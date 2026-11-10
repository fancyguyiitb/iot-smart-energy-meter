"""The subset of the ``RPi.GPIO`` API the firmware uses, backed by the virtual board."""

from __future__ import annotations

import requests

from config import SIM_URL

BCM = 11
BOARD = 10
OUT = 0
IN = 1
HIGH = 1
LOW = 0

_session = requests.Session()


def setmode(mode: int) -> None:
    if mode != BCM:
        raise ValueError("The virtual board only supports BCM numbering")


def setwarnings(flag: bool) -> None:  # noqa: ARG001 - API compatibility
    pass


def setup(channel: int, direction: int, initial: int | None = None, **_kwargs) -> None:
    body = {"pin": int(channel), "mode": "out" if direction == OUT else "in"}
    if initial is not None:
        body["initial"] = int(bool(initial))
    _session.post(f"{SIM_URL}/gpio/setup", json=body, timeout=3).raise_for_status()


def output(channel: int, value: int) -> None:
    _session.post(f"{SIM_URL}/gpio/write", json={"pin": int(channel), "level": int(bool(value))},
                  timeout=3).raise_for_status()


def input(channel: int) -> int:  # noqa: A001 - mirrors RPi.GPIO.input
    response = _session.get(f"{SIM_URL}/gpio/{int(channel)}", timeout=3)
    response.raise_for_status()
    return int(response.json()["level"])


def cleanup(*_args) -> None:
    try:
        _session.post(f"{SIM_URL}/gpio/cleanup", timeout=3)
    except requests.RequestException:
        pass
