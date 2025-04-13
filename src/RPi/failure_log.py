# voltage_monitor.py
import time
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
import live_data
import os
import json

DB_PATH = "/home/rpi/Desktop/powermeter_working/power_meter_data.db"
IST = ZoneInfo("Asia/Kolkata")
JSON_PATH = "live_data.json"  # This JSON file will act like our shared data source
FLAG_FILE = "failure_flags.json"  # <-- NEW: Persistent storage for flags

# Track previously detected failures to avoid duplicate entries


def load_flags():
    if os.path.exists(FLAG_FILE):
        try:
            with open(FLAG_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Load Flag Error] {e}")
    return {"R": False, "Y": False, "B": False}


def save_flags(flags):
    try:
        with open(FLAG_FILE, "w") as f:
            json.dump(flags, f)
    except Exception as e:
        print(f"[Save Flag Error] {e}")


failure_logged = load_flags()


def create_table():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS power_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phase TEXT NOT NULL,
                failure_time TEXT NOT NULL
            )
        """)
        conn.commit()


def insert_failure(phase, timestamp):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO power_events (phase, failure_time) VALUES (?, ?)
        """,
            (phase, timestamp),
        )

        # Keep only last 5 entries per phase
        cursor.execute(
            f"""
            DELETE FROM power_events
            WHERE id NOT IN (
                SELECT id FROM power_events
                WHERE phase = ?
                ORDER BY failure_time DESC
                LIMIT 1
            ) AND phase = ?
        """,
            (phase, phase),
        )

        conn.commit()


def read_live_data():
    if not os.path.exists(JSON_PATH):
        return {}, None

    try:
        with open(JSON_PATH, "r") as f:
            data = json.load(f)
        voltage = data.get("voltage", {})
        timestamp = data.get(
            "timestamp", datetime.now(IST).isoformat(timespec="seconds")
        )
        return voltage, timestamp
    except Exception as e:
        print(f"[Read JSON Error] {e}")
        return {}, datetime.now(IST).isoformat(timespec="seconds")


def monitor_voltage():
    create_table()
    print("[Voltage Monitor] Monitoring started...")

    while True:
        try:
            voltage, ts = read_live_data()

            for phase in ["R", "Y", "B"]:
                v = voltage.get(
                    f"VoltageRMSReg_{phase}", 999
                )  # fallback high to avoid false positives
                if v < 10.0 and not failure_logged[phase]:
                    print(
                        f"[ALERT] Voltage LOW on phase {phase}: {v:.2f}V. Logging failure."
                    )
                    insert_failure(phase, ts)
                    failure_logged[phase] = True
                    save_flags(failure_logged)

                elif v >= 10.0 and failure_logged[phase]:
                    # Reset flag if voltage has recovered
                    failure_logged[phase] = False
                    save_flags(failure_logged)

            time.sleep(1)

        except Exception as e:
            print(f"[Voltage Monitor Error] {e}")
            time.sleep(2)


if __name__ == "__main__":
    monitor_voltage()
