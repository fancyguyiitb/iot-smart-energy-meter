"""SQLite time-series backend for local development.

Rows are keyed by (device_id, phase, ts) with ``INSERT OR REPLACE`` - the same identity
semantics as an InfluxDB point - and stored as UTC epoch seconds.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from storage.base import ENERGY_PHASES, StorageError, TimeSeriesStore
from utils.models import READING_FIELDS, Reading

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS readings (
    device_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    ts REAL NOT NULL,
    {", ".join(f"{f} REAL" for f in READING_FIELDS)},
    PRIMARY KEY (device_id, phase, ts)
) WITHOUT ROWID;
"""


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds")


def _check_fields(fields: list[str]) -> list[str]:
    bad = [f for f in fields if f not in READING_FIELDS]
    if bad:  # field names are interpolated into SQL, so only allow known columns
        raise ValueError(f"Unknown fields: {bad}")
    return fields


class SQLiteStore(TimeSeriesStore):
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    # ------------------------------------------------------------------ writes
    def write_readings(self, device_id: str, readings: list[Reading]) -> int:
        cols = ", ".join(READING_FIELDS)
        rows = [(device_id, r.phase, r.time.timestamp(), *(getattr(r, f) for f in READING_FIELDS))
                for r in readings]
        try:
            with self._conn() as conn:
                conn.executemany(
                    f"INSERT OR REPLACE INTO readings (device_id, phase, ts, {cols}) "
                    f"VALUES (?, ?, ?, {', '.join('?' * len(READING_FIELDS))})", rows)
        except sqlite3.Error as e:
            raise StorageError(str(e)) from e
        return len(rows)

    # ------------------------------------------------------------------ reads
    def latest(self, device_id: str) -> dict[str, dict]:
        out = {}
        conn = self._conn()
        for phase in (*ENERGY_PHASES, "Neutral"):
            row = conn.execute(
                f"SELECT ts, {', '.join(READING_FIELDS)} FROM readings WHERE device_id = ? AND phase = ? "
                "ORDER BY ts DESC LIMIT 1", (device_id, phase)).fetchone()
            if row:
                out[phase] = {"timestamp": _iso(row[0]), **dict(zip(READING_FIELDS, row[1:]))}
        return out

    def series(self, device_id, start, end, fields, phase=None, every_s=None):
        fields = _check_fields(list(fields))
        params: list = [device_id, start.timestamp(), end.timestamp()]
        phase_sql = ""
        if phase:
            phase_sql = " AND phase = ?"
            params.append(phase)
        if every_s:
            every = int(every_s)
            sql = (f"SELECT phase, CAST(ts / {every} AS INTEGER) * {every} AS b, "
                   f"{', '.join(f'AVG({f})' for f in fields)} FROM readings "
                   f"WHERE device_id = ? AND ts >= ? AND ts < ?{phase_sql} GROUP BY phase, b ORDER BY phase, b")
        else:
            sql = (f"SELECT phase, ts, {', '.join(fields)} FROM readings "
                   f"WHERE device_id = ? AND ts >= ? AND ts < ?{phase_sql} ORDER BY phase, ts")
        out: dict[str, list[dict]] = {}
        for row in self._conn().execute(sql, params):
            out.setdefault(row[0], []).append({"timestamp": _iso(row[1]), **dict(zip(fields, row[2:]))})
        return out

    def stats(self, device_id, start, end, field, phase):
        (field,) = _check_fields([field])
        row = self._conn().execute(
            f"SELECT AVG({field}), MIN({field}), MAX({field}), COUNT(*) FROM readings "
            "WHERE device_id = ? AND phase = ? AND ts >= ? AND ts < ?",
            (device_id, phase, start.timestamp(), end.timestamp())).fetchone()
        return {"avg": row[0], "min": row[1], "max": row[2], "count": row[3]}

    def energy_buckets(self, device_id, start, end, bucket_s, tz_offset_s, phase=None):
        bucket, off = int(bucket_s), int(tz_offset_s)
        params: list = [device_id, start.timestamp(), end.timestamp()]
        phase_sql = f" AND phase IN ({', '.join('?' * len(ENERGY_PHASES))})"
        params += list(ENERGY_PHASES)
        if phase:
            phase_sql += " AND phase = ?"
            params.append(phase)
        sql = f"""
            SELECT phase, CAST((ts + {off}) / {bucket} AS INTEGER) AS b,
                   SUM(CASE WHEN d > 0 THEN d ELSE 0 END)
            FROM (
                SELECT phase, ts, energy_kwh - LAG(energy_kwh) OVER (PARTITION BY phase ORDER BY ts) AS d
                FROM readings WHERE device_id = ? AND ts >= ? AND ts < ?{phase_sql}
            )
            GROUP BY phase, b ORDER BY phase, b
        """
        out: dict[str, list[dict]] = {}
        for p, b, kwh in self._conn().execute(sql, params):
            out.setdefault(p, []).append({"start": _iso(b * bucket - off), "kwh": kwh or 0.0})
        return out

    def ping(self) -> None:
        self._conn().execute("SELECT 1")
