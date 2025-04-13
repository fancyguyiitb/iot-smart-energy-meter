# ⚡ Voltix RPi Backend

This repository contains the Raspberry Pi-side code for the Voltix smart energy meter. It collects, displays, stores, and syncs energy data from the ADE9000 IC and communicates with a remote server.

---

## 🧠 Overview

- `app.py` — Loads and displays GUI pages from `/pages`
- `api.py` — Reads data from ADE9000 and writes to local SQLite DB via `db.py`
- `sync.py` — Syncs unsynced data to server every 10 seconds
- `relay.py` — Maintains a WebSocket connection with server for remote relay control
- `failure_flags.json`, `failure_log.py` — Logs and monitors device failure events
- `ADE9000*` files — Interface and calibration for ADE9000 IC
- `pages/` — GUI pages for power, current, energy, frequency, QR, etc.
- `sprint.py` — Debug helper (can be ignored)

---

## 🗄️ Local Database Schema (`power_data`)

```sql
CREATE TABLE IF NOT EXISTS power_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase TEXT,
    voltage_rms REAL,
    current_rms REAL,
    active_power REAL,
    reactive_power REAL,
    apparent_power REAL,
    energy_kwh REAL,
    voltage_thd REAL,
    current_thd REAL,
    power_factor REAL,
    voltage_freq REAL,
    timestamp TEXT,
    sync BOOLEAN DEFAULT 0
);
```

---

## 📦 Installation

```bash
pip install -r requirements.txt
```

---

## 🧑‍💻 Running

```bash
python3 api.py       # Start data collection and local server
python3 app.py     # Launch local GUI
python3 sync.py    # Sync data to remote server
python3 relay.py   # Run relay socket handler
python3 failure_log.py  # Monitor device failure events
```

---

## 📄 Notes

- `sprint.py` is only for internal testing/logging
- See `todos.md` for remaining tasks
