# Open bugs and feature backlog

Everything from the code review that has been fixed is removed from this list. Each changed module's docstring describes what it fixed, and `tests/` guards the fixes. What remains: open bugs, known limitations, and a menu of features to choose from.

Effort: **S** ≈ 1 day, **M** ≈ 2–4 days, **L** ≈ 1–2 weeks.

---

## Open bugs

| ID | Bug | Impact | Suggested fix | Effort |
|---|---|---|---|---|
| B1 | `ADE9000.spi_burst_read_resampled_wfb` calls `spi_transfer16`, which doesn't exist | Waveform capture crashes if called (unused today) | One `xfer2` per burst with chip-select held throughout; emulate the waveform buffer in the virtual chip | S |
| B2 | A new owner of a resold meter sees the previous owner's readings and relay history, including usernames | Privacy leak between households | Scope user queries to data after the owner's `claimed_at` | S |
| B3 | If the Pi boots with an empty local DB and the server is unreachable, the energy counter restarts at 0 | Displayed cumulative kWh drops (consumption analytics are unaffected: they sum positive steps) | Retry the remote restore before accepting a 0 baseline; persist the counter in a small separate file | S |
| B4 | The Pi has no real-time clock. Before NTP syncs at boot, readings get a wrong but plausible timestamp, and the server accepts anything up to 400 days old | Data filed under the wrong day | Wait for NTP sync (`timedatectl`) before sampling | S |
| B5 | Rows the server rejects are marked synced and dropped; only the server logs them | Rare, silent loss of malformed rows | Keep rejected rows in a local dead-letter table; show the count on the device | S |
| B6 | Power-failure events stay on the Pi | The app can't show outages | Sync `power_events` like readings; add an events endpoint and app view | S |
| B7 | The touchscreen GUI places widgets at fixed pixel positions for a 2000×1010 screen | Layout breaks on other screen sizes | Grid/pack layout with relative sizing | M |
| B8 | The web app loads Chart.js from a CDN | No charts on an offline LAN | Vendor `chart.js` into `src/WebApp` | S |

## Known limitations and tech debt

