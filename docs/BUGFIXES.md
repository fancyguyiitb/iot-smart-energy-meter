# Bug fixes

Status of every bug from the code review, plus the ones found while fixing them (N1–N8).
IDs match the review document. "e2e" = `scripts/e2e_check.py` against the running stack;
test files are under `tests/`.

## Critical: data loss, security, safety

| ID | Bug | Fix | Where | Verified by |
|---|---|---|---|---|
| C1 | Device sent IST time with a bogus `Z` (`…+05:30Z`); server's `strptime` always failed and used `now()`, so each sync batch collapsed onto one timestamp (~90% of readings overwritten) | Device sends UTC ISO-8601; server validates with a timezone-aware model and rejects bad rows individually | `RPi/db.py` `to_utc_iso`, `Server/utils/models.py` `Reading` | `test_unsynced_rows_leave_as_utc`, `test_batch_keeps_every_timestamp`, `test_bad_rows_are_rejected_individually`, e2e |
| C2 | InfluxDB `write_api()` defaults to batching: 201 returned before (and even if not) written | `SYNCHRONOUS` writes; storage errors return 503 so the device retries | `Server/storage/influx_store.py`, `api/routes.py` | code review (Influx backend not run locally) |
| C3 | `/api/fetch-all` dumped the whole bucket incl. plaintext passwords, unauthenticated | Endpoint removed; users moved out of the metrics store | `Server/api/routes.py` | `test_fetch_all_is_gone`, e2e |
| C4 | No route checked auth: anyone could switch off a supply or write fake data | User JWT on every user route, device key on device routes, ownership check per device | `Server/api/dependencies.py` | `test_user_endpoints_require_login`, `test_ingest_requires_valid_device_key`, e2e |
| C5 | Anyone could open the device WebSocket as "random12" | Per-device key checked on the handshake (rejected before accept) | `Server/api/websockets.py`, `RPi/relay.py` | `test_forged_device_websocket_is_rejected`, e2e |
| C6 | Sign-up QR key hard-coded in the public repo; token never expired; re-registering took over a device | Per-device claim key from provisioning, 10-min TTL, one-time nonce, owned meters can't be re-claimed | `RPi/claim.py`, `Server/api/auth.py`, `utils/database.py` | `test_claim_codes_expire_and_are_single_use`, `test_claim_code_is_signed_with_device_key`, e2e |
| C7 | Plaintext passwords, sent as URL query params | PBKDF2-SHA256 (600k iterations), JSON body, timing-equalised login | `Server/utils/security.py`, `api/auth.py` | `test_passwords_are_hashed`, `test_login` |
| C8 | Row cap deleted unsynced rows; sync sent *all* unsynced rows in one request (poison pill after an outage) | Batches of 500, timeout, exponential backoff, backlog drains back-to-back; only synced rows are pruned | `RPi/sync.py`, `RPi/db.py` | `test_prune_never_deletes_unsynced_rows`, `test_batches_are_bounded_and_oldest_first`; restart picked up 12 pending rows |

> **Action needed outside the code:** the old Fernet key in `QRCodePage.py` and the Railway URLs are in git history. Treat them as burnt: rotate the server `SIGNUP_SEC_KEY` / InfluxDB token if that deployment still exists.

## High: wrong numbers or broken features

| ID | Bug | Fix | Where | Verified by |
|---|---|---|---|---|
| H1 | Root `.gitignore` `lib/` hid `src/Application/lib` (Flutter source never committed) | `/lib/` (root only) | `.gitignore` | `git check-ignore` |
| H2 | Home screen queried phases A/B/C; data is stored as R/Y/B | Query R/Y/B | `RPi/pages/HomePage.py` | GUI smoke test |
| H3 | Energy restore crashed on a healthy server (two return shapes), used a different host, no timeout | One shape, one configured `SERVER_URL`, timeout, device auth | `RPi/helpers.py`, `RPi/config.py` | restart resumed energy (log) |
| H4 | `sign_extend_32` returned the magnitude: export / reversed CT counted as consumption | Two's complement | `RPi/ADE9000API.py` | `test_sign_extension_is_twos_complement`, `test_driver_decodes_what_the_wires_carry`, `test_reversed_ct_shows_negative_power` |
| H5 | Energy integrated with a nominal 1 s dt | Measured `time.monotonic()` dt, capped after stalls | `RPi/api.py` | code review (hardware accumulators are USP 1) |
| H6 | Energy reset could not work (page skipped, flag in wrong process, restore undid it, DB deleted) | `ResetPage.py`; request/ack through the shared DB; restore uses latest not max; raw data kept | `RPi/pages/ResetPage.py`, `RPi/db.py`, `RPi/api.py` | `test_energy_reset_request_is_seen_once`, `test_last_energy_is_latest_not_max`, live check (applied in 0.6 s) |
| H7 | Failure logger imported a missing module; phase keys mismatched; no staleness check; kept 1 not 5 | Fixed import, R/Y/B end to end, 5 s staleness, 5 per phase | `RPi/failure_log.py`, `RPi/api.py` | `test_failure_log_keeps_last_five_per_phase`, live outage scenario |
| H8 | All relays on GPIO 17; heartbeat read wrong phases; no reconnect; restart toggled supply | Pin per phase, persisted state restored with `initial=`, reconnect with backoff, acked commands | `RPi/relay.py` | e2e relay round trip (board relay opens, measured current → 0 A) |
| H9 | Old socket's disconnect removed the new socket; dead sockets left on errors | Identity check on unregister, catch-all cleanup | `Server/api/services.py` | `test_old_socket_disconnect_does_not_drop_new_one` |
| H10 | Blocking DB calls inside `async def` froze the event loop | Sync routes run in the threadpool; async routes offload DB calls | `Server/api/*.py` | code review |
| H11 | Tk widgets touched from background threads | All page switching and overlays on the Tk main thread | `RPi/app.py`, `CurrentPage.py`, `PowerPage.py` | GUI smoke test |
| H12 | GUI lag: `COUNT(*)` per insert, no indexes, full-day re-reads every second | WAL, indexes, periodic pruning, incremental reads | `RPi/db.py`, `RPi/pages/EnergyPage.py`, `HistoryPage.py` | GUI smoke test |

