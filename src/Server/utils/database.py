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
            row = c.execute("SELECT id, username, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

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
              new_user: tuple[str, str] | None = None) -> int:
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
                username, password_hash = new_user
                try:
                    cur = c.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                                    (username, password_hash, _now()))
                except sqlite3.IntegrityError:
                    raise ClaimError(409, "Username already taken")
                user_id = cur.lastrowid
            cur = c.execute("UPDATE devices SET owner_id = ?, claimed_at = ? WHERE device_id = ? AND owner_id IS NULL",
                            (user_id, _now(), device_id))
            if cur.rowcount != 1:
                raise ClaimError(409, "This meter is already registered to another account. "
                                      "The current owner must release it first.")
            return user_id

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
