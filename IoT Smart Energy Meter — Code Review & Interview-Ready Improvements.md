# IoT Smart Energy Meter — Code Review & Interview-Ready Improvements

Nov 10, 2026 · @Ajinkya

## Summary

The system works end to end in a demo, but most uploaded readings are silently overwritten in the cloud, and the server is open to anyone on the internet. I found 31 bugs: 8 critical, 12 high and 11 medium.

The pipeline is ADE9000 → Raspberry Pi (Python, SQLite, Tkinter) → FastAPI on Railway → InfluxDB → Flutter app. I read every Python file in `src/RPi` and `src/Server`, plus the app config. The Flutter Dart code is not in the repo at all (H1).

The three findings to fix first:

- **About 90% of readings are lost on upload.** A timestamp format mismatch stamps every row in a sync batch with the same time, so InfluxDB keeps one point per phase per batch (C1).
- **Anyone can read every password and switch off the supply.** `/api/fetch-all` returns the `user_auth` records in plaintext, and `/remote-control` has no auth (C3, C4).
- **The Pi's home screen shows only phase B.** It queries phases A/B/C but the logger stores R/Y/B (H2).

The five improvements in the last section each grow out of one of these bugs. That gives you a clean interview story: *I found this failure, worked out why, and redesigned the subsystem so it can't happen.*

## Bugs

The bugs are ranked in three tiers. **Subtle** marks ones you won't spot by skimming: they need two files read together, or knowledge of a library default. Paths are relative to `src/`.

### Critical: data loss, security, safety

| # | Kind | Bug | Where | What goes wrong | Fix |
| --- | --- | --- | --- | --- | --- |
| C1 | Subtle | Timestamps destroyed on ingest | `RPi/db.py:138`, `Server/api/routes.py:32` | The Pi sends IST time with an offset and then appends `Z` (`…T10:00:00.123+05:30Z`). The server's `strptime("%Y-%m-%dT%H:%M:%S.%fZ")` always fails, so it falls back to `now()`. Every row in a batch gets the same timestamp, and InfluxDB overwrites points with identical tags and time. Only the last row per phase survives each \~10 s batch, and after an outage hours of data collapse into one point. | Send UTC from the Pi (`datetime.now(timezone.utc)`) and parse with `datetime.fromisoformat`. Reject bad timestamps instead of substituting `now()`. |
| C2 | Subtle | 201 returned before the write lands | `Server/utils/database.py:10` | `write_api()` defaults to **batching** mode: `write()` queues in memory and returns, and errors surface on a background thread. If InfluxDB is down, the server still returns 201, the Pi marks the rows synced, and the data is gone. | Use `write_api(write_options=SYNCHRONOUS)` and only return 201 after success. |
| C3 | Subtle | `/api/fetch-all` leaks every password | `Server/api/routes.py:157` | It has no auth and no measurement filter, so it returns 30 days of the whole bucket, including the `user_auth` uname/password fields in plaintext. | Delete the endpoint. Keep users out of the metrics bucket. |
| C4 | Obvious | No endpoint checks auth | `Server/api/websockets.py:63`, `utils/security.py:31` | `verify_token` exists but is never used. Anyone can POST `{"device_id":"random12","phase":"R","command":"off"}` to `/remote-control` and cut a consumer's supply, or write fake readings to `/api/write-data`. | Add `Depends(verify_token)` to every route and check that the token's `device_id` matches the request. |
| C5 | Subtle | RPi impersonation over WebSocket | `Server/api/websockets.py:28` | Any client that sends `{"type":"connect","device_id":"random12"}` replaces the real Pi in `connections`. It then receives relay commands and can report fake relay status. | Give each device its own secret or key, and authenticate the WS handshake (signed token in a header). |
| C6 | Subtle | QR sign-up key is public and tokens never expire | `RPi/pages/QRCodePage.py:24`, `Server/api/auth.py:150` | The Fernet key is committed to a public repo. The token's timestamp is discarded (`device_id, _ = msg.split("::")`), so a photo of the QR works forever. Re-registering overwrites the owner, which is a device takeover. A bad token raises `InvalidToken`, giving a 500 instead of a 400. | Rotate the key and load it from env. Use `Fernet.decrypt(token, ttl=300)` plus a one-time nonce. Require the current owner's approval to re-bind. |
| C7 | Obvious | Plaintext passwords in query strings | `Server/api/auth.py:81`, `:113` | Passwords are stored and compared as plaintext (`# FIXME`). Sign-up takes them as URL query params, so they end up in proxy and Railway access logs. | Hash with argon2 or bcrypt, compare in constant time, and take credentials in the JSON body. |
| C8 | Subtle | Offline buffering loses data | `RPi/db.py:83`, `RPi/sync.py:23`, `:39` | The 1M-row cap deletes the oldest rows whether or not they are synced. Sync POSTs **all** unsynced rows in one request with no timeout. After a long outage the payload reaches hundreds of thousands of rows and fails every 10 s forever (a poison pill), while the cap deletes the unsent data. This contradicts the Manual's "data remains stored until reconnected". | Send batches of about 500 rows with a timeout and backoff. Never prune rows where `sync = 0`. See improvement 2. |

