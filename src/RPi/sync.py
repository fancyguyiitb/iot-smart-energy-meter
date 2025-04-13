"""Module that contains the sync function to synchronize the local database with the server"""

import requests
import time

from db import init_db, insert_power_data, update_row_sync_status, get_unsynced_data
from sprint import Logger

BASE_URL = "https://edlserver-production-b9fa.up.railway.app/api/write-data"
# BASE_URL = "http://localhost:8000/api/write-data/"

l = Logger.get_instance(debug=True)


def send_data_to_server(data, token=None):
    """Send data to the server"""
    data = data
    headers = {"Content-Type": "Application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.post(BASE_URL, json=data, headers=headers)
        if response.status_code == 201:
            l.iprint("Data sent to server successfully.")
            return True
        l.eprint("Some problem occurred...")
        l.eprint(response.text)

    except requests.exceptions.RequestException as e:
        l.eprint(f"Error sending data to server: {e}")
        return False


def proc():
    init_db()
    l.iprint("Database initialized.")

    data = get_unsynced_data()
    row_ids = [i.pop("id") for i in data]
    if not data:
        l.iprint("No unsynced data found.")
        l.iprint("Will retry in 5 seconds.")

    else:
        l.iprint(f"{len(data)} unsynced data found.")
        if send_data_to_server(data=data, token=None):
            l.iprint("Updating the local_db...")
            update_row_sync_status(row_ids)
        else:
            l.eprint("Failed to send data to server.")
            l.dprint("Will retry in 5 seconds.")


if __name__ == "__main__":
    while True:
        proc()
        time.sleep(10)
