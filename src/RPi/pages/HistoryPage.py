import tkinter as tk
from tkinter import ttk
import sqlite3
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime, timedelta, date
import matplotlib.dates as mdates
from zoneinfo import ZoneInfo
import numpy as np  # ensure this is imported at the top if not already
from calendar import monthrange
import threading

DB_NAME = "power_meter_data.db"
BTN_BG = "lightgray"
BTN_SELECTED = "white"
IST = ZoneInfo("Asia/Kolkata")


class HistoryPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)

        style = ttk.Style()
        style.configure(
            "CustomCombobox.TCombobox", font=("Arial", 40)
        )  # font increases height, padding helps too
        self.option_add("*TCombobox*Listbox.font", ("Arial", 18))  # dropdown font

        self.controller = controller
        self.phase_view = "R"

        self.month_var = tk.StringVar()
        self.year_var = tk.StringVar()

        self.main_panel = tk.Frame(self)
        self.main_panel.pack(fill="both", expand=True)

        self.fig, self.ax = plt.subplots(figsize=(8, 4))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.main_panel)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Month/year selection dropdowns
        month_names = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]
        current_year = datetime.now().year

        months = list(range(1, 13))
        years = list(range(current_year - 5, current_year + 1))

        tk.Label(
            self.main_panel, text="Month:", font=("Arial", 20), fg="white", bg="#1e1e1e"
        ).place(relx=0.02, rely=0.015)
        month_menu = ttk.Combobox(
            self.main_panel,
            textvariable=self.month_var,
            values=month_names,
            state="readonly",
            style="CustomCombobox.TCombobox",
            width=9,  # wider box
        )

        month_menu.place(relx=0.07, rely=0.01)
        month_menu.configure(font=("Arial", 25))  # 👈 Ensures large font

        self.month_var.set(month_names[datetime.now().month - 1])

        tk.Label(
            self.main_panel, text="Year:", font=("Arial", 20), fg="white", bg="#1e1e1e"
        ).place(relx=0.19, rely=0.015)
        year_menu = ttk.Combobox(
            self.main_panel,
            textvariable=self.year_var,
            values=years,
            state="readonly",
            style="CustomCombobox.TCombobox",
            width=9,
        )
        year_menu.place(relx=0.23, rely=0.01)
        year_menu.configure(font=("Arial", 25))  # 👈 Ensures large font

        self.year_var.set(str(current_year))

        load_btn = tk.Button(
            self.main_panel,
            text="Load Data",
            command=self.load_data,
            bg=BTN_BG,
            font=("Arial", 25),
        )
        load_btn.place(relx=0.32, rely=0.076)

        # Phase buttons
        self.phase_buttons = {}
        for i, phase in enumerate(["R", "Y", "B"]):
            btn = tk.Button(
                self.main_panel,
                text=f"Phase {phase}",
                bg=BTN_BG,
                command=lambda ph=phase: self.set_phase(ph),
                font=("Arial", 25),
            )
            btn.place(relx=0.4 + i * 0.09, rely=0.01)
            self.phase_buttons[phase] = btn

        # Internal data
        self.data = {ph: {"timestamps": [], "energy": []} for ph in ["R", "Y", "B"]}

        self.set_phase("R")

    def set_phase(self, phase):
        self.phase_view = phase
        for p, btn in self.phase_buttons.items():
            btn.config(bg=BTN_SELECTED if p == phase else BTN_BG)
        self.refresh_plot()

    def load_data(self):
        try:
            month_names = [
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ]
            month_idx = month_names.index(self.month_var.get()) + 1
            year = int(self.year_var.get())

            # Start and end of selected month
            start_date = datetime(year, month_idx, 1, tzinfo=IST)
            last_day = monthrange(year, month_idx)[1]
            end_date = datetime(year, month_idx, last_day, 23, 59, 59, tzinfo=IST)

            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT phase, energy_kwh, timestamp FROM power_data
                    WHERE timestamp BETWEEN ? AND ?
                    ORDER BY timestamp ASC
                """,
                    (start_date.isoformat(), end_date.isoformat()),
                )
                rows = cursor.fetchall()

            # Initialize daily_energy dict with 0 for all days for each phase
            self.data = {ph: {"timestamps": [], "energy": []} for ph in ["R", "Y", "B"]}
            daily_energy = {ph: {} for ph in ["R", "Y", "B"]}

            for day in range(1, last_day + 1):
                dt = datetime(year, month_idx, day, tzinfo=IST).date()
                for ph in ["R", "Y", "B"]:
                    daily_energy[ph][dt] = {"start": None, "end": None}

            for phase, energy, timestamp_str in rows:
                if phase not in daily_energy:
                    continue
                dt = datetime.fromisoformat(timestamp_str).astimezone(IST)
                day_key = dt.date()
                if day_key not in daily_energy[phase]:
                    continue
                if daily_energy[phase][day_key]["start"] is None:
                    daily_energy[phase][day_key]["start"] = energy
                    daily_energy[phase][day_key]["end"] = energy
                else:
                    daily_energy[phase][day_key]["end"] = energy

            for phase in ["R", "Y", "B"]:
                for d in sorted(daily_energy[phase]):
                    readings = daily_energy[phase][d]
                    if readings["start"] is None:
                        net_energy = 0
                    else:
                        net_energy = max(readings["end"] - readings["start"], 0)
                    self.data[phase]["timestamps"].append(
                        datetime.combine(d, datetime.min.time(), tzinfo=IST)
                    )
                    self.data[phase]["energy"].append(net_energy)

            self.refresh_plot()

        except Exception as e:
            print(f"[HistoryPage Error] {e}")

    def refresh_plot(self):
        self.ax.clear()
        label = "Energy (kWh)"
        self.ax.set_ylabel(label, fontsize=20)

        self.ax.yaxis.grid(True, linestyle="--", linewidth=0.8)
        self.ax.xaxis.grid(False)
        self.ax.yaxis.get_offset_text().set_fontsize(20)
        self.ax.yaxis.get_offset_text().set_fontweight("bold")
        self.ax.yaxis.get_offset_text().set_x(-0.08)

        timestamps = self.data[self.phase_view]["timestamps"]
        values = self.data[self.phase_view]["energy"]

        if timestamps and values:
            self.ax.bar(timestamps, values, label="Energy", color="red", width=0.8)

            # Fix x-axis till the end of selected month
            year = int(self.year_var.get())
            month_idx = [
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ].index(self.month_var.get()) + 1
            last_day = monthrange(year, month_idx)[1]
            end_of_month = datetime(year, month_idx, last_day, tzinfo=IST)

            self.ax.set_xlim(
                timestamps[0] - timedelta(days=0.5), end_of_month + timedelta(days=0.5)
            )
            self.ax.set_ylim(0, max(values) * 1.2 if max(values) > 0 else 1)

            # Show only selected x-axis ticks: 1, 5, 10, 15, 20, 25, and last day
            special_days = [1, 5, 10, 15, 20, 25, last_day]
            tick_dates = [
                datetime(year, month_idx, d, tzinfo=IST) for d in special_days
            ]
            self.ax.set_xticks(tick_dates)
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b", tz=IST))
            self.ax.tick_params(axis="x", labelsize=18)
            self.ax.tick_params(axis="y", labelsize=18)
            self.ax.legend(fontsize=18)

        self.fig.subplots_adjust(left=0.05, right=0.65, top=0.87, bottom=0.45)
        self.canvas.draw()
