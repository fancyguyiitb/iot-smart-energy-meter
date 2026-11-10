"""The time-series storage interface the API is written against.

Two implementations: :mod:`storage.sqlite_store` (local development, zero setup) and
:mod:`storage.influx_store` (cloud). Both use the same point identity -
(device, phase, timestamp) - so re-sending a batch overwrites instead of duplicating,
which makes the device's at-least-once sync effectively exactly-once.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from utils.models import READING_FIELDS, Reading

ENERGY_PHASES = ("R", "Y", "B")


class StorageError(RuntimeError):
    """The backing store failed; the API turns this into 503 so the device retries."""


class TimeSeriesStore(ABC):
    fields = READING_FIELDS

    @abstractmethod
    def write_readings(self, device_id: str, readings: list[Reading]) -> int:
        """Persist readings durably before returning. Returns the number written."""

    @abstractmethod
    def latest(self, device_id: str) -> dict[str, dict]:
        """{phase: {"timestamp": iso, <field>: value, ...}} - newest reading per phase."""

    @abstractmethod
    def series(self, device_id: str, start: datetime, end: datetime, fields: list[str],
               phase: str | None = None, every_s: int | None = None) -> dict[str, list[dict]]:
        """{phase: [{"timestamp": iso, <field>: value}, ...]}; averaged per ``every_s`` bucket if given."""

    @abstractmethod
    def stats(self, device_id: str, start: datetime, end: datetime, field: str, phase: str) -> dict:
        """{"avg", "min", "max", "count"} of one field over raw (not downsampled) data."""

    @abstractmethod
    def energy_buckets(self, device_id: str, start: datetime, end: datetime, bucket_s: int,
                       tz_offset_s: int, phase: str | None = None) -> dict[str, list[dict]]:
        """Energy *consumed* per bucket: {phase: [{"start": iso, "kwh": float}, ...]}.

        Computed as the sum of positive steps of the cumulative ``energy_kwh`` counter, so
        a counter reset doesn't produce negative (or wildly wrong) consumption. Buckets
        are aligned to local time via ``tz_offset_s`` (e.g. IST midnight).
        """

    def last_energy(self, device_id: str) -> dict[str, dict]:
        latest = self.latest(device_id)
        return {p: {"timestamp": v["timestamp"], "energy_kwh": v.get("energy_kwh")}
                for p, v in latest.items() if p in ENERGY_PHASES}

    def ping(self) -> None:
        """Raise if the store is unreachable."""

    def close(self) -> None:
        pass
