"""Local SQLite store on the Pi (store-and-forward buffer + data for the touchscreen GUI).

Several processes share this file (sampler, sync, failure logger, GUI), so it runs in
WAL mode: readers never block the writer and vice versa.

Fixes compared with the original version:
* One transaction per sample instead of one connection + one commit per phase.
* No ``SELECT COUNT(*)`` over the whole table on every insert (the real cause of the GUI
  lag described in the README); pruning runs periodically instead.
* Pruning deletes only rows that were already synced: unsynced data is never dropped.
* Indexes on (phase, id), (sync, id) and timestamp so GUI queries don't scan the table.
* The "last energy" lookup returns the *latest* value, not ``MAX()`` (which undid resets).
* ``daily_energy`` keeps one row per day and phase forever, so history survives pruning.
* Timestamps leave the device as UTC ISO-8601 (they were IST with a bogus ``Z`` suffix).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Iterable

from config import DB_PATH, PHASES, RETENTION_DAYS, TZ
from sprint import Logger

DB_NAME = DB_PATH  # kept for older imports
l = Logger.get_instance(debug=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS power_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase TEXT,
    voltage_rms REAL,
    current_rms REAL,
    active_power REAL,
    reactive_power REAL,
    apparent_power REAL,
    energy_kwh REAL,
    voltage_thd REAL,
    current_thd REAL,
    power_factor REAL,
    voltage_freq REAL,
    timestamp TEXT,
    sync BOOLEAN DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_power_phase_id ON power_data(phase, id);
CREATE INDEX IF NOT EXISTS idx_power_sync_id ON power_data(sync, id);
CREATE INDEX IF NOT EXISTS idx_power_timestamp ON power_data(timestamp);

CREATE TABLE IF NOT EXISTS power_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase TEXT NOT NULL,
    failure_time TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_energy (
    day TEXT NOT NULL,
    phase TEXT NOT NULL,
    kwh REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (day, phase)
);

CREATE TABLE IF NOT EXISTS meter_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

COLUMNS = (
    "phase", "voltage_rms", "current_rms", "active_power", "reactive_power", "apparent_power",
    "energy_kwh", "voltage_thd", "current_thd", "power_factor", "voltage_freq", "timestamp",
)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def now_local_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="milliseconds")


def to_utc_iso(local_iso: str) -> str:
    """'2025-04-01T10:00:00.123+05:30' -> '2025-04-01T04:30:00.123+00:00'."""
    dt = datetime.fromisoformat(local_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


# --------------------------------------------------------------------------- writes
def insert_samples(rows: Iterable[dict], energy_deltas_kwh: dict[str, float] | None = None,
                   day: str | None = None) -> None:
    """Insert one sample (all phases + neutral) and update today's energy, atomically."""
    rows = list(rows)
    conn = connect()
    try:
        with conn:
            conn.executemany(
                f"INSERT INTO power_data ({', '.join(COLUMNS)}, sync) VALUES ({', '.join('?' * len(COLUMNS))}, 0)",
                [tuple(r.get(c) for c in COLUMNS) for r in rows],
            )
            if energy_deltas_kwh:
                conn.executemany(
                    "INSERT INTO daily_energy (day, phase, kwh) VALUES (?, ?, ?) "
                    "ON CONFLICT(day, phase) DO UPDATE SET kwh = kwh + excluded.kwh",
                    [(day, phase, kwh) for phase, kwh in energy_deltas_kwh.items() if kwh > 0],
                )
    finally:
        conn.close()


def insert_power_data(phase, voltage_rms, current_rms, active_power, reactive_power, apparent_power,
                      voltage_thd, current_thd, power_factor, voltage_freq, timestamp,
                      energy_kwh=None, sync=False):
    """Backwards-compatible single-row insert."""
    insert_samples([{
        "phase": phase, "voltage_rms": voltage_rms, "current_rms": current_rms,
        "active_power": active_power, "reactive_power": reactive_power,
        "apparent_power": apparent_power, "energy_kwh": energy_kwh or 0.0,
        "voltage_thd": voltage_thd, "current_thd": current_thd, "power_factor": power_factor,
        "voltage_freq": voltage_freq, "timestamp": timestamp,
    }])


def prune_synced(retention_days: float = RETENTION_DAYS) -> int:
    """Delete synced rows older than the retention window. Never touches unsynced rows."""
    cutoff = (datetime.now(TZ) - timedelta(days=retention_days)).isoformat(timespec="milliseconds")
    conn = connect()
    try:
        with conn:
            cur = conn.execute("DELETE FROM power_data WHERE sync = 1 AND timestamp < ?", (cutoff,))
        if cur.rowcount:
            l.iprint(f"Pruned {cur.rowcount} synced rows older than {retention_days} days")
        return cur.rowcount
    finally:
        conn.close()


