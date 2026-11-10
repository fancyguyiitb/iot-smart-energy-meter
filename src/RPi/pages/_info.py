import os
import tkinter as tk
from PIL import Image, ImageTk

# Dark theme constants
BG_COLOR = "#121212"
TEXT_COLOR = "#FFFFFF"
HEADING_FONT = ("Helvetica", 36, "bold")
LABEL_FONT = ("Helvetica", 20)

class InfoPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=BG_COLOR)
        self.controller = controller

        # Heading
        heading = tk.Label(
            self,
            text="TEAM MEMBER",
            font=HEADING_FONT,
            bg=BG_COLOR,
            fg=TEXT_COLOR
        )
        heading.place(x=500, y=30)  # Adjust to center horizontally

        # Single member details
        img_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cherish.jpg')
        name = "Alice Johnson"
        roll = "22b3937"

        try:
            image = Image.open(img_path)
            image = image.resize((200, 200), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)

            self.img_label = tk.Label(self, image=photo, bg=BG_COLOR)
            self.img_label.image = photo  # Prevent GC
            self.img_label.place(x=540, y=130)  # Adjust to position image

        except Exception as e:
            print(f"[InfoPage Error] Unable to load {img_path}: {e}")
            self.img_label = tk.Label(self, text="[Image not found]", font=LABEL_FONT, bg=BG_COLOR, fg="red")
            self.img_label.place(x=500, y=130)

        # Name and Roll Number below image
        self.name_label = tk.Label(self, text=name, font=LABEL_FONT, bg=BG_COLOR, fg=TEXT_COLOR)
        self.roll_label = tk.Label(self, text=roll, font=LABEL_FONT, bg=BG_COLOR, fg=TEXT_COLOR)

        self.name_label.place(x=570, y=350)  # Centered below image
        self.roll_label.place(x=580, y=390)
