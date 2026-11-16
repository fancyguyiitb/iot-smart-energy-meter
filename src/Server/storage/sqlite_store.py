"""SQLite time-series backend for local development.

Raw readings are keyed by (device_id, phase, ts) with ``INSERT OR REPLACE`` - the same
identity semantics as an InfluxDB point - and stored as UTC epoch seconds.

Rollups and retention
---------------------
* ``readings_hourly`` / ``readings_daily`` hold, per phase and bucket: sample count,
  avg/min/max of every measurement, energy consumed in the bucket and the counter's last
  value. Buckets follow *local* time (IST hours start at :30 UTC), so a "day" is a
  calendar day for the user.
* Every write marks the local hours it touched as dirty (``rollup_dirty``). Maintenance
  re-rolls only dirty hours and the days containing them. So data that arrives late -
  a meter syncing a 6-hour backlog after an outage - lands in the right rollups, and
  re-sent rows (same identity) don't double count.
* Retention: raw data older than ``raw_retention_days`` and hourly rollups older than
  ``hourly_retention_days`` are deleted; daily rollups are kept forever. Raw rows are
  only deleted once their hour has been rolled up.
* Queries for hourly/daily buckets, and for ranges older than the raw window, read the
  rollups. They apply pending rollups first, so they never return stale numbers.
"""

from __future__ import annotations

import sqlite3
import threading
import time as _time
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from storage.base import ENERGY_PHASES, StorageError, TimeSeriesStore
from utils.models import READING_FIELDS, PowerEvent, Reading