### High: wrong numbers or broken features

| # | Kind | Bug | Where | What goes wrong | Fix |
| --- | --- | --- | --- | --- | --- |
| H1 | Subtle | The Flutter app source was never committed | `.gitignore:17` | The root `.gitignore` (the Python template) contains `lib/`, which also matches `src/Application/lib/`. The repo has no Dart code, so the app can't be built or reviewed. | Change it to `/lib/` or add `!src/Application/lib/`, then commit the app. |
| H2 | Obvious | Home screen shows only phase B | `RPi/pages/HomePage.py:53` | It filters `phase IN ('A','B','C','Neutral')`, but rows are stored as R/Y/B. R and Y always show "-", and B shows by coincidence. | Query `('R','Y','B','Neutral')`. Define the phase names once in a shared module. |
| H3 | Subtle | Energy restore crashes when the server is healthy | `RPi/helpers.py:20`, `RPi/api.py:90` | On a 200 response, `get_max_energy()` returns `{"R": 1.23}`. On failure it returns `{"R": {"energy_kwh": 0}}`. `api.py` indexes `["energy_kwh"]`, so the success path raises `TypeError`, the broad `except` swallows it, and nothing is logged. It is masked because `helpers.py` points at a different host (`edlserver-production`) from `sync.py` (`…-b9fa`), so the fallback probably always runs and the remote restore never works. There is also no request timeout, so a stalled network hangs the sampling loop. | Return one shape, use one configured base URL, and add `timeout=3`. |
| H4 | Subtle | Negative power is folded to its magnitude | `RPi/ADE9000API.py:305` | `sign_extend_32` computes `-val + 2**32`, which is \|P\|, instead of `val - 2**32`. The VAr version is correct. Export, or a CT clamped backwards, is counted as consumption, and energy can only go up. This blocks the solar integration in the README's future scope. | Fix the sign extension. Track import and export energy separately. |
| H5 | Subtle | Energy integration assumes a perfect 1 s loop | `RPi/api.py:106` | `pw * interval / 3.6e6` assumes dt = 1.0 s. The real period is 8 SPI reads, 4 SQLite inserts (each with a `COUNT(*)`), prints and `sleep(1)`, so it is always over 1 s. After an exception the loop also sleeps 2 s and accumulates nothing. The meter reads low by a systematic amount. | Measure dt with `time.monotonic()`, or better, read the chip's own `xWATTHR` accumulators (improvement 1). |
| H6 | Subtle | Energy reset doesn't work, in three ways | `RPi/app.py:120`, `RPi/pages/_Reset.py:52` | (1) The file name starts with `_`, so `load_pages` skips it. (2) `shared_flags.reset_flag` is set in the GUI process, but `api.py` runs as a separate process and never sees it. (3) Even if it did, the in-memory accumulator isn't zeroed, and on restart `max(local, remote)` restores the old value. Deleting the DB file also erases unsynced rows and the failure log, and `sleep(2)` freezes the UI. | Use a server-side "reset epoch": store an offset and never delete raw data. |
| H7 | Obvious | Failure logger can't start, and couldn't detect R or Y anyway | `RPi/failure_log.py:6`, `:105`, `:62` | `import live_data` refers to a module that doesn't exist. The code reads `VoltageRMSReg_R/Y`, but `api.py` writes `_A/_B/_C`, so R and Y default to 999 V and are never flagged, and `_B` actually holds Y-phase voltage. The comment says "keep last 5" but the query uses `LIMIT 1`. There is no staleness check, so if `api.py` dies the logger trusts the old JSON forever. | Remove the import and map phases explicitly. Write the JSON atomically (`os.replace`) with a timestamp and treat data older than 5 s as unknown. |
| H8 | Obvious | Relay control is effectively one switch | `RPi/relay.py:20`, `:74`, `:111` | Every phase maps to GPIO 17, so turning off R turns off everything. The heartbeat reports phases "A", "R", "R". Any error `break`s the loop and the process exits with no reconnect (hence the Manual's "restart relay.py"). `GPIO.setup` drives the pin LOW at start, so a restart can toggle the supply. | Give each phase its own GPIO, add a reconnect loop with backoff, and restore the last commanded state on boot (improvement 4). |
| H9 | Subtle | Device shows offline after a reconnect | `Server/api/websockets.py:56` | When the Pi reconnects, the old socket's disconnect handler runs `del connections[device_id]`, which now removes the **new** socket. Errors other than `WebSocketDisconnect` (such as bad JSON) leave a dead socket in the dict, and the next command returns 500. The in-memory dict also breaks with more than one worker. | Delete only `if connections.get(id) is websocket`, catch all exceptions, and move presence to Redis if you scale. |
| H10 | Subtle | Blocking InfluxDB calls inside `async def` | `Server/api/routes.py`, `analytics/helpers.py` | `query_api.query` is synchronous but is called from async routes, so it blocks the event loop. A slow 1-year `sort()` in `/latest-values` freezes every WebSocket, including relay commands. | Make these routes plain `def` (FastAPI runs them in a threadpool) or use `InfluxDBClientAsync`. |
| H11 | Subtle | Tkinter is called from background threads | `RPi/app.py:96`, `RPi/pages/CurrentPage.py:94`, `PowerPage.py:129` | `tkraise`, `on_show` and matplotlib `draw()` run inside `threading.Thread`, but Tk isn't thread-safe. This causes intermittent freezes and "main thread is not in main loop" crashes. Rapid taps stack several `grab_set` overlays. | Keep all Tk calls on the main thread. Do DB work in a worker and hand results back with `after()` or a queue. |
| H12 | Subtle | The real cause of the "UI lag" in the README | `RPi/db.py:84`, `RPi/pages/EnergyPage.py:157` | Every insert runs `SELECT COUNT(*)` over up to 1M rows, 4 times a second. There are no indexes on `phase` or `timestamp`. EnergyPage re-reads the whole day (about 350k rows by evening) every second on the Tk thread. There is no WAL mode, so reads and writes contend for the lock. The loading screen in the README treated the symptom. | Enable WAL, add an index on `(phase, id)`, prune hourly instead of per insert, and query incrementally with `WHERE id > last_id`. |

### Medium: correctness debt and drift

| # | Kind | Bug | Where | What goes wrong | Fix |
| --- | --- | --- | --- | --- | --- |
| M1 | Subtle | Energy analytics on a cumulative counter | `Server/analytics/helpers.py:115` | The avg/min/max of a running kWh total don't mean anything to a user. | Daily use = last − first (Flux `spread()` or `difference()`). |
| M2 | Subtle | Analytics cache stored at the wrong time | `Server/analytics/helpers.py:63`, `:88` | Points are stamped `now()`, not the target date, so analytics for day D are never found under D. The past-date power route generates, writes, then raises 404 anyway. The "today" route writes a new point on every call. | Stamp at the day's start and upsert one point per day. |
| M3 | Subtle | Accounts disappear after 30 days | `Server/api/auth.py:27`, `:96`, `:116` | Login and sign-up only scan `range(start: -30d)`, so older users and device keys can't log in. The "delete old user" query is a read (`drop(columns)`) and deletes nothing. Login merges uname/password across sign-ups in iteration order. | Move users and devices to Postgres or SQLite. Keep InfluxDB for time series only. |
| M4 | Subtle | Flux injection | `Server/api/routes.py:108`, `analytics/helpers.py:41` | `device_id` and `phase` from query params are pasted into Flux f-strings. | Validate against an allow-list, or use Flux query `params`. |
| M5 | Obvious | Tokens live 60 hours | `Server/utils/security.py:15` | `ACCESS_TOKEN_EXPIRE_MINUTES = 3600` is 60 hours; 1 hour was probably intended. | 15-minute access token plus a refresh token. |
| M6 | Obvious | Frequency is always null in `/latest-values` | `Server/api/routes.py:195`, `:216` | `voltage_freq` is never selected, and the key is misspelled `viltage_freq`. A sort over a year then `first()` is slow. | Add the field and use `last()`. |
| M7 | Subtle | Relay status is one step stale | `Server/api/websockets.py:94` | It returns the cached status, then asks the Pi for a fresh one. | Await the reply with a timeout, or push state on change (improvement 4). |
| M8 | Subtle | Live plots drift and break at midnight | `RPi/pages/CurrentPage.py:127`, `:139` | `date.today()` uses system local time but is treated as IST. Lists never reset at midnight and grow without bound. The `id % 3` decimation assumes exactly 4 rows per sample, so one partial iteration shifts the alignment and a phase vanishes from the plot. | Decimate by time bucket, use a ring buffer (`deque(maxlen=…)`), and use IST explicitly. |
| M9 | Obvious | Two different DB paths | `RPi/failure_log.py:10`, `pages/PowerFailurePage.py:8` | An absolute `/home/rpi/Desktop/…` path in some files and a relative `power_meter_data.db` in others, so which file gets used depends on the working directory. | Use one `config.py` with a path relative to `__file__`. |
| M10 | Obvious | Hard-coded `device_id = "random12"` | RPi, server and QR code (about 10 places) | Single-tenant by construction. A second meter would overwrite the first. | Provision the ID per device and read it from the JWT on the server. |
| M11 | Obvious | Docs and code disagree | `README.md`, `Manual.md`, `PowerFailurePage.py:29` | The README says local storage holds 1 day, but the code keeps 1M rows (about 2.9 days at 4 rows/s). "Predictive maintenance via harmonics" isn't implemented. `refresh_loop` is never started. CORS uses `*` with credentials. Settings allow `None`, so missing env vars crash on first use. | Fix the docs, or build the missing feature (improvement 3). |

## Improvements that become the project's USP

Each of these starts from a real bug above, so you can tell it as one arc in an interview: *symptom → root cause → redesign → measured result*. Numbers in the examples are illustrative.

### 1. Billing-grade energy from the chip's own accumulators

**Pitch:** "I stopped integrating power in Python and let the metering IC do it, then proved the error is under 1%."

- **Problem it fixes:** H3, H4, H5, H6. The 1 Hz software integrator loses energy whenever the loop overruns, folds export into import, and relies on a fragile "max(local, remote)" restore at boot.
- **Design:**
  - Configure the ADE9000's energy accumulation (`EP_CFG`, `EGY_TIME`) and read the per-phase `xWATTHR`/`xVARHR` registers each second. The chip integrates at its internal sample rate, so a stalled Pi loses no energy, only resolution.
  - Store **deltas** with a per-device monotonic `seq`, not running totals. Totals are a server-side sum, so reboots need no restore step and double-counting can't happen.
  - Split import and export by the sign of each delta. This makes the solar and net-metering future scope possible.
  - A reset becomes a server-side "epoch" marker. Raw data stays immutable, which also gives you an audit trail.
- **Proof:** Run a known resistive load (for example a 1 kW heater for 1 h) and report the % error against a reference meter. Class 1 under IEC 62053-21 means ±1%.
- **Why it lands:** It shows you know when the hardware does the job better than the software, and you have a measured accuracy figure instead of a claim.

### 2. Store-and-forward sync that loses nothing and duplicates nothing

**Pitch:** "I pulled the network cable for two hours, plugged it back in, and the cloud chart had no gaps. Row counts matched on both ends."

- **Problem it fixes:** C1, C2, C8. Timestamps get overwritten, writes are acknowledged before they land, and unsynced rows are pruned.
- **Design:**
  - Use an outbox table indexed on `(sync, seq)`. Send the oldest rows first in gzip'd batches of about 500, with a timeout and exponential backoff plus jitter.
  - The server writes synchronously and replies with the **highest committed `seq`**. The Pi marks everything up to that point as synced, like a Kafka consumer offset.
  - Delivery is at-least-once, and writes are idempotent because the InfluxDB point identity is `(device, phase, UTC time)`. A resend overwrites itself, so the net effect is exactly-once.
  - Use two lanes. A **live lane** always sends the newest sample first, so the app goes live the moment the link returns. A **backfill lane** drains history in the background.
  - Prune only rows that are synced and older than N days.
- **Trade-off to discuss:** MQTT with QoS 1 and a persistent session gives you much of this for free. Explain why you'd still keep the local outbox: the broker can't see data the Pi never sent.
- **Why it lands:** It is distributed-systems thinking (acks, idempotency, backpressure) on a $50 device, and it comes with a chaos test you can demo.

### 3. On-device power-quality event engine

**Pitch:** "The meter doesn't just show THD. It tells you your neutral is loose before an appliance burns out."

- **Problem it fixes:** H7 and M11. The failure logger can't run, and the "predictive maintenance via harmonics" in the README doesn't exist.
- **Design:**
  - A rule engine inside the sampling process with **hysteresis and minimum duration**, so a noisy reading can't flap an alarm. Each event records start, end, worst value and duration.
  - Classify events the IEEE 1159 way: sag (0.1–0.9 pu), swell (1.1–1.8 pu), interruption (below 0.1 pu).
  - Use the ADE9000's hardware dip/swell detection and half-cycle RMS (the driver already has `read_half_voltage_rms_regs`) to catch sub-second events that 1 Hz polling misses.
  - **Loose or broken neutral:** neutral current rises while phase voltages diverge, one high and one low. This is the classic way 3-phase homes lose appliances.
  - Also detect: voltage and current unbalance %, a reversed CT (sustained negative P on one phase, after the H4 fix), a rising THD trend, and frequency excursions.
  - Send a push notification to the app with a severity level and a local buzzer. Severity tones are the README's future scope #1.
- **Why it lands:** You turned a display into a diagnostic instrument, and you used domain knowledge and hardware features instead of more polling.

### 4. Fail-safe remote switching with closed-loop verification

**Pitch:** "When the app turns a phase off, the meter checks with its own current sensor that the relay actually opened."

- **Problem it fixes:** C4, C5, H8, H9, M7. Commands have no auth, every phase is on one GPIO, there is no reconnect, and status is stale.
- **Design:**
  - Use a **device shadow**: separate *desired* and *reported* state, as in AWS IoT. The app shows pending → confirmed or failed, never a guess.
  - Commands carry an ID, an expiry and a signature. The Pi rejects anything replayed or stale.
  - **Closed-loop check:** after OFF, the phase current must fall below about 0.05 A within 500 ms. If it doesn't, report "relay failed or welded". The meter verifies its own actuator.
  - Local interlocks run without the cloud: an overcurrent trip, refusing remote ON during a sag or swell (from #3), and a minimum 3-minute off-time to protect AC and fridge compressors from short-cycling.
  - Persist the last desired state and restore it on boot. Run the process under a systemd watchdog. Keep an audit log of who switched what and when.
- **Why it lands:** Safety-critical actuation over an unreliable network is a hard problem. Most student projects send a command and hope; yours confirms and verifies.

### 5. 3-phase load-balancing advisor and bill forecast

**Pitch:** "It tells you which appliance to move to which phase, and how many rupees that saves."

- **Problem it fixes:** The app shows numbers but never says what to do. Uneven loading across phases raises neutral current and losses, and can trip one phase while the others sit idle.
- **Design:**
  - Compute current unbalance % and neutral current per hour.
  - Detect appliance switching as **step changes** in per-phase P (lightweight NILM). Cluster steps by size and time of day, for example "+1.5 kW on Y, 7–9 pm, daily" is likely a geyser or AC.
  - Simulate moving each cluster to another phase and recommend the move with the biggest gain: "Move the 1.5 kW evening load from Y to B: unbalance 38% → 9%".
  - Bill forecast: month-to-date kWh plus a projection from the day-of-week profile. Price it with the user's DISCOM slab table and alert ahead of a slab crossing: "You'll cross 300 units on the 24th".
- **Why it lands:** Only a 3-phase meter can do this, so it is the clearest USP. It also shows product thinking, because it turns telemetry into a decision with a number on it.

## Order of work and talking points

Fix security and the one-line data bugs first: they take a day and change what the repo says about you. Build the features after that, in dependency order.

1. **Day 1, stop the bleeding:** delete `/fetch-all`, add auth to every route, hash passwords, and move credentials into the request body (C3, C4, C7). The Fernet key and any tokens are in git history, so **rotate** them; deleting them from the file isn't enough (C6).
2. **Day 1:** fix `.gitignore` and commit the Flutter app (H1). Without it a reviewer sees half a project.
3. **Day 2, one-liners with outsized effect:** UTC timestamps and `SYNCHRONOUS` writes (C1, C2), phase names on the Home page (H2), sign extension (H4), and the shape, host and timeout in `helpers.py` (H3). Add a pytest that round-trips a timestamp from the Pi to the server.
4. **Week 1:** improvement 2 (sync), then 1 (energy deltas). Energy deltas are only safe once delivery is reliable.
5. **Week 2:** improvement 4 (relay). It depends on the device auth from step 1.
6. **Week 3:** improvements 3 and 5. Both need correct, signed per-phase data.

**Verify C1 before you quote it:** count InfluxDB points per phase per minute. A healthy pipeline gives about 60. Expect about 6 if the overwrite is happening. Check H8's relay polarity on the hardware too.

Three stories that land well in an interview:

- **Root cause over symptom.** "The README blamed UI lag on too much data and added a loading screen. The real cause was a `COUNT(*)` over a million rows on every insert, plus full-day re-reads on the UI thread."
- **Bugs that cross system boundaries.** "Our cloud kept about 10% of what we sent and returned 201 for all of it. It took two independent bugs to do that: a timestamp format mismatch, and a client library that batches writes by default."
- **Process boundaries.** "Energy reset failed in three separate ways. The page never loaded, the flag lived in a different process, and the boot-time restore undid it."
