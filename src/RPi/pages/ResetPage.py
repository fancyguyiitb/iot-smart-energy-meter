"""Energy reset page (was ``_Reset.py``, which the page loader skipped because of the ``_``).

The old reset could not work: it set ``shared_flags.reset_flag`` in the GUI process
(the sampler is a separate process and never saw it), it deleted the whole database
(unsynced readings and the failure log included), it blocked the UI with
``time.sleep(2)``, and on the next start the sampler restored the old value anyway.

Now the GUI writes a reset request into the shared DB; the sampler zeroes its counters
on its next sample and acknowledges. Raw history is kept, and the sampler's start-up
restore uses the *latest* reading, so the reset survives restarts.
"""

import tkinter as tk
from tkinter import messagebox

from db import pending_energy_reset, request_energy_reset


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
            command=self.reset_energy
        )
        self.reset_button.pack(expand=True)
        self.status = tk.Label(self, text="", font=("Arial", 20))
        self.status.pack(pady=20)

    def reset_energy(self):
        if not messagebox.askyesno("Reset energy", "Reset the energy counters of all phases to 0 kWh?"):
            return
        try:
            request_energy_reset()
            self.status.config(text="Reset requested...")
            self.after(1500, self._check_done)
        except Exception as e:
            self.status.config(text=f"Database error: {e}")

    def _check_done(self):
        if pending_energy_reset():
            self.status.config(text="Waiting for the meter to apply the reset...")
            self.after(1000, self._check_done)
        else:
            self.status.config(text="Energy counters reset.")

    # Kept for compatibility with older callers.
    reset_database = reset_energy
