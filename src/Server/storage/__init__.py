"""Storage backend selection (``STORAGE_BACKEND=sqlite|influx``)."""

from __future__ import annotations

from config import settings
from storage.base import StorageError, TimeSeriesStore

_store: TimeSeriesStore | None = None


def get_store() -> TimeSeriesStore:
    global _store
    if _store is None:
        if settings.storage_backend == "influx":
            from storage.influx_store import InfluxStore

            _store = InfluxStore(settings.influxdb_url, settings.influxdb_token,
                                 settings.influxdb_org, settings.influxdb_bucket)
        else:
            from storage.sqlite_store import SQLiteStore

            _store = SQLiteStore(settings.timeseries_db)
    return _store


def close_store() -> None:
    global _store
    if _store is not None:
        _store.close()
        _store = None


__all__ = ["get_store", "close_store", "StorageError", "TimeSeriesStore"]
