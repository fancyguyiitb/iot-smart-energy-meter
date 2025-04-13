import tkinter as tk
import sqlite3
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime, timedelta, date, timezone
import matplotlib.dates as mdates
from matplotlib.ticker import ScalarFormatter
from zoneinfo import ZoneInfo
from matplotlib.ticker import FuncFormatter
from matplotlib.ticker import ScalarFormatter
import numpy as np

DB_NAME = "power_meter_data.db"
BTN_BG = "lightgray"
BTN_SELECTED = "white"
IST = ZoneInfo("Asia/Kolkata")


class EnergyPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.phase_view = "R"
        self.value_types = ["Energy_A"]

        self.value_buttons = {}
        self.phase_buttons = {}

        self.main_panel = tk.Frame(self)
        self.main_panel.pack(fill="both", expand=True)

        self.fig, self.ax = plt.subplots(figsize=(8, 4))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.main_panel)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        btn_font = ("Arial", 30)

        # --- Value Type Buttons ---
        value_types = {"Energy": ["Energy_E"]}
        # for i, (label, values) in enumerate(value_types.items()):
        #     btn = tk.Button(self.main_panel, text=label, font=btn_font,
        #                     command=lambda v=values, l=label: self.set_value_type(v, l),
        #                     bg=BTN_BG)
        #     btn.place(relx=0.01 + 0.15 * i, rely=0.01)
        #     self.value_buttons[label] = btn

        # --- Phase Buttons ---
        for i, phase in enumerate(["R", "Y", "B"]):
            btn = tk.Button(
                self.main_panel,
                text=f"Phase {phase}",
                font=btn_font,
                command=lambda ph=phase: self.set_phase(ph),
                bg=BTN_BG,
            )
            btn.place(relx=0.355 + 0.1 * i, rely=0.01)
            self.phase_buttons[phase] = btn

        # --- Data Storage ---
        self.data = {
            "R": {"timestamps": [], "Energy_E": []},
            "Y": {"timestamps": [], "Energy_E": []},
            "B": {"timestamps": [], "Energy_E": []},
        }

        self.last_logged_id = 0
        self.update_loop_running = False

        self.set_value_type(["Energy_E"], "Energy")
        self.set_phase("R")

    def set_value_type(self, vtypes, label=None):
        self.value_types = vtypes
        print(f"[EnergyPage] Showing: {', '.join(vtypes)} for Phase {self.phase_view}")
        for name, btn in self.value_buttons.items():
            btn.config(bg=BTN_SELECTED if name == label else BTN_BG)
        self.refresh_plot()

    def set_phase(self, phase):
        self.phase_view = phase

        for p, btn in self.phase_buttons.items():
            btn.config(bg=BTN_SELECTED if p == phase else BTN_BG)

        # Show the loading window
        loading_win = tk.Toplevel(self)
        loading_win.title("Loading")
        loading_win.geometry("2000x1010")
        loading_label = tk.Label(loading_win, text="LOADING...", font=("Segoe UI", 45))
        loading_label.pack(expand=True)

        loading_win.transient(self)
        loading_win.grab_set()

        def load_and_close():
            self.refresh_plot()
            loading_win.destroy()

        self.after(100, load_and_close)

    def on_show(self):
        print("[EnergyPage] Active")
        self.update_loop_running = True
        self.after(100, self.update_data)

    def on_hide(self):
        print("[EnergyPage] Hidden")
        self.update_loop_running = False

    def update_data(self):
        if not self.update_loop_running:
            return

        try:
            day_start = datetime.combine(date.today(), datetime.min.time()).replace(
                tzinfo=IST
            )
            day_end = day_start + timedelta(days=1)
            prev_day_start = day_start - timedelta(days=1)
            prev_day_end = (
                day_start  # previous day ends exactly when current day starts
            )

            # Dictionary to store the last value of previous day per phase
            prev_day_last = {}

            # For each phase, query the last entry of the previous day
            phases = ["R", "Y", "B"]
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                for phase in phases:
                    cursor.execute(
                        """
                        SELECT energy_kwh, timestamp
                        FROM power_data
                        WHERE phase = ? AND timestamp BETWEEN ? AND ?
                        ORDER BY timestamp DESC
                        LIMIT 1
                    """,
                        (phase, prev_day_start.isoformat(), prev_day_end.isoformat()),
                    )
                    result = cursor.fetchone()
                    if result:
                        prev_energy, ts = result
                        prev_day_last[phase] = prev_energy
                    else:
                        prev_day_last[phase] = (
                            0  # use zero if no previous day entry is found
                        )

            # Prepare a fresh data storage structure
            # Here we assume self.data is a dictionary that has a key for each phase,
            # with a dictionary containing lists for timestamps and energy readings.
            self.data = {phase: {"timestamps": [], "Energy_E": []} for phase in phases}

            # Now load current day data only
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, phase, energy_kwh, timestamp
                    FROM power_data
                    WHERE timestamp >= ? AND timestamp < ?
                    ORDER BY id ASC
                """,
                    (day_start.isoformat(), day_end.isoformat()),
                )
                rows = cursor.fetchall()

            # Process the current day entries
            prev_timestamp_per_phase = {phase: None for phase in phases}

            for row in rows:
                row_id, phase, energy, timestamp_str = row
                # Skip if phase is not one of the expected ones
                if phase not in self.data:
                    continue

                # Convert the timestamp from ISO format; assumes stored timestamps include timezone info
                dt = datetime.fromisoformat(timestamp_str)
                # Only use records for the current day (they should already be filtered, but we double-check)
                if day_start <= dt < day_end:
                    # Get the previous day last entry for this phase
                    prev_value = prev_day_last.get(phase, 0)
                    # Subtract the previous day's energy reading from the current record
                    adjusted_energy = energy - prev_value
                    # If subtraction produces a negative result then use zero instead
                    if adjusted_energy < 0:
                        adjusted_energy = 0

                    prev_ts = prev_timestamp_per_phase[phase]
                    if prev_ts is not None and (dt - prev_ts).total_seconds() > 3:
                        # Add None to break the line
                        self.data[phase]["timestamps"].append(dt)
                        self.data[phase]["Energy_E"].append(np.nan)

                    # Append the datetime and the adjusted energy value to the corresponding phase data
                    self.data[phase]["timestamps"].append(dt)
                    self.data[phase]["Energy_E"].append(adjusted_energy)

                    # Update last logged id if you need it for further processing
                    self.last_logged_id = row_id

            # # If needed, further filter or clean the data just in case (for example, if self.data already had older entries)
            # for phase in phases:
            #     d = self.data[phase]
            #     filtered = [
            #         (t, e) for t, e in zip(d["timestamps"], d["Energy_E"])
            #         if day_start <= t < day_end
            #     ]
            #     self.data[phase]["timestamps"] = [t for t, _ in filtered]
            #     self.data[phase]["Energy_E"] = [e for _, e in filtered]

            self.refresh_plot()

        except Exception as e:
            print(f"[CurrentPage Error] {e}")

        self.after(1000, self.update_data)  # find it Ayush

    def refresh_plot(self):
        self.ax.clear()

        label = "Energy (kWh)"

        self.ax.set_ylabel(label, fontsize=20)

        self.ax.yaxis.grid(True, linestyle="--", linewidth=0.8)
        self.ax.yaxis.get_offset_text().set_fontsize(20)
        self.ax.yaxis.get_offset_text().set_x(-0.08)
        # self.ax.yaxis.get_offset_text().set_text(f"[ *{self.ax.yaxis.get_offset_text()}]")
        self.ax.yaxis.get_offset_text().set_fontweight("bold")

        self.ax.xaxis.grid(False)
        max_energy = 0  # default fallback
        phase_data = self.data[self.phase_view]
        for value_type in self.value_types:
            values = phase_data[value_type]
            if values:
                max_energy = max(max_energy, max(values))

        self.ax.set_ylim(0, max_energy * 1.05)  # Add 5% padding for visual space

        value_colors = {"Energy_E": "red"}
        value_labels = {"Energy_E": "Energy"}

        # === Prepare 2-row Table Data ===
        col_labels = ["Phase A", "Phase B", "Phase C"]
        energy_row = []

        for phase in ["R", "Y", "B"]:
            values = self.data[phase]["Energy_E"]
            if values:
                energy_row.append(f"{values[-1]:.5f}")
            else:
                energy_row.append("-")

        # === Display Table (Header + 1 Row) ===
        table = self.ax.table(
            cellText=[energy_row],
            colLabels=col_labels,
            cellLoc="center",
            loc="upper center",
            bbox=[0, 1.02, 1, 0.3],
        )
        table.scale(0.7, 1.3)

        for _, cell in table.get_celld().items():
            cell.set_fontsize(25)
            cell.set_text_props(color="black")

        # === Plot energy graph ===
        phase_data = self.data[self.phase_view]
        timestamps = phase_data["timestamps"]

        if timestamps:
            for value_type in self.value_types:
                values = phase_data[value_type]
                self.ax.plot(
                    timestamps,
                    values,
                    label=value_labels[value_type],
                    color=value_colors[value_type],
                    linestyle="-",
                    linewidth=4,
                )
            # phase_data = self.data[self.phase_view]
            # timestamps = phase_data["timestamps"]

            # MAX_GAP = 3  # seconds
            # if timestamps:
            #     for value_type in self.value_types:
            #         values = phase_data[value_type]
            #         if not values or not timestamps:
            #             continue

            #         t_seg = [timestamps[0]]
            #         v_seg = [values[0]]

            #         for i in range(1, len(timestamps)):
            #             if (timestamps[i] - timestamps[i - 1]).total_seconds() <= MAX_GAP:
            #                 t_seg.append(timestamps[i])
            #                 v_seg.append(values[i])
            #             else:
            #                 if len(t_seg) > 1:
            #                     self.ax.plot(
            #                         t_seg, v_seg,
            #                         label=value_labels[value_type] if value_type not in self.ax.get_legend_handles_labels()[1] else "",
            #                         color=value_colors[value_type],
            #                         linestyle='-',
            #                         linewidth=4
            #                     )
            #                 t_seg = [timestamps[i]]
            #                 v_seg = [values[i]]

            #         if len(t_seg) > 1:
            #             self.ax.plot(
            #                 t_seg, v_seg,
            #                 label=value_labels[value_type] if value_type not in self.ax.get_legend_handles_labels()[1] else "",
            #                 color=value_colors[value_type],
            #                 linestyle='-',
            #                 linewidth=4
            #             )

            #     # Time axis setup
            #     day_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=IST)
            #     latest_time = max(timestamps)
            #     latest_time_rounded = (latest_time + timedelta(minutes=1)).replace(second=0, microsecond=0)

            #     self.ax.set_xlim(day_start, latest_time_rounded)

            #     tick_times = []
            #     t = day_start
            #     while t <= latest_time_rounded:
            #         tick_times.append(t)
            #         t += timedelta(hours=3)

            #     self.ax.set_xticks(tick_times)
            #     self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=IST))
            #     self.ax.tick_params(axis='x', labelsize=20)
            #     self.ax.tick_params(axis='y', labelsize=20)
            #     self.ax.legend(fontsize=20)

            day_start = datetime.combine(date.today(), datetime.min.time()).replace(
                tzinfo=IST
            )
            latest_time = max(timestamps)

            # Round latest_time up to the next full minute
            latest_time_rounded = (latest_time + timedelta(minutes=1)).replace(
                second=0, microsecond=0
            )

            # Set X-axis limits from 00:00 to the rounded latest time
            self.ax.set_xlim(day_start, latest_time_rounded)

            # Generate ticks every 3 hours starting from 00:00
            tick_times = []
            t = day_start
            while t <= latest_time_rounded:
                tick_times.append(t)
                t += timedelta(hours=3)

            self.ax.set_xticks(tick_times)

            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=IST))

            self.ax.tick_params(axis="x", labelsize=20)
            self.ax.tick_params(axis="y", labelsize=20)
            # self.ax.legend(fontsize=20)

        self.fig.subplots_adjust(left=0.08, right=0.65, top=0.81, bottom=0.45)
        self.canvas.draw()
