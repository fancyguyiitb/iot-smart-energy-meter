import subprocess
import time
import threading

TOUCH_DEVICE_NAME = "xwayland-touch:13"  # Replace with your exact touch device name
IDLE_TIME = 30  # seconds

def turn_off_display():
    subprocess.run(["vcgencmd", "display_power", "0"])

def turn_on_display():
    subprocess.run(["vcgencmd", "display_power", "1"])

def monitor_touch():
    p = subprocess.Popen(['xinput', 'test', TOUCH_DEVICE_NAME], stdout=subprocess.PIPE)
    last_event = time.time()
    display_off = False

    def idle_check():
        nonlocal last_event, display_off
        while True:
            if time.time() - last_event > IDLE_TIME:
                if not display_off:
                    turn_off_display()
                    display_off = True
            else:
                if display_off:
                    turn_on_display()
                    display_off = False
            time.sleep(1)

    threading.Thread(target=idle_check, daemon=True).start()

    for line in p.stdout:
        if b"motion" in line or b"button" in line:
            last_event = time.time()

if __name__ == "__main__":
    monitor_touch()