ROLLUP_FIELDS = tuple(f for f in READING_FIELDS if f != "energy_kwh")
_ROLLUP_COLS = ", ".join(f"{f}_{s} REAL" for f in ROLLUP_FIELDS for s in ("avg", "min", "max"))
HOUR = 3600
DAY = 86400
RETENTION_EVERY_S = 3600

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS readings (
    device_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    ts REAL NOT NULL,
    {", ".join(f"{f} REAL" for f in READING_FIELDS)},
    PRIMARY KEY (device_id, phase, ts)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS power_events (
    device_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL,
    PRIMARY KEY (device_id, phase, start_ts)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS rollup_dirty (
    device_id TEXT NOT NULL,
    bucket_ts REAL NOT NULL,
    PRIMARY KEY (device_id, bucket_ts)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS readings_hourly (
    device_id TEXT NOT NULL, phase TEXT NOT NULL, bucket_ts REAL NOT NULL, samples INTEGER NOT NULL,
    {_ROLLUP_COLS}, consumed_kwh REAL, energy_kwh_last REAL,
    PRIMARY KEY (device_id, phase, bucket_ts)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS readings_daily (
    device_id TEXT NOT NULL, phase TEXT NOT NULL, bucket_ts REAL NOT NULL, samples INTEGER NOT NULL,
    {_ROLLUP_COLS}, consumed_kwh REAL, energy_kwh_last REAL,
    PRIMARY KEY (device_id, phase, bucket_ts)
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
    def __init__(self, path: Path, tz_name: str = "Asia/Kolkata", raw_retention_days: float = 30,
                 hourly_retention_days: float = 400):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.tz = ZoneInfo(tz_name)
        self.raw_retention_s = raw_retention_days * DAY
        self.hourly_retention_s = hourly_retention_days * DAY
        self._local = threading.local()
        self._rollup_lock = threading.Lock()
        self._last_retention = 0.0
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # First start after upgrading: roll up the raw history that predates rollups.
            if conn.execute("SELECT 1 FROM readings LIMIT 1").fetchone() and \
                    not conn.execute("SELECT 1 FROM readings_hourly LIMIT 1").fetchone() and \
                    not conn.execute("SELECT 1 FROM rollup_dirty LIMIT 1").fetchone():
                halves = conn.execute("SELECT DISTINCT device_id, CAST(ts / 1800 AS INTEGER) FROM readings")
                conn.executemany("INSERT OR IGNORE INTO rollup_dirty VALUES (?, ?)",
                                 {(d, self._hour_start(h * 1800)) for d, h in halves})

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    # ------------------------------------------------------------------ local-time buckets
    def _hour_start(self, ts: float) -> float:
        return datetime.fromtimestamp(ts, self.tz).replace(minute=0, second=0, microsecond=0).timestamp()

    def _day_start(self, ts: float) -> float:
        return datetime.combine(datetime.fromtimestamp(ts, self.tz).date(), time.min, tzinfo=self.tz).timestamp()

    def _next_day(self, day_ts: float) -> float:
        d = datetime.fromtimestamp(day_ts, self.tz).date() + timedelta(days=1)
        return datetime.combine(d, time.min, tzinfo=self.tz).timestamp()

    def _raw_cutoff(self) -> float:
        return _time.time() - self.raw_retention_s

    # ------------------------------------------------------------------ writes
    def write_readings(self, device_id: str, readings: list[Reading]) -> int:
        cols = ", ".join(READING_FIELDS)
        rows = [(device_id, r.phase, r.time.timestamp(), *(getattr(r, f) for f in READING_FIELDS))
                for r in readings]
        hours = {(device_id, self._hour_start(r[2])) for r in rows}
        try:
            with self._conn() as conn:
                conn.executemany(
                    f"INSERT OR REPLACE INTO readings (device_id, phase, ts, {cols}) "
                    f"VALUES (?, ?, ?, {', '.join('?' * len(READING_FIELDS))})", rows)
                conn.executemany("INSERT OR IGNORE INTO rollup_dirty (device_id, bucket_ts) VALUES (?, ?)", hours)
        except sqlite3.Error as e:
            raise StorageError(str(e)) from e
        return len(rows)

    # ------------------------------------------------------------------ rollups
    def refresh_rollups(self) -> tuple[int, int]:
        """Re-roll every dirty hour and the days containing them. Returns (hours, days)."""
        with self._rollup_lock:
            conn = self._conn()
            with conn:
                # Claim the dirty set atomically; a write during the re-roll marks its hour
                # dirty again and it is picked up next time.
                dirty = conn.execute("DELETE FROM rollup_dirty RETURNING device_id, bucket_ts").fetchall()
            if not dirty:
                return 0, 0
            days = set()
            try:
                with conn:
                    for device_id, bucket in dirty:
                        self._roll_hour(conn, device_id, bucket)
                        days.add((device_id, self._day_start(bucket)))
                    for device_id, day in days:
                        self._roll_day(conn, device_id, day)
            except sqlite3.Error:
                with conn:  # put the work back so nothing is lost
                    conn.executemany("INSERT OR IGNORE INTO rollup_dirty VALUES (?, ?)", dirty)
                raise
            return len(dirty), len(days)

    def _roll_hour(self, conn, device_id: str, start: float) -> None:
        end = start + HOUR
        aggs = ", ".join(f"AVG({f}), MIN({f}), MAX({f})" for f in ROLLUP_FIELDS)
        rows = conn.execute(f"SELECT phase, COUNT(*), {aggs} FROM readings "
                            "WHERE device_id = ? AND ts >= ? AND ts < ? GROUP BY phase", (device_id, start, end)).fetchall()
        # Consumption counts the step from the previous hour's last reading too (look back 1 h).
        consumed = dict(conn.execute(
            """SELECT phase, SUM(CASE WHEN d > 0 THEN d ELSE 0 END) FROM (
                   SELECT phase, ts, energy_kwh - LAG(energy_kwh) OVER (PARTITION BY phase ORDER BY ts) AS d
                   FROM readings WHERE device_id = ? AND ts >= ? AND ts < ?)
               WHERE ts >= ? GROUP BY phase""", (device_id, start - HOUR, end, start)).fetchall())
        conn.execute("DELETE FROM readings_hourly WHERE device_id = ? AND bucket_ts = ?", (device_id, start))
        for phase, samples, *vals in rows:
            last = conn.execute("SELECT energy_kwh FROM readings WHERE device_id = ? AND phase = ? AND ts >= ? "
                                "AND ts < ? ORDER BY ts DESC LIMIT 1", (device_id, phase, start, end)).fetchone()
            conn.execute(f"INSERT INTO readings_hourly VALUES ({', '.join('?' * (6 + len(vals)))})",
                         (device_id, phase, start, samples, *vals, consumed.get(phase) or 0.0, last[0] if last else None))

    def _roll_day(self, conn, device_id: str, start: float) -> None:
        end = self._next_day(start)
        if not conn.execute("SELECT 1 FROM readings_hourly WHERE device_id = ? AND bucket_ts >= ? AND bucket_ts < ? "
                            "LIMIT 1", (device_id, start, end)).fetchone():
            return  # hourly detail already expired: keep the existing daily row as it is
        aggs = ", ".join(f"SUM({f}_avg * samples) / SUM(samples), MIN({f}_min), MAX({f}_max)" for f in ROLLUP_FIELDS)
        rows = conn.execute(f"SELECT phase, SUM(samples), {aggs}, SUM(consumed_kwh) FROM readings_hourly "
                            "WHERE device_id = ? AND bucket_ts >= ? AND bucket_ts < ? GROUP BY phase",
                            (device_id, start, end)).fetchall()
        conn.execute("DELETE FROM readings_daily WHERE device_id = ? AND bucket_ts = ?", (device_id, start))
        for phase, samples, *vals in rows:
            last = conn.execute("SELECT energy_kwh_last FROM readings_hourly WHERE device_id = ? AND phase = ? "
                                "AND bucket_ts >= ? AND bucket_ts < ? ORDER BY bucket_ts DESC LIMIT 1",
                                (device_id, phase, start, end)).fetchone()
            conn.execute(f"INSERT INTO readings_daily VALUES ({', '.join('?' * (5 + len(vals)))})",
                         (device_id, phase, start, samples, *vals, last[0] if last else None))

    def apply_retention(self) -> tuple[int, int]:
        """Delete expired raw rows (only once rolled up) and expired hourly rollups."""
        conn = self._conn()
        with conn:
            cutoff = self._raw_cutoff()
            pending = conn.execute("SELECT MIN(bucket_ts) FROM rollup_dirty").fetchone()[0]
            if pending is not None:
                cutoff = min(cutoff, pending)  # never delete raw data that isn't rolled up yet
            raw = conn.execute("DELETE FROM readings WHERE ts < ?", (cutoff,)).rowcount
            hourly = conn.execute("DELETE FROM readings_hourly WHERE bucket_ts < ?",
                                  (_time.time() - self.hourly_retention_s,)).rowcount
        return raw, hourly

    def run_maintenance(self) -> dict:
        hours, days = self.refresh_rollups()
        result = {"hours_rolled": hours, "days_rolled": days, "raw_deleted": 0, "hourly_deleted": 0}
        if _time.time() - self._last_retention >= RETENTION_EVERY_S:
            result["raw_deleted"], result["hourly_deleted"] = self.apply_retention()
            self._last_retention = _time.time()
        return result

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
        if (every_s and every_s >= HOUR) or start.timestamp() < self._raw_cutoff():
            return self._rollup_series(device_id, start, end, fields, phase, every_s)
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

    def _rollup_series(self, device_id, start, end, fields, phase, every_s):
        self.refresh_rollups()
        table = "readings_daily" if every_s and every_s >= DAY else "readings_hourly"
        cols = ", ".join("MAX(energy_kwh_last)" if f == "energy_kwh" else f"SUM({f}_avg * samples) / SUM(samples)"
                         for f in fields)
        group = "bucket_ts" if not every_s or every_s in (HOUR, DAY) else f"CAST(bucket_ts / {int(every_s)} AS INTEGER) * {int(every_s)}"
        params: list = [device_id, start.timestamp(), end.timestamp()]
        phase_sql = ""
        if phase:
            phase_sql = " AND phase = ?"
            params.append(phase)
        sql = (f"SELECT phase, {group} AS b, {cols} FROM {table} WHERE device_id = ? AND bucket_ts >= ? "
               f"AND bucket_ts < ?{phase_sql} GROUP BY phase, b ORDER BY phase, b")
        out: dict[str, list[dict]] = {}
        for row in self._conn().execute(sql, params):
            out.setdefault(row[0], []).append({"timestamp": _iso(row[1]), **dict(zip(fields, row[2:]))})
        return out

    def stats(self, device_id, start, end, field, phase):
        (field,) = _check_fields([field])
        if start.timestamp() < self._raw_cutoff() and field != "energy_kwh":
            self.refresh_rollups()
            row = self._conn().execute(
                f"SELECT SUM({field}_avg * samples) / SUM(samples), MIN({field}_min), MAX({field}_max), SUM(samples) "
                "FROM readings_hourly WHERE device_id = ? AND phase = ? AND bucket_ts >= ? AND bucket_ts < ?",
                (device_id, phase, start.timestamp(), end.timestamp())).fetchone()
        else:
            row = self._conn().execute(
                f"SELECT AVG({field}), MIN({field}), MAX({field}), COUNT(*) FROM readings "
                "WHERE device_id = ? AND phase = ? AND ts >= ? AND ts < ?",
                (device_id, phase, start.timestamp(), end.timestamp())).fetchone()
        return {"avg": row[0], "min": row[1], "max": row[2], "count": row[3] or 0}

    def energy_buckets(self, device_id, start, end, bucket_s, tz_offset_s, phase=None):
        if int(bucket_s) in (HOUR, DAY):  # served from the rollups (local-time buckets)
            self.refresh_rollups()
            table = "readings_hourly" if int(bucket_s) == HOUR else "readings_daily"
            params: list = [device_id, start.timestamp(), end.timestamp(), *ENERGY_PHASES]
            phase_sql = f" AND phase IN ({', '.join('?' * len(ENERGY_PHASES))})"
            if phase:
                phase_sql += " AND phase = ?"
                params.append(phase)
            out: dict[str, list[dict]] = {}
            for p, b, kwh in self._conn().execute(
                    f"SELECT phase, bucket_ts, consumed_kwh FROM {table} WHERE device_id = ? AND bucket_ts >= ? "
                    f"AND bucket_ts < ?{phase_sql} ORDER BY phase, bucket_ts", params):
                out.setdefault(p, []).append({"start": _iso(b), "kwh": kwh or 0.0})
            return out
        # Any other bucket size: compute from raw data.
        bucket, off = int(bucket_s), int(tz_offset_s)
        params = [device_id, start.timestamp(), end.timestamp(), *ENERGY_PHASES]
        phase_sql = f" AND phase IN ({', '.join('?' * len(ENERGY_PHASES))})"
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
        out = {}
        for p, b, kwh in self._conn().execute(sql, params):
            out.setdefault(p, []).append({"start": _iso(b * bucket - off), "kwh": kwh or 0.0})
        return out

    # ------------------------------------------------------------------ events
    def write_events(self, device_id: str, events: list[PowerEvent]) -> int:
        try:
            with self._conn() as conn:
                conn.executemany(
                    "INSERT INTO power_events (device_id, phase, start_ts, end_ts) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(device_id, phase, start_ts) DO UPDATE SET end_ts = COALESCE(excluded.end_ts, end_ts)",
                    [(device_id, e.phase, e.start.timestamp(), e.end.timestamp() if e.end else None) for e in events])
        except sqlite3.Error as e:
            raise StorageError(str(e)) from e
        return len(events)

    def events(self, device_id, start, end):
        rows = self._conn().execute(
            "SELECT phase, start_ts, end_ts FROM power_events WHERE device_id = ? AND start_ts >= ? AND start_ts < ? "
            "ORDER BY start_ts DESC", (device_id, start.timestamp(), end.timestamp())).fetchall()
        return [{"phase": p, "start": _iso(s), "end": _iso(e) if e else None,
                 "duration_s": round(e - s, 1) if e else None} for p, s, e in rows]

    def ping(self) -> None:
        self._conn().execute("SELECT 1")