| Area | Limitation | Plan |
|---|---|---|
| Storage | The InfluxDB backend is written but has never been run (Docker wasn't available) | Run `scripts/e2e_check.py` against `deploy/docker-compose.yml` before the cloud move |
| Latency | The cloud sees readings one sync batch (10 s) later | Feature 2 (live lane) or feature 14 (MQTT) |
| Scale | Device WebSocket connections live in one server process | Shared broker (Redis pub/sub or MQTT) before running more than one worker |
| Retention | The server keeps 1 Hz data forever; month queries scan raw rows | Hourly and daily rollups plus a retention policy |
| Auth | No rate limiting on login or sign-up; the web app keeps its token in `localStorage`; no refresh tokens or password reset | Rate limiter; short-lived token plus refresh token; reset flow |
| Transport | Device keys travel in request headers, which is safe only over HTTPS | Enforce HTTPS/WSS in the cloud; mTLS device certificates (feature 13) |
| Operations | No systemd units on the Pi, so a crashed process stays down; logs only go to stdout | Unit files with `Restart=always` and a watchdog; rotated log files |
| Client | The Flutter source was lost; the web app is the reference client | Rewrite against the current API (`src/Application/README.md`) |
| Tests | No automated tests for sync backoff, relay reconnects or the InfluxDB backend | Cover them in hardware-in-the-loop CI (feature 11) |

**Outside the code:** the old QR encryption key (`QRCodePage.py`) and the Railway deployment URLs are in git history. Rotate any secrets of that deployment if it still exists.

---

## Features to choose from

| # | Feature | Area | Effort | Do first |
|---|---|---|---|---|
| 1 | Billing-grade energy from the chip's own accumulators | Metering | M | – |
| 2 | Sync that loses nothing, plus a live lane | Reliability | M | – |
| 3 | Power-quality event engine | Metering | M | – |
| 4 | Fail-safe switching with closed-loop verification | Control | M | – |
| 5 | 3-phase load-balancing advisor and bill forecast | Product | L | 1, 6 |
| 6 | Appliance detection from power signatures | Product / ML | L | – |
| 7 | Waveform capture and harmonic spectrum | Metering / DSP | L | B1 |
| 8 | Max-demand monitoring and automatic load shedding | Control | M | 4 |
| 9 | Schedules and automation rules | Control | M | 4 |
| 10 | Consumption anomaly detection | ML | M | – |
| 11 | Hardware-in-the-loop CI | Engineering | S | – |
| 12 | Local-first control over the LAN | Reliability | M | 4 |
| 13 | Device certificates and signed OTA updates | Security / Ops | L | – |
| 14 | MQTT transport with device shadow | Platform | L | 2, 4 |
| 15 | Fleet dashboard and device health | Platform | M | – |
| 16 | Alerts: push, Telegram, email | Product | S | 3 or 8 |
| 17 | Tamper detection | Metering / Security | M | 3 |
| 18 | Monthly report and data export | Product | S | – |
| 19 | Observability: metrics and dashboards | Operations | S | – |
| 20 | Household roles and sharing | Product / Security | M | – |

**A strong interview set:** 1 + 3 + 4 + 11. That covers hardware depth, safety under an unreliable network, and engineering rigour, and each is demoable on the virtual board. Add 5 if you want a product story.

### Metering and power quality

**1. Billing-grade energy from the chip's own accumulators**
- Read the ADE9000's `xWATTHR` registers each second with reset-on-read, instead of integrating power in Python. The chip integrates at its internal sample rate, so a stalled Pi loses no energy.
- Store per-second deltas with a sequence number and split import from export. Totals are a server-side sum, so restores and resets become trivial.
- Prove accuracy against the virtual board's ground-truth counters (class 1 = ±1%). The virtual chip already emulates reset-on-read and 32-bit wrap.

**3. Power-quality event engine**
- Rules with hysteresis and minimum duration classify sags (0.1–0.9 pu), swells (1.1–1.8 pu) and interruptions, plus voltage and current unbalance.
- Detect a loose neutral (phase voltages diverge while neutral current changes) and a reversed CT (sustained negative power on one phase).
- Events sync to the server and show in the app. Every case already has a scenario button on the virtual board.

**7. Waveform capture and harmonic spectrum**
- Capture the ADE9000 waveform buffer around an event or on demand, run an FFT on the Pi, and show harmonics 1–25 per phase next to the raw waveform.
- Needs B1 fixed and waveform-buffer emulation in the virtual chip, built from each appliance's harmonic profile.

**17. Tamper detection**
- Log the events a utility meter logs: reversed CT, missing neutral (measured neutral current ≠ phasor sum), bypass (phase currents and neutral disagree), chip power cycles, and an enclosure-open switch on a GPIO.
- Tamper log is synced, timestamped and can't be cleared from the device.

### Control

**4. Fail-safe switching with closed-loop verification**
- A device shadow keeps desired and reported state apart; the app shows pending, then confirmed or failed.
- After switching a phase off, the meter checks with its own sensor that the current fell below about 0.05 A within 500 ms. Otherwise it reports a welded relay. (Add a welded-relay fault to the virtual board to test this.)
- Local interlocks work without the cloud: a 3-minute minimum off-time protects compressors, ON is refused during a sag or swell, and an overcurrent trip runs on the device.

**8. Max-demand monitoring and automatic load shedding**
- Compute the 15- or 30-minute rolling average demand, the way demand charges are billed, and warn at 90% of the sanctioned load.
- Optionally shed the lowest-priority phase automatically, with hysteresis and an automatic restore.

**9. Schedules and automation rules**
- Relay schedules and rules such as "if phase B is above 3 kW for 10 minutes, turn it off". Rules run on the device, so they keep working offline.
- Rules are versioned and checked for conflicts, with time-of-day tariff hints such as "running the geyser at 6 am saves ₹X a month".

### Product and insight

**5. 3-phase load-balancing advisor and bill forecast**
- Measure unbalance % and neutral current, find movable loads (using feature 6), and simulate moving each one: "move the 1.5 kW evening load from Y to B: unbalance 38% → 9%".
- Forecast the month's units and cost from the daily profile and the user's slab tariff, and warn before a slab is crossed.

**6. Appliance detection from power signatures**
- Detect step changes in each phase's active and reactive power and THD, cluster the steps into appliance signatures, and draw an "AC on 19:02–21:40" timeline.
- The virtual board knows which appliance is really on, so you can report precision and recall instead of screenshots.

**10. Consumption anomaly detection**
- Build an hour-of-week baseline (median and spread) from history and flag unusual use: "3× normal at 3 am", or a fridge running much longer than usual (an early sign of a fault).

**16. Alerts**
- Notify on outages, power-quality events, relay changes and high usage by Telegram bot, email or web push, with de-duplication, rate limits and quiet hours.

**18. Monthly report and data export**
- Monthly PDF or CSV: consumption by day and phase, peak demand, a power-quality summary and the estimated bill. Optionally emailed on the 1st.

**20. Household roles and sharing**
- Owner, member and viewer roles with invite links. Only owners and members can switch relays, and the audit log shows who did it.

### Platform and engineering

**11. Hardware-in-the-loop CI**
- A GitHub Actions workflow that runs the unit tests, boots the server, the virtual board and the firmware headless, then runs `e2e_check.py` plus scenario tests (outage → failure logged, solar → negative power).
- Every pull request proves the whole system still works end to end. Cheap to build and impressive to show.

**12. Local-first control over the LAN**
- The Pi serves a small authenticated API on the local network. The app falls back to it when the cloud is unreachable, so relays and live readings keep working during an internet outage.

**13. Device certificates and signed OTA updates**
- Per-device X.509 certificates (mTLS) replace shared API keys.
- Signed release bundles install with an A/B scheme, a post-update health check and automatic rollback.

**14. MQTT transport with device shadow**
- Replace HTTP sync and the WebSocket with MQTT: QoS 1 telemetry, a retained shadow topic for the relays, and a last-will message for online status.
- This also removes the single-worker limit on the server. A good trade-off discussion versus the current design.

**15. Fleet dashboard and device health**
- Installer or utility view across many meters: last seen, sync backlog, firmware version, chip temperature, error counts, with drill-down.

**19. Observability**
- A `/metrics` endpoint (ingest rate, rejected rows, meters online, command latency) and device metrics (sync backlog, sampling-loop overruns), with a Grafana dashboard kept in the repo.
