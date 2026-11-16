"""Server settings, read from the environment and ``src/Server/.env``.

Local development needs only SECRET_KEY (``python manage.py init-env`` creates it).
Everything else has a local-first default: SQLite storage under ``src/Server/data``.
For the cloud, set STORAGE_BACKEND=influx plus the INFLUXDB_* variables.

The old version used ``os.getenv`` defaults, so a missing variable became ``None`` and
crashed later at first use (e.g. ``settings.signup_sec_key.encode()``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parent
REPO_ROOT = SERVER_DIR.parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=SERVER_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    secret_key: str = ""  # JWT signing key (>= 32 chars)

    storage_backend: Literal["sqlite", "influx"] = "sqlite"
    data_dir: Path = SERVER_DIR / "data"
    timeseries_db: Path | None = None  # sqlite backend; default data_dir/timeseries.db
    metadata_db: Path | None = None  # users, devices, audit log; default data_dir/voltix.db

    influxdb_url: str | None = None
    influxdb_token: str | None = None
    influxdb_org: str | None = None
    influxdb_bucket: str | None = None

    access_token_expire_minutes: int = 60  # was 3600 *minutes* (60 h)
    password_hash_iterations: int = 600_000  # PBKDF2-HMAC-SHA256
    claim_ttl_seconds: int = 600  # how long a device sign-up QR code stays valid
    command_timeout_seconds: float = 5.0  # wait for the device to acknowledge a relay command
    device_online_timeout_seconds: float = 90.0
    max_batch_size: int = 2000

    # Rollups and retention (SQLite backend; for InfluxDB see deploy/influx_downsampling.flux)
    raw_retention_days: float = 30  # 1 Hz readings; older raw data is deleted once rolled up
    hourly_retention_days: float = 400  # hourly rollups; daily rollups are kept forever
    maintenance_interval_seconds: float = 60  # how often dirty hours are re-rolled

    # Live lane: newest reading pushed by the device every second (not persisted here;
    # the batched sync remains the durable path)
    live_min_interval_seconds: float = 0.5  # drop pushes faster than this per device

    # Auth hardening
    trust_proxy_headers: bool = False  # only behind a reverse proxy that sets X-Forwarded-For
    reset_token_ttl_minutes: int = 15
    public_app_url: str = "http://127.0.0.1:8000/app/"  # used in password-reset emails
    smtp_host: str | None = None  # unset = write emails to data_dir/outbox (local dev)
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    mail_from: str = "Voltix <no-reply@voltix.local>"

    cors_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]
    timezone: str = "Asia/Kolkata"
    webapp_dir: Path = REPO_ROOT / "src" / "WebApp"

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        if len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY must be set to at least 32 characters. "
                             "Run `python manage.py init-env` in src/Server.")
        if self.storage_backend == "influx":
            missing = [n for n in ("influxdb_url", "influxdb_token", "influxdb_org", "influxdb_bucket")
                       if not getattr(self, n)]
            if missing:
                raise ValueError(f"STORAGE_BACKEND=influx needs: {', '.join(m.upper() for m in missing)}")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.timeseries_db = self.timeseries_db or self.data_dir / "timeseries.db"
        self.metadata_db = self.metadata_db or self.data_dir / "voltix.db"
        return self


settings = Settings()