## Medium

| ID | Bug | Fix | Where |
|---|---|---|---|
| M1 | Energy analytics = avg/min/max of a running counter | Consumption = sum of positive steps (survives resets) | `Server/analytics/helpers.py`, `storage/*` (test: `test_energy_consumption_survives_counter_reset`) |
| M2 | Cached analytics stamped with the wrong time, 404 after writing, a write per request | Computed on read, no cache | `Server/analytics/helpers.py` |
| M3 | Accounts and device keys vanished after 30 days; "delete" was a read | Relational users/devices tables | `Server/utils/database.py` |
| M4 | Flux injection through `device_id` / `phase` | Flux `params`, allow-listed fields; device comes from the token | `Server/storage/influx_store.py` |
| M5 | Token lifetime 3600 *minutes* | 60 minutes, configurable | `Server/config.py` |
| M6 | `/latest-values` never returned frequency (typo `viltage_freq`) | All fields returned | `Server/api/routes.py` |
| M7 | Relay status one step stale | Commands wait for the device's ack; status refreshes first | `Server/api/services.py`, `websockets.py` (test: `test_command_waits_for_device_ack`) |
| M8 | Live plots: local-time "today", unbounded lists, `id % 3` decimation tied to 4 rows/sample | IST day, midnight reset, time-based decimation | `RPi/pages/CurrentPage.py`, `PowerPage.py` |
| M9 | Two different DB paths | One `config.py` | `RPi/config.py` |
| M10 | Hard-coded `random12` | Provisioned per device (`manage.py provision-device`) | `Server/manage.py`, `RPi/config.py` |
| M11 | Docs vs code drift; failure page never refreshed; CORS `*` + credentials; `None` settings | History kept per day in `daily_energy`; refresh loop on show; explicit CORS origins; validated settings | `RPi/db.py`, `PowerFailurePage.py`, `Server/main.py`, `Server/config.py` |

## Found while fixing

| ID | Bug | Fix | Where |
|---|---|---|---|
| N1 | PF register not sign-extended: PF −0.99 decoded as ~31 | Sign extension | `RPi/ADE9000API.py` (test: `test_driver_decodes_what_the_wires_carry`) |
| N2 | Angle scale test `(accmode & 0x0100) >= 0` always true → 60 Hz scale on a 50 Hz grid (20% error) | `if accmode & 0x0100` | `RPi/ADE9000API.py` (test: `test_angles_use_50hz_scale`) |
| N3 | `WATTHR_B/C` shifted HI left by 32 bits (2³² too large); `WATTHR_A` not sign-extended | `signed(HI) × CAL_ENERGY_CC` | `RPi/ADE9000API.py` (test: `test_energy_register_decoding_matches_chip_accumulator`) |
| N4 | Hiding and re-showing a page started a second refresh loop (each tab switch could double DB polling) | Pending `after()` job cancelled on hide | all live pages |
| N5 | EnergyPage gap detection never fired (`prev_ts` never updated) | Updated per row | `RPi/pages/EnergyPage.py` |
| N6 | Reading right after `RUN=1` returned zeros → false power failure logged on every boot | 1 s DSP settle + 2-sample debounce in the failure logger | `RPi/api.py`, `RPi/failure_log.py` |
| N7 | `os.replace` fails on Windows while another process has the file open | Retrying atomic write | `RPi/fileutil.py` |
| N8 | Bad rows in a batch failed the whole request → sync blocked forever | Per-row validation, rejected rows reported | `Server/api/routes.py` |

## Not fixed yet

* `ADE9000.spi_burst_read_resampled_wfb` calls a method that doesn't exist (`spi_transfer16`). Unused today; the waveform buffer needs chip-select held across transfers, which the virtual SPI does not model yet.
* The Flutter app source is not in the repo (H1 lost it). `src/WebApp` is the reference client until it's rewritten.
* Time-series and relay history stay with the *device*, so a new owner after a resale can see the previous owner's history. Needs a data-ownership decision (scope queries to `claimed_at`).
* The InfluxDB backend implements the same interface but is untested locally (Docker wasn't running). Before the cloud move, start `deploy/docker-compose.yml`, set `STORAGE_BACKEND=influx` and run `scripts/e2e_check.py` against it.
* Live data reaches the cloud one sync batch later (10 s). USP 2's "live lane" addresses this.
