"""``spidev``-compatible module: real SPI on the Pi, virtual SPI everywhere else."""

from hal import HAL

if HAL == "hardware":
    from spidev import SpiDev  # noqa: F401
else:
    from hal.virtual_spi import SpiDev  # noqa: F401
