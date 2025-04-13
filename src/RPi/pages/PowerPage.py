import tkinter as tk
import sqlite3
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime, timedelta, date, timezone
import matplotlib.dates as mdates
from zoneinfo import ZoneInfo
import threading

DB_NAME = "power_meter_data.db"
BTN_BG = "lightgray"
BTN_ACTIVE = "#333333"
BTN_SELECTED = "white"  # 555555"
BTN_TEXT = "#FFFFFF"
BG_COLOR = "#121212"
IST = ZoneInfo("Asia/Kolkata")


class PowerPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        self.phase_view = "R"
        self.power_types = ["apparent_power"]  # removed apparent

        self.power_buttons = {}
        self.phase_buttons = {}

        self.main_panel = tk.Frame(self)
        self.main_panel.pack(fill="both", expand=True)

        self.fig, self.ax = plt.subplots(figsize=(8, 4))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.main_panel)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        btn_font = ("Arial", 30)

        # --- Power Type Buttons ---
        power_types = {
            "Total": ["apparent_power"],
            "Active": ["active_power"],
            "Reactive": ["reactive_power"],
        }

        for i, (label, powers) in enumerate(power_types.items()):
            btn = tk.Button(
                self.main_panel,
                text=label,
                font=btn_font,
                command=lambda p=powers, l=label: self.show_loading_overlay(
                    lambda: self.set_power_type(p, l)
                ),
                # command=lambda p=powers, l=label: self.set_power_type(p, l),
                bg=BTN_BG,  # fg=BTN_TEXT,
                # activebackground=BTN_ACTIVE,
                # activeforeground=BTN_TEXT
            )
            btn.place(relx=0.01 + 0.08 * i, rely=0.01)
            self.power_buttons[label] = btn

        # --- Phase Buttons ---
        phases = ["R", "Y", "B"]
        for i, phase in enumerate(phases):
            btn = tk.Button(
                self.main_panel,
                text=f"Phase {phase}",
                font=btn_font,
                command=lambda ph=phase: self.show_loading_overlay(
                    lambda: self.set_phase(ph)
                ),
                # command=lambda ph=phase: self.set_phase(ph),
                bg=BTN_BG,  # fg=BTN_TEXT,
                # activebackground=BTN_ACTIVE,
                # activeforeground=BTN_TEXT
            )
            btn.place(relx=0.355 + 0.1 * i, rely=0.01)
            self.phase_buttons[phase] = btn

        # --- Data Storage ---
        self.time_stamps = []
        self.data = {
            "R": {
                "timestamps": [],
                "apparent_power": [],
                "active_power": [],
                "reactive_power": [],
            },
            "Y": {
                "timestamps": [],
                "apparent_power": [],
                "active_power": [],
                "reactive_power": [],
            },
            "B": {
                "timestamps": [],
                "apparent_power": [],
                "active_power": [],
                "reactive_power": [],
            },
        }

        self.last_logged_id = 0
        self.update_loop_running = False

        # Set default selected styles
        self.set_power_type(["apparent_power"], "Total")
        self.set_power_type(["active_power"], "Active")
        self.set_power_type(["reactive_power"], "Reactive")
        self.set_phase("R")

    def show_loading_overlay(self, callback):
        loading_win = tk.Toplevel(self)
        loading_win.overrideredirect(True)
        loading_win.configure(bg="white")
        loading_win.geometry("2000x1010")

        loading_label = tk.Label(
            loading_win,
            text="LOADING...",
            font=("Segoe UI", 36),
            bg="white",
            fg="black",
        )
        loading_label.pack(expand=True)

        self.update_idletasks()

        def run_and_close():
            callback()
            loading_win.destroy()

        threading.Thread(target=run_and_close).start()

    def set_power_type(self, ptypes, label=None):
        self.power_types = ptypes
        print(f"[PowerPage] Showing: {', '.join(ptypes)} for Phase {self.phase_view}")
        for name, btn in self.power_buttons.items():
            btn.config(bg=BTN_SELECTED if name == label else BTN_BG)
        self.refresh_plot()

    def set_phase(self, phase):
        self.phase_view = phase
        print(f"[PowerPage] Viewing Phase: {phase}")
        for p, btn in self.phase_buttons.items():
            btn.config(bg=BTN_SELECTED if p == phase else BTN_BG)
        self.refresh_plot()

    def on_show(self):
        print("[PowerPage] Active")
        self.update_loop_running = True
        self.after(100, self.update_data)

    def on_hide(self):
        print("[PowerPage] Hidden")
        self.update_loop_running = False

    def update_data(self):
        if not self.update_loop_running:
            return

        from datetime import datetime, date, timedelta, timezone

        try:
            # Define IST timezone and compute today's 24-hour window in IST.
            ist = timezone(timedelta(hours=5, minutes=30))
            day_start = datetime.combine(date.today(), datetime.min.time()).replace(
                tzinfo=ist
            )
            day_end = day_start + timedelta(days=1)

            # Prepare the optimized query:
            #  - Fetch rows where id > last_logged_id.
            #  - Only return every third row (id % 3 == 0).
            #  - Return only rows from today's 24-hour period.
            query = """
                SELECT id, phase, apparent_power,active_power, reactive_power, timestamp
                FROM power_data
                WHERE id > ?
                  AND (id % 3) = 0
                  AND timestamp >= ? AND timestamp < ?
                ORDER BY id ASC
            """

            # Execute the query with the appropriate parameters.
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute(
                query, (self.last_logged_id, day_start.isoformat(), day_end.isoformat())
            )
            rows = cursor.fetchall()
            conn.close()

            # Process each row fetched from the query.
            # Since the SQL query already restricts the rows to today’s data,
            # additional filtering is minimal.
            for row in rows:
                row_id, phase, apparent, active, reactive, timestamp_str = row

                if phase not in self.data:
                    continue

                dt = datetime.fromisoformat(timestamp_str)  # Keeps the +05:30 offset

                # Append the row values directly since filtering is done in SQL.
                self.data[phase]["timestamps"].append(dt)
                self.data[phase]["apparent_power"].append(apparent)
                self.data[phase]["active_power"].append(active)
                self.data[phase]["reactive_power"].append(reactive)
                # Update last_logged_id with the latest processed row ID.
                self.last_logged_id = row_id

            # print("[INFO]: C Phase Data", len(self.data["B"]["active_power"]))

            # # Optionally, to ensure only today’s data is kept on the UI, we can
            # # filter the lists. This filtering loop should be nearly redundant now but is kept
            # # as a safeguard.
            # for phase in ["R", "Y", "B"]:
            #     data = self.data[phase]
            #     filtered = [
            #         (t, ap) for t, ap in zip(data["timestamps"], data["apparent_power"])
            #         if day_start <= t < day_end
            #     ]
            #     self.data[phase]["timestamps"] = [t for t, _ in filtered]
            #     self.data[phase]["apparent_power"] = [ap for _, ap in filtered]

            # Refresh the plot after processing new data.
            self.refresh_plot()

        except Exception as e:
            print(f"[PowerPage Error] {e}")

        self.after(1000, self.update_data)

    def refresh_plot(self):
        ist = timezone(timedelta(hours=5, minutes=30))
        day_start = datetime.combine(date.today(), datetime.min.time()).replace(
            tzinfo=ist
        )

        self.ax.clear()
        self.ax.set_ylabel("Power (VA / W / VAR)", fontsize=25)
        self.ax.yaxis.grid(True, linestyle="--", linewidth=0.8)
        self.ax.xaxis.grid(False)
        max_power = -1e5  # default fallback
        phase_data = self.data[self.phase_view]
        for power_type in self.power_types:
            powers = phase_data[power_type]
            if powers:
                max_power = max(max_power, max(powers))

        if "reactive_power" in self.power_types:
            min_power = (
                min(phase_data["reactive_power"]) if phase_data["reactive_power"] else 0
            )
            bottom = min(-1, min_power * 1.05)  # Always show some negative space
            top = max(1, max_power * 1.05)  # Ensure room at the top
        else:
            bottom = 0
            top = max(1, max_power * 1.05)  # Minimum top for visibility

        self.ax.set_ylim(bottom, top)

        power_colors = {
            "apparent_power": "red",
            "active_power": "green",
            "reactive_power": "blue",
        }
        power_labels = {
            "apparent_power": "Total Power",
            "active_power": "Active Power",
            "reactive_power": "Reactive Power",
        }

        phase_data = self.data[self.phase_view]
        timestamps = phase_data["timestamps"]

        if timestamps:
            MAX_GAP = 60  # seconds

            for power_type in self.power_types:
                ts = phase_data["timestamps"]
                vals = phase_data[power_type]
                if not ts:
                    continue

                t_seg, v_seg = [ts[0]], [vals[0]]
                for i in range(1, len(ts)):
                    if (ts[i] - ts[i - 1]).total_seconds() <= MAX_GAP:
                        t_seg.append(ts[i])
                        v_seg.append(vals[i])
                    else:
                        if len(t_seg) > 1:
                            self.ax.plot(
                                t_seg,
                                v_seg,
                                label=power_labels[power_type],
                                color=power_colors[power_type],
                                linestyle="-",
                                linewidth=4,
                            )
                        t_seg, v_seg = [ts[i]], [vals[i]]

                if len(t_seg) > 1:
                    self.ax.plot(
                        t_seg,
                        v_seg,
                        label=power_labels[power_type],
                        color=power_colors[power_type],
                        linestyle="-",
                        linewidth=4,
                    )

            # 👉 Put this here, **after** the for-loop:
            # self.ax.legend(fontsize=24)

            # ⏰ Set x-axis from 00:00 to latest timestamp
            latest_time = max(timestamps)

            # Make sure x-axis always starts at 00:00 IST today and ends at latest data timestamp
            self.ax.set_xlim(day_start, latest_time)

            # Calculate tick positions every 3 hours from 00:00 until the latest_time
            tick_times = []
            current_tick = day_start
            while current_tick <= latest_time:
                tick_times.append(current_tick)
                current_tick += timedelta(hours=3)

            self.ax.set_xticks(tick_times)

            # Format the tick labels as HH:MM in IST
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=IST))

            # Format ticks as HH:MM
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=IST))
            # Optional: vertical line for current time
            # self.ax.axvline(datetime.now(tz=ist), color='gray', linestyle='--', linewidth=1, label="Now")

            self.ax.tick_params(axis="x", labelsize=20)
            self.ax.tick_params(axis="y", labelsize=20)
        # self.ax.legend(fontsize=24)

        self.fig.subplots_adjust(left=0.09, right=0.65, top=0.9, bottom=0.45)
        self.canvas.draw()
