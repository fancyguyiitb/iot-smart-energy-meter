"""Single source of device configuration for every firmware process.

Values come from the environment, optionally loaded from ``device.env`` next to this
file (created by ``python src/Server/manage.py provision-device``). Nothing about the
server URL, device identity, file paths or pins is hard-coded anywhere else.
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional on the real Pi
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = Path(os.getenv("VOLTIX_DEVICE_ENV", BASE_DIR / "device.env"))
if load_dotenv and ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=False)


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


# Hardware abstraction: "hardware" = real SPI + GPIO on the Pi, "virtual" = src/VirtualDevice.
HAL = os.getenv("VOLTIX_HAL", "virtual").strip().lower()
SIM_URL = os.getenv("SIM_URL", "http://127.0.0.1:9000").rstrip("/")

# Identity, provisioned per device. The key authenticates the device to the server; the
# claim key signs the short-lived sign-up QR code.
DEVICE_ID = os.getenv("DEVICE_ID", "")
DEVICE_KEY = os.getenv("DEVICE_KEY", "")
CLAIM_KEY = os.getenv("CLAIM_KEY", "")

SERVER_URL = os.getenv("SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
WS_URL = os.getenv("WS_URL") or (
    SERVER_URL.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws"
)
HTTP_TIMEOUT_S = float(os.getenv("HTTP_TIMEOUT_S", "5"))

# Files. Everything lives under DATA_DIR so the processes agree regardless of their CWD.
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(Path(os.getenv("DB_PATH", DATA_DIR / "power_meter_data.db")))
LIVE_DATA_PATH = DATA_DIR / "live_data.json"
RELAY_STATE_PATH = DATA_DIR / "relay_state.json"
FAILURE_FLAGS_PATH = DATA_DIR / "failure_flags.json"

TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Kolkata"))

PHASES = ("R", "Y", "B")
PHASE_TO_CHIP = {"R": "A", "Y": "B", "B": "C"}  # board wiring of the ADE9000 channels

SAMPLE_INTERVAL_S = float(os.getenv("SAMPLE_INTERVAL_S", "1.0"))
SYNC_INTERVAL_S = float(os.getenv("SYNC_INTERVAL_S", "10"))
SYNC_BATCH_SIZE = int(os.getenv("SYNC_BATCH_SIZE", "500"))
RETENTION_DAYS = float(os.getenv("RETENTION_DAYS", "3"))  # synced rows older than this are pruned

# Relays: one GPIO per phase (BCM numbering). HIGH closes the relay unless ACTIVE_HIGH=false.
RELAY_PINS = {
    phase.strip().upper(): int(pin)
    for phase, pin in (item.split(":") for item in os.getenv("RELAY_PINS", "R:17,Y:27,B:22").split(","))
}
RELAY_ACTIVE_HIGH = _bool("RELAY_ACTIVE_HIGH", "true")

FAILURE_VOLTAGE_V = float(os.getenv("FAILURE_VOLTAGE_V", "10"))
LIVE_DATA_MAX_AGE_S = float(os.getenv("LIVE_DATA_MAX_AGE_S", "5"))
CLAIM_CODE_REFRESH_S = int(os.getenv("CLAIM_CODE_REFRESH_S", "300"))

GUI_GEOMETRY = os.getenv("GUI_GEOMETRY", "2000x1010")
GUI_FULLSCREEN = _bool("GUI_FULLSCREEN", "false")


def device_headers() -> dict[str, str]:
    """Headers that authenticate this device to the server."""
    return {"X-Device-Id": DEVICE_ID, "X-Device-Key": DEVICE_KEY}


def require_identity() -> None:
    if not (DEVICE_ID and DEVICE_KEY):
        raise SystemExit(
            "DEVICE_ID / DEVICE_KEY are not set. Provision the device first:\n"
            "  python src/Server/manage.py provision-device --device-id meter-001 "
            "--env-out src/RPi/device.env"
        )
