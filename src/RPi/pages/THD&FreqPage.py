import tkinter as tk
import sqlite3
import matplotlib.pyplot as plt
from tkinter import Label
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime

# Set global dark theme for matplotlib
# plt.style.use('dark_background')
BG_COLOR = "#121212"

from config import DB_PATH as DB_NAME  # one DB path shared by every process


class THD_and_FreqPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)  # , bg=BG_COLOR
        self.controller = controller

        self.fig, self.ax = plt.subplots(figsize=(8, 4))  # 19,9
        # self.fig.patch.set_facecolor(BG_COLOR)
        # self.ax.set_facecolor("#222222")

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.time_stamps = []
        self.freq_data = {"R": [], "Y": [], "B": []}
        self.update_loop_running = False
        self.last_logged_id = 0

    def on_show(self):
        print("[THDPage] Active")
        self.update_loop_running = True
        self._job = self.after(100, self.update_data)

    def on_hide(self):
        print("[THDPage] Hidden")
        self.update_loop_running = False
        if getattr(self, "_job", None):
            self.after_cancel(self._job)  # don't leave a refresh loop running while hidden
            self._job = None

    def update_data(self):
        if not self.update_loop_running:
            return

        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()

            # 🔹 Fetch Latest THD and Frequency Data (Per Phase)
            data = {}
            for phase in ["R", "Y", "B"]:
                cursor.execute(
                    """
                    SELECT voltage_thd, current_thd, voltage_freq
                    FROM power_data
                    WHERE phase = ? AND voltage_thd IS NOT NULL AND voltage_freq IS NOT NULL
                    ORDER BY id DESC LIMIT 1
                """,
                    (phase,),
                )
                row = cursor.fetchone()
                if row:
                    data[phase] = row

            conn.close()

            # 🔹 Prepare Combined Table Data
            combined_table_data = [
                ["Phase", "Voltage THD (%)", "Current THD (%)", "Frequency (Hz)"]
            ]
            for phase in ["R", "Y", "B"]:
                if phase in data:
                    vthd, cthd, freq = data[phase]
                    combined_table_data.append(
                        [phase, f"{vthd:.2f}", f"{cthd:.2f}", f"{freq:.2f}"]
                    )
                else:
                    combined_table_data.append([phase, "-", "-", "-"])

            # 🔹 Draw Combined Table
            self.ax.clear()
            self.ax.axis("off")

            table = self.ax.table(
                cellText=combined_table_data,
                loc="upper left",
                cellLoc="center",
                colWidths=[0.12] * len(combined_table_data[0]),
            )
            for key, cell in table.get_celld().items():
                cell.set_fontsize(70)
                cell.set_text_props(color="black")
                # cell.set_facecolor("#333333")  # optional for dark mode
            table.scale(1.3, 7.44)

            self.fig.tight_layout()
            self.canvas.draw()

        except Exception as e:
            print(f"[THDPage Error] {e}")

        self._job = self.after(1000, self.update_data)
