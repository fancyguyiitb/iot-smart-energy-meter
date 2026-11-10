"""Virtual Voltix meter board: physics + emulated ADE9000 + relay GPIOs, over HTTP.

Two kinds of clients talk to this process:

* The **firmware** (``src/RPi``) with ``VOLTIX_HAL=virtual``: its SPI and GPIO calls are
  forwarded here (``/spi``, ``/gpio``) instead of to /dev/spidev0.0 and the BCM pins.
* The **control panel** (``/``): a browser UI that plays the role of the physical world -
  switch appliances, inject grid faults, watch relays and the ground-truth readings.

Run:  uvicorn server:app --port 9000   (from this directory)
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from chip import VirtualADE9000
from physics import PHASES, Installation

TICK_HZ = float(os.getenv("SIM_TICK_HZ", "10"))
# BCM pin -> phase relay. Must match RELAY_PINS in the firmware's device.env.
RELAY_PINS = {int(pin): phase for phase, pin in
              (item.split(":") for item in os.getenv("SIM_RELAY_PINS", "R:17,Y:27,B:22").split(","))}
RELAY_ACTIVE_HIGH = os.getenv("SIM_RELAY_ACTIVE_HIGH", "true").lower() == "true"

installation = Installation()
chip = VirtualADE9000(installation)
gpio_levels: dict[int, int] = {}
gpio_modes: dict[int, str] = {}
gpio_lock = threading.Lock()
_stop = threading.Event()


def _apply_relays() -> None:
    for pin, phase in RELAY_PINS.items():
        level = gpio_levels.get(pin, 0)
        installation.set_relay(phase, bool(level) == RELAY_ACTIVE_HIGH and gpio_modes.get(pin) == "out")


def _sim_loop() -> None:
    period = 1.0 / TICK_HZ
    while not _stop.is_set():
        started = time.monotonic()
        chip.update()
        _stop.wait(max(0.0, period - (time.monotonic() - started)))


@asynccontextmanager
async def lifespan(_: FastAPI):
    thread = threading.Thread(target=_sim_loop, name="sim-loop", daemon=True)
    thread.start()
    yield
    _stop.set()
    thread.join(timeout=2)


app = FastAPI(title="Voltix virtual meter board", lifespan=lifespan)
STATIC = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------------------------------------------------------------------- firmware side
class SpiFrame(BaseModel):
    tx: list[int] = Field(..., max_length=4096)


@app.post("/spi/{bus}/{device}")
def spi_transfer(bus: int, device: int, frame: SpiFrame):
    if (bus, device) != (0, 0):
        raise HTTPException(404, "No chip on that chip-select")
    return {"rx": chip.transfer(frame.tx)}


class GpioSetup(BaseModel):
    pin: int
    mode: str = "out"  # out | in
    initial: int | None = None


class GpioWrite(BaseModel):
    pin: int
    level: int


@app.post("/gpio/setup")
def gpio_setup(req: GpioSetup):
    with gpio_lock:
        gpio_modes[req.pin] = req.mode
        if req.initial is not None:
            gpio_levels[req.pin] = 1 if req.initial else 0
        else:
            gpio_levels.setdefault(req.pin, 0)
        _apply_relays()
    return {"pin": req.pin, "level": gpio_levels[req.pin]}


@app.post("/gpio/write")
def gpio_write(req: GpioWrite):
    with gpio_lock:
        if gpio_modes.get(req.pin) != "out":
            raise HTTPException(409, f"GPIO{req.pin} is not configured as an output")
        gpio_levels[req.pin] = 1 if req.level else 0
        _apply_relays()
    return {"pin": req.pin, "level": gpio_levels[req.pin]}


@app.get("/gpio/{pin}")
def gpio_read(pin: int):
    with gpio_lock:
        return {"pin": pin, "level": gpio_levels.get(pin, 0)}


@app.post("/gpio/cleanup")
def gpio_cleanup():
    with gpio_lock:
        gpio_modes.clear()
        gpio_levels.clear()
        _apply_relays()
    return {"ok": True}


# ---------------------------------------------------------------------- panel side
@app.get("/")
def panel():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "chip_running": chip.running}


@app.get("/api/state")
def state():
    data = installation.describe()
    data["chip"] = chip.stats()
    data["chip"]["firmware_connected"] = (time.time() - data["chip"]["last_access"]) < 5
    with gpio_lock:
        data["gpio"] = [{"pin": pin, "phase": phase, "mode": gpio_modes.get(pin), "level": gpio_levels.get(pin, 0)}
                        for pin, phase in RELAY_PINS.items()]
    return data


class ApplianceUpdate(BaseModel):
    on: bool


@app.post("/api/appliance/{appliance_id}")
def set_appliance(appliance_id: str, req: ApplianceUpdate):
    if appliance_id not in installation.appliances:
        raise HTTPException(404, "Unknown appliance")
    installation.set_appliance(appliance_id, req.on)
    return {"ok": True}


class PhaseUpdate(BaseModel):
    mode: str | None = Field(None, pattern="^(normal|sag|swell|outage)$")
    nominal_v: float | None = Field(None, ge=0, le=320)
    custom_kw: float | None = Field(None, ge=-10, le=15)
    custom_pf: float | None = Field(None, ge=0.05, le=1.0)
    ct_reversed: bool | None = None


@app.post("/api/phase/{phase}")
def update_phase(phase: str, req: PhaseUpdate):
    if phase not in PHASES:
        raise HTTPException(404, "Phase must be R, Y or B")
    installation.update_phase(phase, **req.model_dump())
    return {"ok": True}


class GridUpdate(BaseModel):
    frequency: float | None = Field(None, ge=45, le=55)
    voltage_thd: float | None = Field(None, ge=0, le=30)
    loose_neutral: float | None = Field(None, ge=0, le=1)
    noise: bool | None = None


@app.post("/api/grid")
def update_grid(req: GridUpdate):
    installation.update_grid(**req.model_dump())
    return {"ok": True}


@app.post("/api/scenario/{name}")
def scenario(name: str):
    try:
        installation.apply_scenario(name)
    except KeyError:
        raise HTTPException(404, "Unknown scenario")
    return {"ok": True}


@app.post("/api/reset-truth-energy")
def reset_truth_energy():
    installation.reset_truth_energy()
    return {"ok": True}


@app.post("/api/chip/power-cycle")
async def power_cycle():
    """Simulate the meter board losing power: the ADE9000 forgets its configuration."""
    with chip.lock:
        chip.regs.clear()
        chip.running = False
        for p in PHASES:
            chip.energy_acc_wh[p] = 0.0
    await asyncio.sleep(0)
    return {"ok": True}
