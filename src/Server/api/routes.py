from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from influxdb_client import Point, WritePrecision
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from utils.database import write_api, query_api
from utils.security import verify_token
from config import settings
from utils.sprint import Logger


l = Logger.get_instance(True)
router = APIRouter()
BUCKET = settings.influxdb_bucket
ORG = settings.influxdb_org

INDIA_TZ = ZoneInfo("Asia/Kolkata")


@router.post("/write-data")
async def write_data(power_data: list[dict] = None):
    """Batch write power and energy data to InfluxDB."""
    device_id = "random12"
    points = []
    time_now = datetime.now(timezone.utc)

    if not power_data:
        raise HTTPException(status_code=400, detail="No data provided.")

    for p in power_data:
        try:
            timestamp = datetime.strptime(p["time"], "%Y-%m-%dT%H:%M:%S.%fZ")
        except (KeyError, ValueError, TypeError):
            timestamp = time_now  # Fallback if missing or invalid format

        try:
            point = (
                Point("power_data")
                .tag("device_id", device_id)
                .tag("phase", p["phase"])
                .field("power_watt", float(p["power_watt"]))
                .field("power_var", float(p["power_var"]))
                .field("power_va", float(p["power_va"]))
                .field("voltage_rms", float(p["voltage_rms"]))
                .field("current_rms", float(p["current_rms"]))
                .field("power_factor", float(p["power_factor"]))
                .field("voltage_thd", float(p["voltage_thd"]))
                .field("current_thd", float(p["current_thd"]))
                .field("energy_kwh", float(p["energy_kwh"]))
                .field("voltage_freq", float(p["voltage_freq"]))
                .time(timestamp, WritePrecision.NS)
            )
            points.append(point)
        except KeyError as e:
            raise HTTPException(
                status_code=400, detail=f"Missing required field: {str(e)}"
            )

    if not points:
        raise HTTPException(status_code=400, detail="No valid data to write.")

    try:
        l.dprint("Writing data to InfluxDB..., points: ", points)
        write_api.write(bucket=BUCKET, org=ORG, record=points)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write data: {str(e)}")

    return JSONResponse(
        content={"message": "Data written successfully."}, status_code=201
    )


@router.get("/query-data/")
async def query_data(
    range_hours: int = 240,
    device_id: str = "random12",
    date_str: str = Query(description="Date in YYYY-MM-DD format"),
):
    """Query power and energy data for a specific device, grouped by phase."""

    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception as e:
            return JSONResponse(
                content={"message": f"Invalid date format: {e}"}, status_code=400
            )

        # Use consistent timezone conversion
        start_dt = datetime.combine(target_date, datetime.min.time()).replace(
            tzinfo=INDIA_TZ
        )
        end_dt = start_dt + timedelta(days=1)

        start_iso = start_dt.astimezone(ZoneInfo("UTC")).isoformat()
        end_iso = end_dt.astimezone(ZoneInfo("UTC")).isoformat()

        range_clause = f"range(start: {start_iso}, stop: {end_iso})"
    elif range_hours is not None:
        range_clause = f"range(start: -{range_hours}h)"
    else:
        range_clause = "range(start: -24h)"

    # Flux Query
    query = f"""
    from(bucket: "{BUCKET}")
      |> {range_clause}
      |> filter(fn: (r) => r.device_id == "{device_id}")
      |> group(columns: ["phase"])  // Group by phase
      |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")  // Pivot for structured output
      |> keep(columns: ["_time", "phase", "power_watt", "voltage_rms", "current_rms", "energy_kwh"])  // Keep only relevant fields
    """

    tables = query_api.query(query, org=ORG)
    formatted_results = {}

    for table in tables:
        for record in table.records:
            phase = record.values.get("phase", "Unknown")
            if phase not in formatted_results:
                formatted_results[phase] = []

            formatted_results[phase].append(
                {
                    "timestamp": record.values.get("_time").isoformat(),
                    "power_watt": record.values.get("power_watt", None),
                    "voltage_rms": record.values.get("voltage_rms", None),
                    "current_rms": record.values.get("current_rms", None),
                    "energy_kwh": record.values.get("energy_kwh", None),
                }
            )

    return JSONResponse(content=formatted_results, status_code=200)


@router.get("/fetch-analytics/")
async def fetch_analytics(device_id: str):
    """Fetch analytics data for a given device."""
    query = f"""
    from(bucket: "{BUCKET}")
      |> range(start: -30d)
      |> filter(fn: (r) => r._measurement == "analytics_data")
      |> filter(fn: (r) => r.device_id == "{device_id}")
    """
    tables = query_api.query(query, org=ORG)
    analytics_results = {}

    for table in tables:
        for record in table.records:
            field = record.get_field()
            value = record.get_value()
            analytics_results[field] = value

    return JSONResponse(content=analytics_results, status_code=200)


@router.get("/fetch-all")
async def fetch_all_data():
    """Fetch all data in the InfluxDB bucket without authentication for testing"""

    query = f"""
    from(bucket: "{BUCKET}")
      |> range(start: -30d)  // Fetch last 30 days of data
    """

    tables = query_api.query(query, org=ORG)

    results = []

    for table in tables:
        for record in table.records:
            results.append(
                {
                    "measurement": record.get_measurement(),
                    "device_id": record.values.get("device_id"),
                    "field": record.values.get("_field"),
                    "value": record.get_value(),
                    "time": record.get_time(),
                }
            )

    return {"data": results}


