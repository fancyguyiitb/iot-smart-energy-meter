import tkinter as tk
from PIL import Image, ImageTk
import qrcode
from cryptography.fernet import Fernet
from datetime import datetime

def encrypt_device_time(secret_key: bytes, device_id: str) -> bytes:
    """
    Encrypts the device_id and current time using the provided secret_key.

    Returns:
        Encrypted token (bytes)
    """
    cipher = Fernet(secret_key)
    current_time = datetime.utcnow().isoformat()
    data = f"{device_id}::{current_time}"
    return cipher.encrypt(data.encode())


class QRCodePage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg="white")
        self.controller = controller
        SECRET_KEY = b'Lqv-21_gHUjkaP4cLPCFi50SGSqwEoYRUWk-M6BP7EQ=' # FIXME: Remove this in final production.
        qr_data = encrypt_device_time(SECRET_KEY, "random12")
        self.qr_data = qr_data

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

    def on_show(self):
        qr = qrcode.make(self.qr_data)
        img = qr.get_image()
        img = img.resize((400, 400))
        img_tk = ImageTk.PhotoImage(img)

        self.qr_label.config(image=img_tk)
        self.qr_label.image = img_tk  # Prevent garbage collection
