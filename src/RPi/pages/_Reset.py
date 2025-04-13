import tkinter as tk
import sqlite3
import shared_flags  # 👈 import the shared module
import os
import time

DB_NAME = "power_meter_data.db"

class ResetPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        self.reset_button = tk.Button(
            self,
            text="Reset Energy",
            font=("Arial", 35),
            bg="red",
            fg="white",
            command=self.reset_database
        )
        self.reset_button.pack(expand=True)

    def reset_database(self):
        try:
            if os.path.exists(DB_NAME):
                os.remove(DB_NAME)
                print("Database file deleted.")
            
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS power_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phase TEXT,
                    voltage_rms REAL,
                    current_rms REAL,
                    active_power REAL,
                    reactive_power REAL,
                    apparent_power REAL,
                    energy_kwh REAL,
                    voltage_thd REAL,
                    current_thd REAL,
                    power_factor REAL,
                    voltage_freq REAL,
                    timestamp TEXT,
                    sync BOOLEAN DEFAULT 0
                )
            """)
            conn.commit()
            conn.close()
            shared_flags.reset_flag = True  # ✅ set the flag
            time.sleep(2)
            shared_flags.reset_flag = False
            print("Database reset successful. Flag set to True.")
        except Exception as e:
            print("Database error:", e)
