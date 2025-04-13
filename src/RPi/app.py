import tkinter as tk
import os
import importlib.util
import inspect
import threading
import time

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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("-")
        self.configure(cursor="none")
        self.geometry("2000x1010")

        self.bind("<Escape>", lambda e: self.destroy())

        # Layout config
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.container = tk.Frame(self)
        self.container.grid(row=0, column=0, sticky="nsew")

        self.frames = {}
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
        # Create loading window
        loading_win = tk.Toplevel(self)
        loading_win.title("Loading...")
        loading_win.geometry("2000x1010")
        loading_win.transient(self)
        loading_win.grab_set()
        loading_win.overrideredirect(True)
        loading_win.configure(bg="white")

        label = tk.Label(
            loading_win,
            text="LOADING...",
            font=("Segoe UI", 45),
            fg="black",
            bg="white",
        )
        label.pack(expand=True, fill="both")

        # Run frame switching in background so loading window appears immediately
        def switch_page():
            time.sleep(0.1)  # Let the loading window render
            for name, frame in self.frames.items():
                if hasattr(frame, "on_hide"):
                    frame.on_hide()

            frame = self.frames[page_name]

            # Simulate load delay (optional, remove in actual code)
            # time.sleep(2)

            frame.tkraise()
            if hasattr(frame, "on_show"):
                frame.on_show()

            # Close the loading window on main thread
            self.after(100, loading_win.destroy)

        threading.Thread(target=switch_page).start()

    def load_pages(self):
        pages = []
        pages_dir = os.path.join(os.path.dirname(__file__), "pages")
        for filename in os.listdir(pages_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                module_name = filename[:-3]
                file_path = os.path.join(pages_dir, filename)
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, tk.Frame) and obj.__module__ == module_name:
                        pages.append(obj)
        return pages


if __name__ == "__main__":
    app = App()
    app.mainloop()
