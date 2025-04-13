import tkinter as tk
import sqlite3
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime, timedelta, date, timezone
import matplotlib.dates as mdates
import threading
from zoneinfo import ZoneInfo

DB_NAME = "power_meter_data.db"
BTN_BG = "lightgray"
BTN_SELECTED = "white"
IST = ZoneInfo("Asia/Kolkata")


class CurrentPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.phase_view = "R"
        self.value_types = ["Current_A"]

        self.value_buttons = {}
        self.phase_buttons = {}

        self.main_panel = tk.Frame(self)
        self.main_panel.pack(fill="both", expand=True)

        self.fig, self.ax = plt.subplots(figsize=(8, 4))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.main_panel)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        btn_font = ("Arial", 30)

        # --- Value Type Buttons ---
        value_types = {"Current": ["Current_A"], "Voltage": ["Voltage_V"]}
        for i, (label, values) in enumerate(value_types.items()):
            btn = tk.Button(
                self.main_panel,
                text=label,
                font=btn_font,
                command=lambda v=values, l=label: self.show_loading_overlay(
                    lambda: self.set_value_type(v, l)
                ),
                bg=BTN_BG,
            )
            btn.place(relx=0.01 + 0.1 * i, rely=0.01)
            self.value_buttons[label] = btn

        # --- Phase Buttons ---
        for i, phase in enumerate(["R", "Y", "B"]):
            btn = tk.Button(
                self.main_panel,
                text=f"Phase {phase}",
                font=btn_font,
                command=lambda ph=phase: self.show_loading_overlay(
                    lambda: self.set_phase(ph)
                ),
                bg=BTN_BG,
            )
            btn.place(relx=0.355 + 0.1 * i, rely=0.01)
            self.phase_buttons[phase] = btn

        # --- Data Storage ---
        self.data = {
            "R": {"timestamps": [], "Current_A": [], "Voltage_V": []},
            "Y": {"timestamps": [], "Current_A": [], "Voltage_V": []},
            "B": {"timestamps": [], "Current_A": [], "Voltage_V": []},
        }

        self.last_logged_id = 0
        self.update_loop_running = False

        self.set_value_type(["Current_A"], "Current")
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

    def set_value_type(self, vtypes, label=None):
        self.value_types = vtypes
        print(f"[CurrentPage] Showing: {', '.join(vtypes)} for Phase {self.phase_view}")
        for name, btn in self.value_buttons.items():
            btn.config(bg=BTN_SELECTED if name == label else BTN_BG)
        self.refresh_plot()

    def set_phase(self, phase):
        self.phase_view = phase
        print(f"[CurrentPage] Viewing Phase: {phase}")
        for p, btn in self.phase_buttons.items():
            btn.config(bg=BTN_SELECTED if p == phase else BTN_BG)
        self.refresh_plot()

    def on_show(self):
        print("[CurrentPage] Active")
        self.update_loop_running = True
        self.after(100, self.update_data)

    def on_hide(self):
        print("[CurrentPage] Hidden")
        self.update_loop_running = False

    def update_data(self):
        if not self.update_loop_running:
            return

        try:
            day_start = datetime.combine(date.today(), datetime.min.time()).replace(
                tzinfo=IST
            )
            day_end = day_start + timedelta(days=1)
            # Prepare the optimized query:
            #   - Only select rows with id greater than the last processed id.
            #   - Include only every third row (id % 3 == 0).
            #   - Filter rows by timestamp so that only today's data is returned.
            query = """
                    SELECT id, phase, current_rms, voltage_rms, timestamp
                    FROM power_data
                    WHERE id > ?
                      AND (id % 3) = 0
                      AND timestamp >= ? AND timestamp < ?
                    ORDER BY id ASC
                """
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute(
                query, (self.last_logged_id, day_start.isoformat(), day_end.isoformat())
            )
            rows = cursor.fetchall()
            conn.close()

            # Process the returned rows
            for row in rows:
                row_id, phase, current, voltage, timestamp_str = row

                if phase not in self.data:
                    continue

                dt = datetime.fromisoformat(
                    timestamp_str
                )  # ISO format preserves tzinfo
                # Append the fetched data directly; extra filtering is now unnecessary
                self.data[phase]["timestamps"].append(dt)
                self.data[phase]["Current_A"].append(current)
                self.data[phase]["Voltage_V"].append(voltage)

                self.last_logged_id = row_id  # Update the last logged ID

            self.refresh_plot()

            # for row in rows:
            #     row_id, phase, current, voltage, timestamp = row

            #     if phase not in self.data:
            #         continue

            #     dt = datetime.fromisoformat(timestamp)  # ISO format preserves tzinfo
            #     if day_start <= dt < day_end:
            #         self.data[phase]["timestamps"].append(dt)
            #         self.data[phase]["Current_A"].append(current)
            #         self.data[phase]["Voltage_V"].append(voltage)

            #     self.last_logged_id = row_id

            # for phase in ["R", "Y", "B"]:
            #     d = self.data[phase]
            #     filtered = [
            #         (t, c, v) for t, c, v in zip(d["timestamps"], d["Current_A"], d["Voltage_V"])
            #         if day_start <= t < day_end
            #     ]
            #     self.data[phase]["timestamps"] = [t for t, _, _ in filtered]
            #     self.data[phase]["Current_A"] = [c for _, c, _ in filtered]
            #     self.data[phase]["Voltage_V"] = [v for _, _, v in filtered]

            # self.refresh_plot()

        except Exception as e:
            print(f"[CurrentPage Error] {e}")

        self.after(1000, self.update_data)

    def refresh_plot(self):
        self.ax.clear()
        self.ax.set_ylabel("Current/Voltage", fontsize=20)
        self.ax.yaxis.grid(True, linestyle="--", linewidth=0.8)
        self.ax.xaxis.grid(False)

        value_colors = {
            "Current_A": "red",
            "Voltage_V": "green",
        }
        value_labels = {
            "Current_A": "Current",
            "Voltage_V": "Voltage",
        }

        phase_data = self.data[self.phase_view]
        timestamps = phase_data["timestamps"]

        if timestamps:
            MAX_GAP = 60  # seconds
            plotted_labels = set()

            for value_type in self.value_types:
                ts = phase_data["timestamps"]
                vals = phase_data[value_type]
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
                                label=value_labels[value_type],
                                color=value_colors[value_type],
                                linestyle="-",
                                linewidth=4,
                            )
                        t_seg, v_seg = [ts[i]], [vals[i]]
                if len(t_seg) > 1:
                    self.ax.plot(
                        t_seg,
                        v_seg,
                        label=value_labels[value_type],
                        color=value_colors[value_type],
                        linestyle="-",
                        linewidth=4,
                    )

            latest_time = max(timestamps)

            # Day start for reference
            day_start = datetime.combine(date.today(), datetime.min.time()).replace(
                tzinfo=IST
            )

            # X-axis from 00:00 to latest time
            self.ax.set_xlim(day_start, latest_time)

            # Generate ticks at fixed 3-hour intervals from midnight up to the latest time
            tick_times = []
            tick = day_start
            while tick <= latest_time:
                tick_times.append(tick)
                tick += timedelta(hours=3)

            self.ax.set_xticks([mdates.date2num(t) for t in tick_times])
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=IST))

            self.ax.tick_params(axis="x", labelsize=20)
            self.ax.tick_params(axis="y", labelsize=20)
            # self.ax.legend(fontsize=24)

        self.fig.subplots_adjust(left=0.075, right=0.65, top=0.91, bottom=0.45)
        self.canvas.draw()
