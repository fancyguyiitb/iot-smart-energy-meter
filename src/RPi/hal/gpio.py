"""``RPi.GPIO``-compatible module: the real library on the Pi, virtual pins elsewhere."""

from hal import HAL

if HAL == "hardware":
    from RPi.GPIO import *  # noqa: F401,F403
else:
    from hal.virtual_gpio import *  # noqa: F401,F403
