"""Server admin CLI.

  python manage.py init-env
      Create src/Server/.env with a random SECRET_KEY (no-op if it exists).

  python manage.py provision-device --device-id meter-001 --env-out ../RPi/device.env
      Register a meter: generates its device key (only the hash is stored here) and its
      claim key, and writes the device's env file. Use --rotate to issue new secrets.

  python manage.py list-devices
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

SERVER_DIR = Path(__file__).resolve().parent
ENV_PATH = SERVER_DIR / ".env"
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")


def init_env() -> None:
    if ENV_PATH.exists() and "SECRET_KEY=" in ENV_PATH.read_text():
        print(f"{ENV_PATH} already exists")
        return
    ENV_PATH.write_text(
        "# Local development settings (never commit this file)\n"
        f"SECRET_KEY={secrets.token_urlsafe(48)}\n"
        "STORAGE_BACKEND=sqlite\n"
        "# STORAGE_BACKEND=influx\n# INFLUXDB_URL=\n# INFLUXDB_TOKEN=\n# INFLUXDB_ORG=\n# INFLUXDB_BUCKET=\n"
    )
    print(f"Wrote {ENV_PATH}")


def _read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))
    return {k.strip(): v.strip() for k, v in pairs}


def provision_device(device_id: str, env_out: Path | None, server_url: str, hal: str, rotate: bool,
                     name: str | None = None) -> None:
    if not DEVICE_ID_RE.match(device_id):
        sys.exit("device id must be 3-64 characters of letters, digits, '-' or '_'")
    from utils.database import get_metadata_db
    from utils.security import hash_device_key, new_device_key

    db = get_metadata_db()
    existing = db.get_device(device_id)
    current_env = _read_env(env_out) if env_out else {}
    if existing and not rotate:
        if current_env.get("DEVICE_ID") == device_id and current_env.get("DEVICE_KEY"):
            print(f"Device {device_id} already provisioned ({env_out})")
            return
        sys.exit(f"Device {device_id} exists but its key is unknown here; re-run with --rotate")

    device_key = new_device_key()
    claim_key = Fernet.generate_key().decode()
    db.upsert_device(device_id, hash_device_key(device_key), claim_key, name)
    lines = [
        "# Device identity - keep secret, never commit (see src/RPi/config.py)",
        f"DEVICE_ID={device_id}",
        f"DEVICE_KEY={device_key}",
        f"CLAIM_KEY={claim_key}",
        f"SERVER_URL={server_url}",
        "# virtual = talk to src/VirtualDevice; hardware = real SPI/GPIO on the Pi",
        f"VOLTIX_HAL={hal}",
    ]
    if env_out:
        env_out.parent.mkdir(parents=True, exist_ok=True)
        env_out.write_text("\n".join(lines) + "\n")
        print(f"Provisioned {device_id}; wrote {env_out}")
    else:
        print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-env")
    p = sub.add_parser("provision-device")
    p.add_argument("--device-id", required=True)
    p.add_argument("--name")
    p.add_argument("--env-out", type=Path)
    p.add_argument("--server-url", default="http://127.0.0.1:8000")
    p.add_argument("--hal", choices=["virtual", "hardware"], default="virtual")
    p.add_argument("--rotate", action="store_true")
    sub.add_parser("list-devices")
    args = parser.parse_args()

    if args.cmd == "init-env":
        init_env()
        return
    sys.path.insert(0, str(SERVER_DIR))
    if args.cmd == "provision-device":
        provision_device(args.device_id, args.env_out, args.server_url, args.hal, args.rotate, args.name)
    elif args.cmd == "list-devices":
        from utils.database import get_metadata_db

        for d in get_metadata_db().list_devices():
            print(d)


if __name__ == "__main__":
    main()
