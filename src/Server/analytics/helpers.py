"""Module containing helper functions for analytics."""

from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo  # Python 3.9+
from fastapi import HTTPException
from influxdb_client import InfluxDBClient, Point, WritePrecision
from config import settings
from utils.sprint import Logger

# Timezone
INDIA_TZ = ZoneInfo("Asia/Kolkata")

BUCKET = settings.influxdb_bucket
ORG = settings.influxdb_org
TOKEN = settings.influxdb_token
URL = settings.influxdb_url

client = InfluxDBClient(url=URL, token=TOKEN)
write_api = client.write_api()
query_api = client.query_api()

l = Logger.get_instance(debug=True)


def get_day_bounds(target_date: date):
    """Return start and end datetime objects for a given date (in Asia/Kolkata)."""
    start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=INDIA_TZ)
    end = start + timedelta(days=1)
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(
        ZoneInfo("UTC")
    )  # convert for InfluxDB


def generate_power_analytics(target_date: date, phase: str, device_id: str):
    """Generate analytics for power data on the target date."""
    start, end = get_day_bounds(target_date)
    query = f'''
        from(bucket: "{BUCKET}")
          |> range(start: {start.isoformat()}, stop: {end.isoformat()})
          |> filter(fn: (r) => r["_measurement"] == "power_data")
          |> filter(fn: (r) => r["phase"] == "{phase}" and r["device_id"] == "{device_id}")
          |> filter(fn: (r) => r["_field"] == "power_watt")
    '''
    result = query_api.query(org=ORG, query=query)
    values = [record.get_value() for table in result for record in table.records]

    if not values:
        raise HTTPException(
            status_code=404, detail="No power data found for this date."
        )

    avg_power = sum(values) / len(values)
    max_power = max(values)
    min_power = min(values)

    point = (
        Point("power_analytics")
        .tag("device_id", device_id)
        .tag("phase", phase)
        .field("avg_power_watt", float(avg_power))
        .field("max_power_watt", float(max_power))
        .field("min_power_watt", float(min_power))
        .time(datetime.now(INDIA_TZ), WritePrecision.NS)
    )
    write_api.write(bucket=BUCKET, org=ORG, record=point)
    return {
        "avg_power_watt": avg_power,
        "max_power_watt": max_power,
        "min_power_watt": min_power,
    }


def fetch_stored_power_analytics(target_date: date, phase: str, device_id: str):
    """Fetch stored power analytics for a given date from InfluxDB."""
    start, end = get_day_bounds(target_date)
    query = f'''
        from(bucket: "{BUCKET}")
          |> range(start: {start.isoformat()}, stop: {end.isoformat()})
          |> filter(fn: (r) => r["_measurement"] == "power_analytics")
          |> filter(fn: (r) => r["phase"] == "{phase}" and r["device_id"] == "{device_id}")
    '''
    result = query_api.query(org=ORG, query=query)
    analytics = {
        record.get_field(): record.get_value()
        for table in result
        for record in table.records
    }
    if not analytics:
        analytics = generate_power_analytics(target_date, phase, device_id)
        raise HTTPException(
            status_code=404, detail="No stored power analytics found for this date."
        )
    return analytics


