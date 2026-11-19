"""Relational metadata: users, devices, one-time claim nonces and the relay audit log.

This used to live in InfluxDB as time-series points queried with ``range(start: -30d)``,
so every account and device key silently disappeared after 30 days, "deleting" an old
user was a read query that deleted nothing, and a username's fields could be mixed
across sign-ups. A relational table with constraints fixes all of that.

Local: SQLite file (``METADATA_DB``). The SQL is plain enough to port to Postgres when
moving to the cloud.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    name TEXT,
    key_hash TEXT NOT NULL,
    claim_key TEXT NOT NULL,
    owner_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    claimed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_devices_owner ON devices(owner_id);
CREATE TABLE IF NOT EXISTS claim_nonces (
    nonce TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    used_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relay_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    user_id INTEGER,
    phase TEXT,
    command TEXT NOT NULL,
    ok INTEGER NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_relay_audit_device ON relay_audit(device_id, id);
-- Relay shadow: the state the owner last asked for, per phase (reported state comes from the meter).
CREATE TABLE IF NOT EXISTS relay_shadow (
    device_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    desired TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (device_id, phase)
);
-- Electricity tariff per user (JSON), used for bill forecasts.
CREATE TABLE IF NOT EXISTS tariffs (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    tariff TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- Password reset: only a hash of the token is stored; single use; short expiry.
CREATE TABLE IF NOT EXISTS reset_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class ClaimError(Exception):
    """Raised when a sign-up / claim can't proceed. ``status`` is the HTTP status to return."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MetadataDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
            if "email" not in cols:  # migrate databases from before password reset existed
                conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
            if "token_version" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ users
    def get_user(self, user_id: int) -> dict | None:
        with self.connect() as c:
            row = c.execute("SELECT id, username, email, token_version, created_at FROM users WHERE id = ?",
                            (user_id,)).fetchone()
        return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict | None:
        with self.connect() as c:
            row = c.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        return dict(row) if row else None

    def set_email(self, user_id: int, email: str | None) -> None:
        """Raises ClaimError(409) if another account uses the address."""
        try:
            with self.connect() as c:
                c.execute("UPDATE users SET email = ? WHERE id = ?", (email.strip().lower() if email else None, user_id))
        except sqlite3.IntegrityError:
            raise ClaimError(409, "That email address is already used by another account")

    def set_password(self, user_id: int, password_hash: str) -> int:
        """Change the password, invalidate every issued token and pending reset link.
        Returns the new token version."""
        with self.connect() as c:
            c.execute("UPDATE users SET password_hash = ?, token_version = token_version + 1 WHERE id = ?",
                      (password_hash, user_id))
            c.execute("DELETE FROM reset_tokens WHERE user_id = ?", (user_id,))
            return c.execute("SELECT token_version FROM users WHERE id = ?", (user_id,)).fetchone()[0]

    def bump_token_version(self, user_id: int) -> int:
        """Log out every session of a user."""
        with self.connect() as c:
            c.execute("UPDATE users SET token_version = token_version + 1 WHERE id = ?", (user_id,))
            return c.execute("SELECT token_version FROM users WHERE id = ?", (user_id,)).fetchone()[0]

    # ------------------------------------------------------------------ password reset
    def create_reset_token(self, user_id: int, token_hash: str, expires_at: datetime) -> None:
        """Only one live reset link per user: issuing a new one revokes older ones."""
        with self.connect() as c:
            c.execute("DELETE FROM reset_tokens WHERE user_id = ?", (user_id,))
            c.execute("INSERT INTO reset_tokens (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                      (token_hash, user_id, expires_at.isoformat(), _now()))

    def consume_reset_token(self, token_hash: str) -> int | None:
        """Atomically use a reset token. Returns the user id, or None if unknown/expired/used."""
        with self.connect() as c:
            row = c.execute("DELETE FROM reset_tokens WHERE token_hash = ? RETURNING user_id, expires_at",
                            (token_hash,)).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            return None
        return row["user_id"]

    def get_user_by_username(self, username: str) -> dict | None:
        with self.connect() as c:
            row = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ devices
    def upsert_device(self, device_id: str, key_hash: str, claim_key: str, name: str | None = None) -> None:
        with self.connect() as c:
            c.execute(
                """INSERT INTO devices (device_id, name, key_hash, claim_key, created_at) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(device_id) DO UPDATE SET key_hash = excluded.key_hash,
                       claim_key = excluded.claim_key, name = COALESCE(excluded.name, devices.name)""",
                (device_id, name, key_hash, claim_key, _now()),
            )

    def get_device(self, device_id: str) -> dict | None:
        with self.connect() as c:
            row = c.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return dict(row) if row else None

    def list_devices(self) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT device_id, name, owner_id, created_at, claimed_at FROM devices")]

    def devices_for_user(self, user_id: int) -> list[dict]:
        with self.connect() as c:
            rows = c.execute("SELECT device_id, name, claimed_at FROM devices WHERE owner_id = ? ORDER BY claimed_at",
                             (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def release_device(self, device_id: str, user_id: int) -> bool:
        with self.connect() as c:
            cur = c.execute("UPDATE devices SET owner_id = NULL, claimed_at = NULL WHERE device_id = ? AND owner_id = ?",
                            (device_id, user_id))
        return cur.rowcount == 1

    # ------------------------------------------------------------------ claiming
    def claim(self, device_id: str, nonce: str, *, user_id: int | None = None,
              new_user: tuple | None = None) -> int:
        """Atomically: burn the one-time nonce, create the user (optional), bind the device.

        Returns the owner's user id. Raises ClaimError on any conflict; nothing is written then.
        """
        with self.connect() as c:
            try:
                c.execute("INSERT INTO claim_nonces (nonce, device_id, used_at) VALUES (?, ?, ?)",
                          (nonce, device_id, _now()))
            except sqlite3.IntegrityError:
                raise ClaimError(400, "This sign-up code was already used. Show a new QR code on the meter.")
            if new_user is not None:
                username, password_hash, *rest = new_user
                email = rest[0].strip().lower() if rest and rest[0] else None
                try:
                    cur = c.execute("INSERT INTO users (username, password_hash, email, created_at) VALUES (?, ?, ?, ?)",
                                    (username, password_hash, email, _now()))
                except sqlite3.IntegrityError as e:
                    raise ClaimError(409, "That email address is already used" if "email" in str(e)
                                     else "Username already taken")
                user_id = cur.lastrowid
            cur = c.execute("UPDATE devices SET owner_id = ?, claimed_at = ? WHERE device_id = ? AND owner_id IS NULL",
                            (user_id, _now(), device_id))
            if cur.rowcount != 1:
                raise ClaimError(409, "This meter is already registered to another account. "
                                      "The current owner must release it first.")
            return user_id

    # ------------------------------------------------------------------ relay shadow
    def set_desired(self, device_id: str, phases: list[str], desired: str) -> None:
        with self.connect() as c:
            c.executemany("INSERT INTO relay_shadow (device_id, phase, desired, updated_at) VALUES (?, ?, ?, ?) "
                          "ON CONFLICT(device_id, phase) DO UPDATE SET desired = excluded.desired, "
                          "updated_at = excluded.updated_at", [(device_id, p, desired, _now()) for p in phases])

    def get_desired(self, device_id: str) -> dict[str, str]:
        with self.connect() as c:
            return {r["phase"]: r["desired"] for r in
                    c.execute("SELECT phase, desired FROM relay_shadow WHERE device_id = ?", (device_id,))}

    # ------------------------------------------------------------------ tariff
    def get_tariff(self, user_id: int) -> dict | None:
        import json

        with self.connect() as c:
            row = c.execute("SELECT tariff FROM tariffs WHERE user_id = ?", (user_id,)).fetchone()
        return json.loads(row["tariff"]) if row else None

    def set_tariff(self, user_id: int, tariff: dict) -> None:
        import json

        with self.connect() as c:
            c.execute("INSERT INTO tariffs (user_id, tariff, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) "
                      "DO UPDATE SET tariff = excluded.tariff, updated_at = excluded.updated_at",
                      (user_id, json.dumps(tariff), _now()))

    # ------------------------------------------------------------------ audit
    def log_relay(self, device_id: str, user_id: int | None, phase: str | None, command: str, ok: bool,
                  detail: str | None = None) -> None:
        with self.connect() as c:
            c.execute("INSERT INTO relay_audit (device_id, user_id, phase, command, ok, detail, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)", (device_id, user_id, phase, command, int(ok), detail, _now()))

    def relay_history(self, device_id: str, limit: int = 20) -> list[dict]:
        with self.connect() as c:
            rows = c.execute(
                """SELECT a.created_at, a.phase, a.command, a.ok, a.detail, u.username
                   FROM relay_audit a LEFT JOIN users u ON u.id = a.user_id
                   WHERE a.device_id = ? ORDER BY a.id DESC LIMIT ?""", (device_id, limit)).fetchall()
        return [dict(r) for r in rows]


_db: MetadataDB | None = None


def get_metadata_db() -> MetadataDB:
    global _db
    if _db is None:
        _db = MetadataDB(settings.metadata_db)
    return _db
