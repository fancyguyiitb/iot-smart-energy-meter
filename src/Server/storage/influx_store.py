"""InfluxDB 2.x backend for the cloud deployment.

Fixes compared with the original server code:
* Writes are **synchronous**. ``write_api()`` defaults to batching mode, which returns
  before anything is written and reports errors on a background thread - the server
  answered 201 even when InfluxDB was down, and the device then dropped the data.
* Device ids and phases are passed as Flux query ``params``, never pasted into the query
  text (the old f-strings allowed Flux injection through query parameters).
* "Latest" uses ``last()`` instead of sorting a whole year of data.

NOTE: developed against the same interface as the SQLite backend, which is what the
local test-suite exercises. Run the suite against InfluxDB (see deploy/docker-compose.yml)
before the cloud cut-over.
"""

from __future__ import annotations

from datetime import datetime

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from storage.base import ENERGY_PHASES, StorageError, TimeSeriesStore
from utils.models import READING_FIELDS, Reading

MEASUREMENT = "power_data"


def _flux_time(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


class InfluxStore(TimeSeriesStore):
    def __init__(self, url: str, token: str, org: str, bucket: str):
        self.org, self.bucket = org, bucket
        self.client = InfluxDBClient(url=url, token=token, org=org, timeout=10_000)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.query_api = self.client.query_api()

    def _query(self, flux: str, **params):
        try:
            return self.query_api.query(flux, org=self.org, params={"bucket": self.bucket, **params})
        except Exception as e:  # network / auth / query errors
            raise StorageError(str(e)) from e

    def write_readings(self, device_id: str, readings: list[Reading]) -> int:
        points = []
        for r in readings:
            p = Point(MEASUREMENT).tag("device_id", device_id).tag("phase", r.phase)
            for f in READING_FIELDS:
                p = p.field(f, float(getattr(r, f)))
            points.append(p.time(r.time, WritePrecision.MS))
        try:
            self.write_api.write(bucket=self.bucket, org=self.org, record=points)
        except Exception as e:
            raise StorageError(str(e)) from e
        return len(points)

    def latest(self, device_id: str) -> dict[str, dict]:
        flux = f'''
            from(bucket: params.bucket)
              |> range(start: -30d)
              |> filter(fn: (r) => r._measurement == "{MEASUREMENT}" and r.device_id == params.device_id)
              |> last()
              |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        out = {}
        for table in self._query(flux, device_id=device_id):
            for rec in table.records:
                phase = rec.values.get("phase")
                row = {"timestamp": rec.get_time().isoformat(), **{f: rec.values.get(f) for f in READING_FIELDS}}
                if phase and (phase not in out or row["timestamp"] > out[phase]["timestamp"]):
                    out[phase] = row
        return out

    def series(self, device_id, start, end, fields, phase=None, every_s=None):
        fields = [f for f in fields if f in READING_FIELDS]
        field_set = "[" + ", ".join(f'"{f}"' for f in fields) + "]"  # from an allow-list
        window = f"|> aggregateWindow(every: {int(every_s)}s, fn: mean, createEmpty: false)" if every_s else ""
        phase_filter = "and r.phase == params.phase" if phase else ""
        flux = f'''
            fields = {field_set}
            from(bucket: params.bucket)
              |> range(start: time(v: params.start), stop: time(v: params.stop))
              |> filter(fn: (r) => r._measurement == "{MEASUREMENT}" and r.device_id == params.device_id {phase_filter})
              |> filter(fn: (r) => contains(value: r._field, set: fields))
              {window}
              |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
              |> group(columns: ["phase"])
              |> sort(columns: ["_time"])
        '''
        params = {"device_id": device_id, "start": _flux_time(start), "stop": _flux_time(end)}
        if phase:
            params["phase"] = phase
        out: dict[str, list[dict]] = {}
        for table in self._query(flux, **params):
            for rec in table.records:
                out.setdefault(rec.values.get("phase"), []).append(
                    {"timestamp": rec.get_time().isoformat(), **{f: rec.values.get(f) for f in fields}})
        return out

    def stats(self, device_id, start, end, field, phase):
        if field not in READING_FIELDS:
            raise ValueError(field)
        base = f'''
            data = from(bucket: params.bucket)
              |> range(start: time(v: params.start), stop: time(v: params.stop))
              |> filter(fn: (r) => r._measurement == "{MEASUREMENT}" and r.device_id == params.device_id
                                   and r.phase == params.phase and r._field == "{field}")
        '''
        params = {"device_id": device_id, "phase": phase, "start": _flux_time(start), "stop": _flux_time(end)}
        result = {}
        for name in ("mean", "min", "max", "count"):
            tables = self._query(base + f"data |> {name}()", **params)
            values = [rec.get_value() for t in tables for rec in t.records]
            result[name] = values[0] if values else None
        return {"avg": result["mean"], "min": result["min"], "max": result["max"], "count": result["count"] or 0}

    def energy_buckets(self, device_id, start, end, bucket_s, tz_offset_s, phase=None):
        phase_filter = "and r.phase == params.phase" if phase else ""
        flux = f'''
            import "timezone"
            from(bucket: params.bucket)
              |> range(start: time(v: params.start), stop: time(v: params.stop))
              |> filter(fn: (r) => r._measurement == "{MEASUREMENT}" and r.device_id == params.device_id
                                   and r._field == "energy_kwh" {phase_filter})
              |> filter(fn: (r) => r.phase == "R" or r.phase == "Y" or r.phase == "B")
              |> difference(nonNegative: true)
              |> aggregateWindow(every: {int(bucket_s)}s, fn: sum, createEmpty: false, timeSrc: "_start",
                                 location: timezone.fixed(offset: {int(tz_offset_s)}s))
        '''
        params = {"device_id": device_id, "start": _flux_time(start), "stop": _flux_time(end)}
        if phase:
            params["phase"] = phase
        out: dict[str, list[dict]] = {}
        for table in self._query(flux, **params):
            for rec in table.records:
                if rec.values.get("phase") in ENERGY_PHASES:
                    out.setdefault(rec.values["phase"], []).append(
                        {"start": rec.get_time().isoformat(), "kwh": rec.get_value() or 0.0})
        return out

    def ping(self) -> None:
        if not self.client.ping():
            raise StorageError("InfluxDB ping failed")

    def close(self) -> None:
        self.client.close()
