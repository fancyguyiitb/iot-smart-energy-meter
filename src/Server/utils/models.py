"""Request/response models. Validation here is what keeps bad data out of storage."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator

PHASES = ("R", "Y", "B")
Phase = Literal["R", "Y", "B", "Neutral"]
READING_FIELDS = ("voltage_rms", "current_rms", "power_watt", "power_var", "power_va", "power_factor",
                  "voltage_thd", "current_thd", "energy_kwh", "voltage_freq", "energy_sw_kwh", "export_kwh")
# Cumulative counters (summed as consumption in rollups, never averaged):
#   energy_kwh    import energy from the metering chip's accumulators (billing)
#   energy_sw_kwh import energy integrated in software on the meter (cross-check)
#   export_kwh    export energy from the chip's accumulators
COUNTER_FIELDS = ("energy_kwh", "energy_sw_kwh", "export_kwh")


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
    energy_sw_kwh: float = 0.0
    export_kwh: float = 0.0

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


class PowerEvent(BaseModel):
    """A supply interruption on one phase. ``end`` is None while the outage is ongoing."""

    phase: Literal["R", "Y", "B"]
    start: AwareDatetime
    end: AwareDatetime | None = None

    @field_validator("start", "end")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return v.astimezone(timezone.utc) if v else v


EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$"


class SignUpRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    claim_code: str = Field(..., max_length=1024)
    email: str | None = Field(None, max_length=254, pattern=EMAIL_PATTERN)  # needed for password reset


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=254, description="Username or email")


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class EmailUpdateRequest(BaseModel):
    current_password: str = Field(..., max_length=128)
    email: str | None = Field(None, max_length=254, pattern=EMAIL_PATTERN)


class LoginRequest(BaseModel):
    username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=128)


class ClaimRequest(BaseModel):
    claim_code: str = Field(..., max_length=1024)


class RelayCommand(BaseModel):
    device_id: str | None = None
    phase: Literal["R", "Y", "B", "ALL"]
    command: Literal["on", "off"]
