import tkinter as tk
import sqlite3
from zoneinfo import ZoneInfo
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime

from config import DB_PATH  # was a hard-coded absolute path that differed from the other processes

IST = ZoneInfo("Asia/Kolkata")


class PowerFailurePage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        self.fig, self.ax = plt.subplots(figsize=(19, 9), constrained_layout=True)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill="both", expand=True)

        refresh_btn = tk.Button(
            self, text="Refresh", command=self.refresh_data, font=("Arial", 16)
        )
        refresh_btn.pack(pady=10)

        self._job = None
        self.refresh_data()

    def on_show(self):
        # refresh_loop existed but was never started, so the log only updated on "Refresh".
        self.refresh_loop()

    def on_hide(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None

    def refresh_loop(self):
        self.refresh_data()
        self._job = self.after(10000, self.refresh_loop)

    def refresh_data(self):
        self.ax.clear()
        self.ax.axis("off")

        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT phase, failure_time 
                    FROM power_events 
                    ORDER BY failure_time DESC
                """)
                rows = cursor.fetchall()

            if not rows:
                table_data = [["-", "-"]]
            else:
                table_data = [["Phase", "Failure Time (IST)"]]
                for phase, fail_ts in rows:
                    fail_ist = datetime.fromisoformat(fail_ts).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    table_data.append([phase, fail_ist])

        except sqlite3.OperationalError:
            # DB or table doesn't exist
            table_data = [["-", "-"]]

        except Exception as e:
            print("[PowerFailurePage Error]", e)
            table_data = [["Error", str(e)]]

        table = self.ax.table(
            cellText=table_data,
            loc="upper left",
            cellLoc="center",
            colWidths=[0.3, 0.5],
        )

        for key, cell in table.get_celld().items():
            cell.set_fontsize(25)
            cell.set_text_props(color="black")

        table.scale(0.79, 4.5)
        self.canvas.draw()
