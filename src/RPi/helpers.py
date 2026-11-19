"""Helper functions for the powermeter application."""

from __future__ import annotations

import requests

from config import HTTP_TIMEOUT_S, PHASES, SERVER_URL, device_headers


def get_last_energy() -> dict[str, dict] | None:
    """Latest cumulative energy the *server* holds for this device, per phase.

    Returns ``{"R": {"energy_kwh": float, "timestamp": str | None}, ...}``, or ``None``
    if the server couldn't be asked (offline, error). "No data yet" is a valid answer
    (zeros with no timestamp); "couldn't ask" is not, so callers can retry instead of
    silently restarting the energy counter at 0.
    """
    try:
        response = requests.get(f"{SERVER_URL}/api/last-energy-data", headers=device_headers(),
                                timeout=HTTP_TIMEOUT_S)
        if response.status_code != 200:
            print(f"[ERROR]: Server returned HTTP {response.status_code} for last energy")
            return None
        data = response.json()
        return {
            p: {**{c: float((data.get(p) or {}).get(c) or 0.0) for c in ("energy_kwh", "energy_sw_kwh", "export_kwh")},
                "timestamp": (data.get(p) or {}).get("timestamp")}
            for p in PHASES
        }
    except (requests.RequestException, ValueError) as e:
        print(f"[ERROR]: Error fetching last energy from server: {e}")
        return None


# Old name, kept so external scripts keep working.
get_max_energy = get_last_energy
