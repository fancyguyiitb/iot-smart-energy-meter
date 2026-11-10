"""Touchscreen GUI of the meter. Loads every page in ``pages/`` (files starting with
``_`` are skipped) and shows them behind a bottom navigation bar.

Fixes compared with the original version:
* Page switching runs on the Tk main thread (``after``) instead of a background thread;
  Tkinter is not thread-safe, which caused random freezes and crashes.
* Rapid taps can't stack several modal "LOADING..." windows.
* Deterministic page order (``os.listdir`` order differs between machines).
* Window geometry / full screen come from config (GUI_GEOMETRY, GUI_FULLSCREEN).
"""

import importlib.util
import inspect
import os
import tkinter as tk

from config import GUI_FULLSCREEN, GUI_GEOMETRY
from db import init_db

# Global Styles
NAVBAR_HEIGHT = 60
BUTTON_PAD = 15
BUTTON_FONT = ("Segoe UI", 30)
BTN_BG = "lightgray"
BTN_ACTIVE = "#333333"
BTN_TEXT = "#FFFFFF"
BG_COLOR = "#121212"

DISPLAY_NAME_MAP = {
    "THD_and_FreqPage": "Harmonics",
    "HomePage": "Home",
    "HistoryPage": "History",
    "CurrentPage": "V - I",
    "PowerPage": "Power",
    "ResetPage": "Energy Reset",
    "PowerFailurePage": "Failure Log",
    "QRCodePage": "Get QR",
}

PAGE_ORDER = ["HomePage", "CurrentPage", "PowerPage", "EnergyPage", "THD_and_FreqPage",
              "HistoryPage", "PowerFailurePage", "QRCodePage", "ResetPage"]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Voltix")
        self.configure(cursor="none" if GUI_FULLSCREEN else "")
        self.geometry(GUI_GEOMETRY)
        if GUI_FULLSCREEN:
            self.attributes("-fullscreen", True)

        self.bind("<Escape>", lambda e: self.destroy())

        # Layout config
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.container = tk.Frame(self)
        self.container.grid(row=0, column=0, sticky="nsew")

        self.frames = {}
        self._switching = False
        self.pages = self.load_pages()

        self.create_navbar()
        self.show_frame("HomePage")

    def create_navbar(self):
        self.navbar = tk.Frame(self, height=NAVBAR_HEIGHT, bg=BTN_BG)
        self.navbar.grid(row=1, column=0, sticky="ew")
        self.navbar.grid_columnconfigure(tuple(range(len(self.pages))), weight=1)

        for idx, PageClass in enumerate(self.pages):
            page_name = PageClass.__name__
            frame = PageClass(parent=self.container, controller=self)
            self.frames[page_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

            display_name = DISPLAY_NAME_MAP.get(
                page_name, page_name.replace("Page", "")
            )
            btn = tk.Button(
                self.navbar,
                text=display_name,
                command=lambda name=page_name: self.show_frame(name),
                bg=BTN_BG,
                font=BUTTON_FONT,
                padx=BUTTON_PAD,
                pady=BUTTON_PAD,
            )
            btn.grid(row=0, column=idx, sticky="nsew")

    def show_frame(self, page_name):
        if self._switching or page_name not in self.frames:
            return
        self._switching = True

        loading_win = tk.Toplevel(self)
        loading_win.title("Loading...")
        loading_win.geometry(GUI_GEOMETRY)
        loading_win.transient(self)
        loading_win.overrideredirect(True)
        loading_win.configure(bg="white")
        tk.Label(loading_win, text="LOADING...", font=("Segoe UI", 45), fg="black", bg="white").pack(
            expand=True, fill="both")
        loading_win.update_idletasks()

        def switch_page():
            try:
                for frame in self.frames.values():
                    if hasattr(frame, "on_hide"):
                        frame.on_hide()
                frame = self.frames[page_name]
                frame.tkraise()
                if hasattr(frame, "on_show"):
                    frame.on_show()
            finally:
                loading_win.destroy()
                self._switching = False

        # Give the overlay one paint, then switch - all on the Tk main thread.
        self.after(50, switch_page)

    def load_pages(self):
        pages = []
        pages_dir = os.path.join(os.path.dirname(__file__), "pages")
        for filename in sorted(os.listdir(pages_dir)):
            if filename.endswith(".py") and not filename.startswith("_"):
                module_name = filename[:-3]
                file_path = os.path.join(pages_dir, filename)
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, tk.Frame) and obj.__module__ == module_name:
                        pages.append(obj)
        order = {name: i for i, name in enumerate(PAGE_ORDER)}
        return sorted(pages, key=lambda c: (order.get(c.__name__, len(order)), c.__name__))


if __name__ == "__main__":
    init_db()
    app = App()
    app.mainloop()
