# Virtual meter board

A software stand-in for the Voltix meter board, so the firmware, server and app can be developed and tested without hardware.

It has three layers:

| Layer | File | Role |
|---|---|---|
| Physical world | `physics.py` | 3-phase, 4-wire 230 V / 50 Hz supply with source impedance; appliances (resistive, motor, switch-mode, cycling fridge); relays; faults |
| Chip | `chip.py` | Register-level ADE9000 emulation: SPI framing, RUN gate, RMS/power/PF/THD/period/angle/temperature registers, 32-bit wrapping energy accumulators |
| Bus | `server.py` | HTTP endpoints for the firmware's virtual SPI (`/spi/0/0`) and GPIO (`/gpio/*`), plus the control panel API |

The firmware's real driver (`src/RPi/ADE9000API.py`) runs unchanged against this chip. Register codes are derived from the board's calibration constants, so every conversion in the driver is exercised. That is how the driver's sign-extension and register-scaling bugs were caught.

## Run

Normally started by `python scripts/run_local.py`. On its own:

```bash
cd src/VirtualDevice
uvicorn server:app --port 9000
```

Open http://127.0.0.1:9000/ for the control panel.

## What you can simulate

* **Loads:** toggle appliances per phase, or add an adjustable load. A negative load is generation (rooftop solar), which produces export.
* **Supply faults per phase:** sag (0.75 pu), swell (1.15 pu), outage.
* **Grid:** frequency drift, background voltage THD, measurement noise.
* **Wiring faults:** loose neutral (the star point shifts towards the loaded phases), CT clamped backwards.
* **Board:** power-cycle the chip. It forgets its configuration and the firmware must re-initialise it.
* **Scenarios:** one-click presets such as evening peak, brown-out, losing phase Y, loose neutral and solar export.

The panel shows the **ground truth** (what really flows in the wires, with true import/export energy counters) next to relay and GPIO state. Compare it with the web app to check the measurement chain end to end.

## Settings (environment)

| Variable | Default | Meaning |
|---|---|---|
| `SIM_TICK_HZ` | `10` | Physics/register update rate |
| `SIM_RELAY_PINS` | `R:17,Y:27,B:22` | BCM pin per phase relay (must match the firmware's `RELAY_PINS`) |
| `SIM_RELAY_ACTIVE_HIGH` | `true` | Relay closes when the pin is HIGH |
