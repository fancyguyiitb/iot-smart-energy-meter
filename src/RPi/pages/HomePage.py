import tkinter as tk
import sqlite3
from tkinter import Label
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Dark theme constants
BG_COLOR = "#121212"

# Database name
from config import DB_PATH as DB_NAME  # one DB path shared by every process


class HomePage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # Matplotlib Figure Setup
        self.fig, self.ax = plt.subplots(figsize=(19, 9), constrained_layout=True)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill="both", expand=True, padx=0, pady=0)

        self.update_loop_running = False

    def on_show(self):
        print("[HomePage] Active")
        self.update_loop_running = True
        self._job = self.after(100, self.update_table)

    def on_hide(self):
        print("[HomePage] Hidden")
        self.update_loop_running = False
        if getattr(self, "_job", None):
            self.after_cancel(self._job)  # don't leave a refresh loop running while hidden
            self._job = None

    def update_table(self):
        if not self.update_loop_running:
            return

        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()

            # Instead of multiple queries, use one query to fetch the latest record for each phase.
            # Assumes that for every phase, the highest id is the latest record.
            query = """
                SELECT t.phase, t.voltage_rms, t.current_rms, t.active_power,
                       t.reactive_power, t.apparent_power, t.power_factor, t.timestamp
                FROM power_data t
                JOIN (
                  SELECT phase, MAX(id) AS max_id
                  FROM power_data
                  WHERE phase IN ('R','Y','B','Neutral')  -- stored names (was 'A','B','C': R/Y never showed)
                  GROUP BY phase
                ) AS latest
                  ON t.phase = latest.phase AND t.id = latest.max_id
            """
            cursor.execute(query)
            results = cursor.fetchall()
            conn.close()

            # Build a dictionary from the fetched data.
            data = {}
            for row in results:
                phase = row[0]
                data[phase] = row[
                    1:
                ]  # (voltage_rms, current_rms, active_power, reactive_power, apparent_power, power_factor, timestamp)

            # Construct table data.
            table_data = [
                ["Phase", "Vrms(V)", "Irms(A)", "P(W)", "Q(VAR)", "S(VA)", "PF"]
            ]

            for phase in ["R", "Y", "B"]:
                if phase in data:
                    v, i, p, q, s, pf, t = data[phase]
                    table_data.append(
                        [
                            phase,
                            f"{v:.2f}",
                            f"{i:.2f}",
                            f"{p:.2f}",
                            f"{q:.2f}",
                            f"{s:.2f}",
                            f"{pf:.2f}",
                        ]
                    )
                else:
                    table_data.append([phase] + ["-"] * 6)

            if "Neutral" in data:
                # For Neutral, only display current (or modify as required)
                _, i, *_, t = data["Neutral"]
                table_data.append(["Neutral", "0.00", f"{i:.2f}", "-", "-", "-", "-"])
            else:
                table_data.append(["Neutral", "0.00", "-", "-", "-", "-", "-"])

            # Clear current axes and create a new table.
            self.ax.clear()
            self.ax.axis("off")

            table = self.ax.table(
                cellText=table_data,
                loc="upper left",
                cellLoc="center",
                colWidths=[0.12] * len(table_data[0]),
            )

            # Update table cells only once.
            for key, cell in table.get_celld().items():
                cell.set_fontsize(46)
                cell.set_text_props(color="black")

            table.scale(0.75, 6.5)
            self.canvas.draw()

        except Exception as e:
            print(f"[HomePage Error] {e}")

        # Update every second.
        self._job = self.after(1000, self.update_table)
