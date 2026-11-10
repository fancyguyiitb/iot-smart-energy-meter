"""Sign-up QR code.

Fixes compared with the original version:
* No secret in the source: the code is signed with this device's provisioned CLAIM_KEY
  (the old hard-coded Fernet key is public on GitHub and must be considered burnt).
* The code is short-lived and one-time, and is regenerated while the page is shown;
  it used to be created once at boot, from a hard-coded device id.
* The code is also printed as text, for typing/pasting it into the web app.
"""

import tkinter as tk

import qrcode
from PIL import ImageTk

from claim import make_claim_code
from config import CLAIM_CODE_REFRESH_S


class QRCodePage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg="white")
        self.controller = controller
        self._job = None

        self.qr_label = tk.Label(self, bg="beige")
        self.qr_label.place(x=450, y=90)

        self.text_label = tk.Label(
            self,
            text="Scan me to Sign Up",
            font=("Segoe UI", 28),
            bg="white",
            fg="black"
        )
        self.text_label.place(x=490, y=490)  # Adjust as needed

        self.code_label = tk.Label(self, text="", font=("Consolas", 10), bg="white", fg="#555",
                                   wraplength=900, justify="left")
        self.code_label.place(x=60, y=550)

    def on_show(self):
        self.refresh_code()

    def on_hide(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None

    def refresh_code(self):
        try:
            code = make_claim_code()
        except Exception as e:  # device not provisioned
            self.text_label.config(text="Device not provisioned")
            self.code_label.config(text=str(e))
            return
        img = qrcode.make(code).get_image().resize((400, 400))
        img_tk = ImageTk.PhotoImage(img)
        self.qr_label.config(image=img_tk)
        self.qr_label.image = img_tk  # Prevent garbage collection
        self.text_label.config(text="Scan me to Sign Up")
        self.code_label.config(text=f"Code (valid {CLAIM_CODE_REFRESH_S // 60} min): {code}")
        self._job = self.after(CLAIM_CODE_REFRESH_S * 1000, self.refresh_code)