@router.get("/latest-values")
async def get_latest_values():
    """Get the latest values of voltage, current, and power for each phase (A, B, C) of the device."""
    device_id = "random12"
    query = f'''
    
    from(bucket: "{BUCKET}")
    |> range(start: -1y)  // Consider last 1 hour
    |> filter(fn: (r) => r.device_id == "{device_id}")
    |> filter(fn: (r) => r._measurement == "power_data")
    |> filter(fn: (r) => r._field == "voltage_rms" or r._field == "current_rms" or r._field == "power_watt")
    |> sort(columns: ["_time"], desc: true)  // Sort by time descending to get the latest values first
    |> first()  // Take the latest value per field
    |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")  // Pivot for structured output
    |> keep(columns: ["_time", "phase", "voltage_rms", "current_rms", "power_watt", "voltage_freq"])  // Keep only relevant columns
    '''

    tables = query_api.query(query, org=ORG)
    latest_values = {}

    for table in tables:
        for record in table.records:
            l.dprint("Record: ", record.values)
            phase = record.values.get("phase")
            if not phase:
                continue  # Skip if phase is missing
            latest_values[phase] = {
                "timestamp": record.values.get("_time").isoformat(),
                "voltage": record.values.get("voltage_rms"),
                "current": record.values.get("current_rms"),
                "power": record.values.get("power_watt"),
                "viltage_freq": record.values.get("voltage_freq"),
            }

    if not latest_values:
        return JSONResponse(
            content={"message": "No data found for the device."}, status_code=404
        )

    return JSONResponse(content=latest_values, status_code=200)


@router.get("/thd-values")
async def get_thd_data(range_hours: int = None, date_str: str = None):
    """Get the THD values of all three phases."""
    device_id = "random12"

    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception as e:
            return JSONResponse(
                content={"message": f"Invalid date format: {e}"}, status_code=400
            )

        # Use consistent timezone conversion
        start_dt = datetime.combine(target_date, datetime.min.time()).replace(
            tzinfo=INDIA_TZ
        )
        end_dt = start_dt + timedelta(days=1)

        start_iso = start_dt.astimezone(ZoneInfo("UTC")).isoformat()
        end_iso = end_dt.astimezone(ZoneInfo("UTC")).isoformat()

        range_clause = f"range(start: {start_iso}, stop: {end_iso})"
    elif range_hours is not None:
        range_clause = f"range(start: -{range_hours}h)"
    else:
        range_clause = "range(start: -24h)"

    query = f'''
    from(bucket: "{BUCKET}")
      |> {range_clause}
      |> filter(fn: (r) => r.device_id == "{device_id}")
      |> filter(fn: (r) => r._measurement == "power_data")
      |> group(columns: ["phase"])  // Group by phase
      |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")  // Pivot for structured output
      |> keep(columns: ["_time", "phase", "power_factor", "voltage_thd", "current_thd", "voltage_freq"])  // Keep only relevant fields
    '''

    tables = query_api.query(query, org=ORG)
    latest_values = {}

    for table in tables:
        for record in table.records:
            l.dprint("Record: ", record.values)
            phase = record.values.get("phase")
            if not phase:
                continue  # Skip if phase is missing

            data_point = {
                "timestamp": record.values.get("_time").isoformat(),
                "voltage_thd": record.values.get("voltage_thd"),
                "current_thd": record.values.get("current_thd"),
                "power_factor": record.values.get("power_factor"),
                "voltage_freq": record.values.get("voltage_freq"),
            }
            if phase not in latest_values:
                latest_values[phase] = [data_point]
            else:
                latest_values[phase].append(data_point)

    if not latest_values:
        return JSONResponse(
            content={"message": "No data found for the device."}, status_code=404
        )

    return JSONResponse(content=latest_values, status_code=200)


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    # check the influxdb_client connection
    test_query = f"""
    from(bucket: "{BUCKET}")
      |> range(start: -1m)
    """
    try:
        tables = query_api.query(query=test_query, org=ORG)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to connect to InfluxDB: {str(e)}"
        )

    return JSONResponse(content={"message": "connection OK."}, status_code=200)


@router.get("/last-energy-data")
async def get_last_energy_val():
    """Fetches and sends last `energy_kwh` value"""

    device_id = "random12"  # FIXME: Change all of this later.
    query = f'''
        from(bucket: "{BUCKET}")
        |> range(start: -1y)  // Consider last 1 hour
        |> filter(fn: (r) => r.device_id == "{device_id}")
        |> filter(fn: (r) => r._measurement == "power_data")
        |> filter(fn: (r) => r._field == "energy_kwh")
        |> sort(columns: ["_time"], desc: true)  // Sort by time descending to get the latest values first
        |> first()  // Take the latest value per field
        |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")  // Pivot for structured output
        |> keep(columns: ["_time", "phase", "energy_kwh"])  // Keep only relevant columns
        '''

    tables = query_api.query(query, org=ORG)

    energy_values = {}

    for table in tables:
        for record in table.records:
            l.dprint("Record: ", record.values)
            phase = record.values.get("phase")
            if not phase:
                continue  # Skip if phase is missing
            energy_values[phase] = {
                "timestamp": record.values.get("_time").isoformat(),
                "energy_kwh": record.values.get("energy_kwh"),
            }

    if not energy_values:
        return JSONResponse(
            content={"message": "No data found for the device."}, status_code=404
        )

    return JSONResponse(content=energy_values, status_code=200)
