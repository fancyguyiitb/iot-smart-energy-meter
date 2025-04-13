"""Helper functions for the powermeter application."""

import requests


BASE_URL = "https://edlserver-production.up.railway.app/api/"


def get_max_energy():
    try:
        response = requests.get(f"{BASE_URL}last-energy-data")
        if response.status_code != 200:
            return {
                "R": {"energy_kwh": 0},
                "Y": {"energy_kwh": 0},
                "B": {"energy_kwh": 0},
            }
        else:
            phase_data = response.json()
            data = {
                "R": phase_data["R"]["energy_kwh"],
                "Y": phase_data["Y"]["energy_kwh"],
                "B": phase_data["B"]["energy_kwh"],
            }
        return data
    except Exception as e:
        print(f"[ERROR]: Error fetching data from server: {e}")

        return {"R": {"energy_kwh": 0}, "Y": {"energy_kwh": 0}, "B": {"energy_kwh": 0}}
