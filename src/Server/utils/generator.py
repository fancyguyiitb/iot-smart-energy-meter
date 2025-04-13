"""Module that generates the data for db"""

import csv
import random
from datetime import datetime, timedelta

CSV_FILENAME = "sensor_data.csv"

NUM_POINTS = 500  # Generates 500 random data points over the last 24 hours

time_now = datetime.utcnow()
time_start = time_now - timedelta(hours=24)

with open(CSV_FILENAME, mode="w", newline="") as file:
    writer = csv.writer(file)

    # Write CSV header
    writer.writerow(["time", "device_id", "I", "V", "P"])

    # Generate random data points
    for _ in range(NUM_POINTS):
        timestamp = time_start + timedelta(
            seconds=random.randint(0, 86400)
        )  # Random time in last 24hrs
        I = round(random.uniform(0.1, 10.0), 2)  # Random float for Current (I)
        V = round(random.uniform(110.0, 250.0), 2)  # Random float for Voltage (V)
        P = round(I * V, 2)  # Power (P = I * V)

        # Write to CSV
        writer.writerow([timestamp.isoformat(), "random12", I, V, P])

print(f"Data written to {CSV_FILENAME}")
