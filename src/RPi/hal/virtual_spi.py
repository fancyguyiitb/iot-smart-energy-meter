"""A drop-in for ``spidev.SpiDev`` that carries SPI frames to the virtual meter board."""

from __future__ import annotations

import requests

from config import SIM_URL


class SpiDev:
    def __init__(self) -> None:
        self.max_speed_hz = 0
        self.mode = 0
        self._session = requests.Session()
        self._url: str | None = None

    def open(self, bus: int, device: int) -> None:
        self._url = f"{SIM_URL}/spi/{bus}/{device}"
        try:
            self._session.get(f"{SIM_URL}/health", timeout=3).raise_for_status()
        except requests.RequestException as exc:
            raise OSError(f"Virtual meter board not reachable at {SIM_URL} ({exc}). "
                          "Start it with: python scripts/run_local.py") from exc

    def xfer2(self, tx: list[int]) -> list[int]:
        if self._url is None:
            raise OSError("SPI device not opened")
        response = self._session.post(self._url, json={"tx": [int(b) & 0xFF for b in tx]}, timeout=2)
        response.raise_for_status()
        return response.json()["rx"]

    xfer = xfer2

    def close(self) -> None:
        self._session.close()
        self._url = None
