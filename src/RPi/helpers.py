"""Helper functions for the powermeter application."""

from __future__ import annotations

import requests

from config import HTTP_TIMEOUT_S, PHASES, SERVER_URL, device_headers


def get_last_energy() -> dict[str, dict]:
    """Latest cumulative energy the *server* holds for this device, per phase.

    Always returns ``{"R": {"energy_kwh": float, "timestamp": str | None}, ...}``.
    The old version returned two different shapes (a float on success, a dict on
    failure), so the success path crashed the sampler; it also used a different host
    than sync.py and had no timeout.
    """
    empty = {p: {"energy_kwh": 0.0, "timestamp": None} for p in PHASES}
    try:
        response = requests.get(f"{SERVER_URL}/api/last-energy-data", headers=device_headers(),
                                timeout=HTTP_TIMEOUT_S)
        if response.status_code != 200:
            return empty
        data = response.json()
        return {
            p: {"energy_kwh": float((data.get(p) or {}).get("energy_kwh") or 0.0),
                "timestamp": (data.get(p) or {}).get("timestamp")}
            for p in PHASES
        }
    except (requests.RequestException, ValueError) as e:
        print(f"[ERROR]: Error fetching last energy from server: {e}")
        return empty


# Old name, kept so external scripts keep working.
get_max_energy = get_last_energy