# --------------------------------------------------------------------------- sync
def get_unsynced_data(limit: int = 500) -> list[dict]:
    """Oldest unsynced rows first, formatted for the server's ingest API."""
    conn = connect()
    try:
        rows = conn.execute(
            f"SELECT id, {', '.join(COLUMNS)} FROM power_data WHERE sync = 0 ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()

    formatted = []
    for row in rows:
        r = dict(zip(("id",) + COLUMNS, row))
        formatted.append({
            "id": r["id"],
            "phase": r["phase"],
            "voltage_rms": r["voltage_rms"] or 0.0,
            "current_rms": r["current_rms"] or 0.0,
            "power_watt": r["active_power"] or 0.0,
            "power_var": r["reactive_power"] or 0.0,
            "power_va": r["apparent_power"] or 0.0,
            "energy_kwh": r["energy_kwh"] or 0.0,
            "voltage_thd": r["voltage_thd"] or 0.0,
            "current_thd": r["current_thd"] or 0.0,
            "power_factor": r["power_factor"] or 0.0,
            "voltage_freq": r["voltage_freq"] or 0.0,
            "time": to_utc_iso(r["timestamp"]),
        })
    return formatted


def count_unsynced() -> int:
    conn = connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM power_data WHERE sync = 0").fetchone()[0]
    finally:
        conn.close()


def update_row_sync_status(row_ids):
    """Marks the given row IDs as synced, in one transaction."""
    if not row_ids:
        return 0
    conn = connect()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE power_data SET sync = 1 WHERE id IN ({})".format(",".join("?" * len(row_ids))),
                tuple(row_ids),
            )
        return cur.rowcount
    except Exception as e:
        l.eprint("Error updating sync status:", e)
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------- energy
def get_last_energy(phase: str) -> tuple[float, str | None]:
    """Latest stored cumulative energy for a phase and its timestamp (local ISO)."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT energy_kwh, timestamp FROM power_data WHERE phase = ? ORDER BY id DESC LIMIT 1", (phase,)
        ).fetchone()
    except sqlite3.Error as e:
        l.eprint("Error fetching last energy:", e)
        return 0.0, None
    finally:
        conn.close()
    return (row[0] or 0.0, row[1]) if row else (0.0, None)


def get_last_max_energy(phase):
    """Deprecated name kept for compatibility; returns the latest (not the max) value."""
    return get_last_energy(phase)[0]


def get_daily_energy(start_day: str, end_day: str) -> dict[str, dict[str, float]]:
    """{phase: {YYYY-MM-DD: kWh}} for days in [start_day, end_day]."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT day, phase, kwh FROM daily_energy WHERE day BETWEEN ? AND ?", (start_day, end_day)
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, dict[str, float]] = {p: {} for p in PHASES}
    for day, phase, kwh in rows:
        out.setdefault(phase, {})[day] = kwh
    return out


# --------------------------------------------------------------------------- cross-process state
def set_state(key: str, value: str) -> None:
    conn = connect()
    try:
        with conn:
            conn.execute("INSERT INTO meter_state (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    finally:
        conn.close()


def get_state(key: str) -> str | None:
    conn = connect()
    try:
        row = conn.execute("SELECT value FROM meter_state WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def request_energy_reset() -> str:
    """Called by the GUI process; the sampler process picks it up on its next sample."""
    token = now_local_iso()
    set_state("energy_reset_requested", token)
    return token


def pending_energy_reset() -> str | None:
    requested = get_state("energy_reset_requested")
    if requested and requested != get_state("energy_reset_handled"):
        return requested
    return None


def ack_energy_reset(token: str) -> None:
    set_state("energy_reset_handled", token)


# --------------------------------------------------------------------------- power events
def insert_failure(phase: str, timestamp: str, keep: int = 5) -> None:
    conn = connect()
    try:
        with conn:
            conn.execute("INSERT INTO power_events (phase, failure_time) VALUES (?, ?)", (phase, timestamp))
            conn.execute(
                """DELETE FROM power_events WHERE phase = ? AND id NOT IN (
                       SELECT id FROM power_events WHERE phase = ? ORDER BY failure_time DESC LIMIT ?)""",
                (phase, phase, keep),
            )
    finally:
        conn.close()


def get_failures() -> list[tuple[str, str]]:
    conn = connect()
    try:
        return conn.execute("SELECT phase, failure_time FROM power_events ORDER BY failure_time DESC").fetchall()
    finally:
        conn.close()
