# ⚡ Voltix meter firmware (Raspberry Pi)

The Pi-side code of the Voltix meter. It reads the ADE9000, buffers readings locally, syncs them to the server, controls the relays, logs power failures and drives the touchscreen.

The same code runs on the real board (`VOLTIX_HAL=hardware`) and against the virtual board in `src/VirtualDevice` (`VOLTIX_HAL=virtual`).

---

## Processes

| Script | Role |
|---|---|
| `api.py` | Sampler: reads the ADE9000 every second, integrates energy with measured dt, stores one transaction per sample, publishes live voltages, re-initialises the chip if it loses its configuration |
| `sync.py` | Store-and-forward: sends unsynced rows oldest-first in batches, marks them synced only after the server commits, backs off on failure |
| `relay.py` | Authenticated WebSocket to the server; one relay per phase; acknowledged commands; state persisted and restored at boot; reconnects forever |
| `failure_log.py` | Logs per-phase supply loss (debounced, ignores stale data) |
| `app.py` | Touchscreen GUI; loads every page in `pages/` (files starting with `_` are skipped) |
| `claim.py` | Prints a fresh one-time sign-up code and link |
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

---

## Local database (`data/power_meter_data.db`, WAL mode)

| Table | Contents |
|---|---|
| `power_data` | One row per phase (+ Neutral) per second; `sync` flag; indexed on `(phase, id)`, `(sync, id)`, `timestamp`. Synced rows older than `RETENTION_DAYS` are pruned; unsynced rows never are |
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