def generate_energy_analytics(target_date: date, phase: str, device_id: str):
    """Generate analytics for energy data on the target date."""
    start, end = get_day_bounds(target_date)
    query = f'''
        from(bucket: "{BUCKET}")
          |> range(start: {start.isoformat()}, stop: {end.isoformat()})
          |> filter(fn: (r) => r["_measurement"] == "power_data")
          |> filter(fn: (r) => r["phase"] == "{phase}" and r["device_id"] == "{device_id}")
          |> filter(fn: (r) => r["_field"] == "energy_kwh")
    '''
    result = query_api.query(org=ORG, query=query)
    values = [record.get_value() for table in result for record in table.records]

    if not values:
        l.dprint("No energy data found for this date: ", start, end, phase, device_id)
        raise HTTPException(
            status_code=404, detail="No energy data found for this date."
        )

    avg_energy = sum(values) / len(values)
    max_energy = max(values)
    min_energy = min(values)

    point = (
        Point("energy_analytics")
        .tag("device_id", device_id)
        .tag("phase", phase)
        .field("avg_energy_kwh", float(avg_energy))
        .field("max_energy_kwh", float(max_energy))
        .field("min_energy_kwh", float(min_energy))
        .time(datetime.now(INDIA_TZ), WritePrecision.NS)
    )
    write_api.write(bucket=BUCKET, org=ORG, record=point)
    return {
        "avg_energy_kwh": avg_energy,
        "max_energy_kwh": max_energy,
        "min_energy_kwh": min_energy,
    }


def fetch_stored_energy_analytics(target_date: date, phase: str, device_id: str):
    """Fetch stored energy analytics for a given date from InfluxDB."""
    start, end = get_day_bounds(target_date)
    query = f'''
        from(bucket: "{BUCKET}")
          |> range(start: {start.isoformat()}, stop: {end.isoformat()})
          |> filter(fn: (r) => r["_measurement"] == "energy_analytics")
          |> filter(fn: (r) => r["phase"] == "{phase}" and r["device_id"] == "{device_id}")
    '''
    result = query_api.query(org=ORG, query=query)
    analytics = {
        record.get_field(): record.get_value()
        for table in result
        for record in table.records
    }
    if not analytics:
        analytics = generate_energy_analytics(target_date, phase, device_id)
        l.dprint("No points found for this date. Generating new analytics...")

    return analytics


def fetch_power_data(target_date: date, phase: str, device_id: str):
    """Fetch power data for a given date from InfluxDB."""

    start, end = get_day_bounds(target_date)

    query = f"""
    from(bucket: "{BUCKET}")
      |> range(start: {start.isoformat()}, stop: {end.isoformat()})
      |> filter(fn: (r) => r["_measurement"] == "power_data")
      |> filter(fn: (r) => r.device_id == "{device_id}" and r.phase == "{phase}")
      |> group(columns: ["phase"])  
      |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")  
      |> keep(columns: ["_time", "phase", "power_watt"])  // Keep only relevant fields
    """

    try:
        tables = query_api.query(query, org=ORG)
    except Exception as e:
        l.dprint(f"Error fetching data: {e}")
        return {}
    power_data = []
    for table in tables:
        for record in table.records:
            timestamp = record.get_time().isoformat()
            phase = record.values.get("phase", "Unknown")

            power_data.append(
                {
                    "timestamp": timestamp,
                    "power_watt": record.values.get("power_watt", None),
                }
            )

    if not power_data:
        l.dprint("No power data found for this date.")

    return power_data


def fetch_energy_data(target_date: date, phase: str, device_id: str):
    """Fetch power data for a given date from InfluxDB."""

    start, end = get_day_bounds(target_date)

    query = f"""
    from(bucket: "{BUCKET}")
      |> range(start: {start.isoformat()}, stop: {end.isoformat()})
      |> filter(fn: (r) => r["_measurement"] == "power_data")
      |> filter(fn: (r) => r.device_id == "{device_id}" and r.phase == "{phase}")
      |> group(columns: ["phase"])  
      |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")  
      |> keep(columns: ["_time", "phase", "energy_kwh"])  // Keep only relevant fields
    """

    try:
        tables = query_api.query(query, org=ORG)
    except Exception as e:
        l.dprint(f"Error fetching data: {e}")
        return {}
    energy_data = []
    for table in tables:
        for record in table.records:
            timestamp = record.get_time().isoformat()
            phase = record.values.get("phase", "Unknown")

            energy_data.append(
                {
                    "timestamp": timestamp,
                    "energy_kwh": record.values.get("energy_kwh", None),
                }
            )

    if not energy_data:
        l.dprint("No energy data found for this date.")

    return energy_data
