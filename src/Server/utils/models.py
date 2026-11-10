"""Request/response models. Validation here is what keeps bad data out of storage."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator

PHASES = ("R", "Y", "B")
Phase = Literal["R", "Y", "B", "Neutral"]
READING_FIELDS = ("voltage_rms", "current_rms", "power_watt", "power_var", "power_va", "power_factor",
                  "voltage_thd", "current_thd", "energy_kwh", "voltage_freq")


class Reading(BaseModel):
    """One phase of one sample, as the device sends it.

    ``time`` must carry a timezone. The old server parsed it with a format that never
    matched what the device sent and silently substituted ``now()``, which collapsed
    every sync batch onto one timestamp (InfluxDB then kept one point per phase).
    Now a bad timestamp is rejected with 422.
    """

    phase: Phase
    time: AwareDatetime
    voltage_rms: float = 0.0
    current_rms: float = 0.0
    power_watt: float = 0.0
    power_var: float = 0.0
    power_va: float = 0.0
    power_factor: float = 0.0
    voltage_thd: float = 0.0
    current_thd: float = 0.0
    energy_kwh: float = 0.0
    voltage_freq: float = 0.0

    @field_validator(*READING_FIELDS)
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("must be a finite number")
        return v

    @field_validator("time")
    @classmethod
    def _plausible_time(cls, v: datetime) -> datetime:
        now = datetime.now(timezone.utc)
        if v > now + timedelta(minutes=10):
            raise ValueError("timestamp is in the future (device clock wrong?)")
        if v < now - timedelta(days=400):
            raise ValueError("timestamp is too old")
        return v.astimezone(timezone.utc)


class SignUpRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    claim_code: str = Field(..., max_length=1024)


class LoginRequest(BaseModel):
    username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=128)


class ClaimRequest(BaseModel):
    claim_code: str = Field(..., max_length=1024)


class RelayCommand(BaseModel):
    device_id: str | None = None
    phase: Literal["R", "Y", "B", "ALL"]
    command: Literal["on", "off"]
