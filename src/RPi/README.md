# ⚡ Voltix meter firmware (Raspberry Pi)

The Pi-side code of the Voltix meter. It reads the ADE9000, buffers readings locally, syncs them to the server, controls the relays, logs power failures and drives the touchscreen.

The same code runs on the real board (`VOLTIX_HAL=hardware`) and against the virtual board in `src/VirtualDevice` (`VOLTIX_HAL=virtual`).

---

## Processes

| Script | Role |
|---|---|
| `api.py` | Sampler: reads the ADE9000 every second, integrates energy with measured dt, stores one transaction per sample, publishes live voltages, re-initialises the chip if it loses its configuration |
| `sync.py` | Two lanes. **Durable:** every reading, oldest-first in batches, marked synced only after the server commits, backs off on failure, rejected rows kept in `rejected_data`, outage events uploaded too. **Live:** the newest sample every second, best effort, never stale, never blocks the durable lane |
| `relay.py` + `relay_safety.py` | Authenticated WebSocket to the server; fail-safe switching enforced on the meter: OFF verified by measured current (welded-contact detection), minimum off-time, anti-chatter, no ON into a bad supply, local overcurrent trip; state persisted; reconnects forever |
| `failure_log.py` | Logs per-phase supply loss (debounced, ignores stale data) |
| `app.py` | Touchscreen GUI; loads every page in `pages/` (files starting with `_` are skipped) |
| `claim.py` | Prints a fresh one-time sign-up code and link |
| `hw_selftest.py` | Bring-up check: initialises the ADE9000 and prints one reading per phase (real or virtual hardware) |
| `auto_off.py` | Turns the display off when idle (real Pi only) |

Supporting modules: `config.py` (all settings), `db.py` (local SQLite), `hal/` (real or virtual SPI/GPIO), `ADE9000*.py` (driver, register map, calibration), `helpers.py`, `fileutil.py`.

---

## Configuration

Every process reads `config.py`, which loads the environment and `device.env`. Create `device.env` by provisioning the device on the server:

```bash
cd src/Server
python manage.py provision-device --device-id meter-001 --env-out ../RPi/device.env \
    --server-url https://<your-server> --hal hardware
```

| Variable | Default | Meaning |
|---|---|---|
| `DEVICE_ID`, `DEVICE_KEY`, `CLAIM_KEY` | from provisioning | Device identity. Keep secret; never commit |
| `SERVER_URL` | `http://127.0.0.1:8000` | Server base URL (`WS_URL` is derived) |
| `VOLTIX_HAL` | `virtual` | `hardware` on the Pi |
| `SIM_URL` | `http://127.0.0.1:9000` | Virtual board (virtual HAL only) |
| `DATA_DIR` | `src/RPi/data` | Local DB, live data, relay state |
| `RELAY_PINS` | `R:17,Y:27,B:22` | BCM pin per phase |
| `RELAY_ACTIVE_HIGH` | `true` | Relay polarity |
| `SAMPLE_INTERVAL_S`, `SYNC_INTERVAL_S`, `SYNC_BATCH_SIZE`, `RETENTION_DAYS` | `1`, `10`, `500`, `3` | Timing and retention |
| `GUI_GEOMETRY`, `GUI_FULLSCREEN` | `2000x1010`, `false` | Touchscreen window |
| `LIVE_ENABLED`, `LIVE_INTERVAL_S` | `true`, `1` | Live lane on/off and push interval |
| `MIN_OFF_TIME_S`, `MAX_SWITCHES_PER_WINDOW`, `SWITCH_WINDOW_S` | `180`, `6`, `600` | Compressor protection and anti-chatter |
| `TRIP_CURRENT_A`, `TRIP_DELAY_S` | `32`, `2` | Local overcurrent trip |
| `SUPPLY_MIN_V`, `SUPPLY_MAX_V` | `195`, `253` | No switching ON outside this supply range |
| `VERIFY_OFF_CURRENT_A`, `VERIFY_TIMEOUT_S` | `0.05`, `3` | Closed-loop check after switching OFF |
| `CLOCK_SYNC_TIMEOUT_S` | `300` | Max wait for NTP at boot before sampling with a plausible clock |
| `ENERGY_RESTORE_RETRY_S` | `120` | How long to retry the server for the energy counter when nothing is stored locally |

---

## Local database (`data/power_meter_data.db`, WAL mode)

| Table | Contents |
|---|---|
| `power_data` | One row per phase (+ Neutral) per second; energy as three counters: `energy_kwh` (chip accumulators, billing), `energy_sw_kwh` (software, cross-check), `export_kwh`; `sync` flag; indexed on `(phase, id)`, `(sync, id)`, `timestamp`. Synced rows older than `RETENTION_DAYS` are pruned; unsynced rows never are |
| `daily_energy` | kWh per day and phase, kept forever (History page) |
| `power_events` | Last 5 supply failures per phase |
| `meter_state` | Cross-process requests, e.g. the GUI's energy reset |

---

## Running

Locally, everything starts with `python scripts/run_local.py` from the repo root.

On the Pi:

```bash
pip install -r requirements.txt
python3 api.py & python3 sync.py & python3 relay.py & python3 failure_log.py & python3 app.py
```
