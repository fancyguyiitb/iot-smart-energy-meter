from datetime import datetime
from zoneinfo import ZoneInfo  # For Python 3.9+
from fastapi import APIRouter, HTTPException, Query
from analytics.helpers import (
    generate_power_analytics,
    fetch_stored_power_analytics,
    generate_energy_analytics,
    fetch_stored_energy_analytics,
    fetch_energy_data,
    fetch_power_data,
)
from utils.sprint import Logger

l = Logger.get_instance(True)

analysis_router = APIRouter()

# Default device and phase values
DEFAULT_DEVICE_ID = "random12"
DEFAULT_PHASE = "R"

# Define the target timezone
INDIA_TZ = ZoneInfo("Asia/Kolkata")


@analysis_router.get("/power")
async def get_power_analytics(
    date_str: str = Query(..., description="Date in YYYY-MM-DD format"),
    phase: str = Query(DEFAULT_PHASE, description="Phase identifier"),
    device_id: str = Query(DEFAULT_DEVICE_ID, description="Device ID"),
):
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
        )

    # Get the current date in Asia/Kolkata timezone
    current_date = datetime.now(INDIA_TZ).date()

    l.dprint(f"Current date: {current_date}, target date: {target_date}")

    if target_date == current_date:
        l.dprint("Analytics data accessed for today")
        analytics_data = generate_power_analytics(target_date, phase, device_id)
    else:
        analytics_data = fetch_stored_power_analytics(target_date, phase, device_id)

    power_data = fetch_power_data(target_date, phase, device_id)

    data = {
        "analytics_data": analytics_data,
        "power_data": power_data,
    }

    if not power_data:
        raise HTTPException(
            status_code=404, detail="No power data found for this date."
        )
    return data


@analysis_router.get("/energy")
async def get_energy_analytics(
    date_str: str = Query(..., description="Date in YYYY-MM-DD format"),
    phase: str = Query(DEFAULT_PHASE, description="Phase identifier"),
    device_id: str = Query(DEFAULT_DEVICE_ID, description="Device ID"),
):
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
        )

    # Get the current date in Asia/Kolkata timezone
    current_date = datetime.now(INDIA_TZ).date()

    if target_date == current_date:
        analytics_data = generate_energy_analytics(target_date, phase, device_id)
    else:
        analytics_data = fetch_stored_energy_analytics(target_date, phase, device_id)

    energy_data = fetch_energy_data(target_date, phase, device_id)

    data = {
        "analytics_data": analytics_data,
        "energy_data": energy_data,
    }
    return data
