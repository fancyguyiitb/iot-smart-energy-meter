"""Hardware abstraction layer.

``from hal import spi`` and ``from hal import gpio`` give the firmware an ``spidev``-
compatible and an ``RPi.GPIO``-compatible module. With ``VOLTIX_HAL=hardware`` they are
the real libraries; with ``VOLTIX_HAL=virtual`` (the default off-device) they forward
every SPI frame and pin change to the virtual meter board in ``src/VirtualDevice``.
The driver and application code above this layer is identical in both cases.
"""

from config import HAL

if HAL not in {"hardware", "virtual"}:
    raise SystemExit(f"VOLTIX_HAL must be 'hardware' or 'virtual', got {HAL!r}")
