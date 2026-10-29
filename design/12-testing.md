# 12. Testing

The test plan: levels and tools, test environment, the suites for each TST- requirement, end-to-end tests for every real-time scenario, tests for design decisions, non-functional checks, and the traceability matrix. Requirements: [08 §8.3](../requirements/08-non-functional-and-testing.md) (TST-10 – TST-16), TST-01 – TST-04 (simulator, [11](11-simulator.md)), [real-time-scenario.md](../requirements/real-time-scenario.md).

Decisions referenced: DD89–DD94 in [decisions.md](decisions.md).

## 12.1 Levels and tools (DD89)

| Level | Scope | Tools |
|---|---|---|
| Unit | Pure functions and classes: config resolution, validation, contract validation, QC, conversions, features, probability derivation, alert state machine, subject formatting | `pytest`, `hypothesis` (property-based) |
| Integration | One process against **real** PostgreSQL + TimescaleDB, Mosquitto and Mailpit (DD90) | `pytest` with a test database, `paho-mqtt` |
| API | All endpoints, roles, errors, WebSocket | `pytest` + `httpx`, FastAPI test client, `websockets` |
| End-to-end | Simulator → MQTT → ingest → forecast → alerts → dashboard and Mailpit | `scripts/test.ps1 -E2E`, simulator scenarios, Playwright, Mailpit API |
| Frontend | Components, event router, live store, leader election | Vitest + React Testing Library; Playwright for multi-tab |
| Model | Back-tests, metrics, feature contract, registry | `pytest` in `ml/` and `backend/tests/ml` |
| Contract | MQTT schema (simulator copy vs backend validator), OpenAPI snapshot vs frontend client | `pytest`, generated client diff |
| Performance | Latency, run time, frame budget, bundle size | Custom timers, Playwright tracing, bundle visualizer |

## 12.2 Environment

| Item | Rule |
|---|---|
| Services | The same locally installed services as the demo ([01 §1.7](01-architecture.md)); tests use their own database `ews_test` (migrated from scratch per run) and a second Mosquitto on port 1884 (`test.ps1` starts `mosquitto.exe -c config/mosquitto/test.conf` with a test password/ACL file, then stops it) |
| Time (DD91) | A **fake clock** (`ews.common.clock`, [11 §11.3](11-simulator.md)) in unit and integration tests; the **demo clock** at 60–120× in end-to-end tests, so a 1-hour scenario runs in about a minute |
| Mail | Mailpit API (`GET /api/v1/messages`, search by `X-EWS-Alert-Id`) to assert subjects, recipients and threading; inbox cleared before each test |
| Models | A tiny test model set (`models/test/`) with the real feature contract, so end-to-end tests do not need the trained TFT; one optional suite runs with the real models |
| Data | Fixtures in `backend/tests/fixtures/`: example site YAML, kits, scenario expectations; golden files for formulas and email templates |
| Determinism | Fixed simulator `seed`; no test depends on wall-clock timing except the performance suite |
| Runner | `scripts/test.ps1 [-Unit] [-Integration] [-Api] [-E2E] [-Frontend] [-Perf] [-Slow]`; all suites by default except `-Perf` and `-Slow` |
| Long scenarios (DD126) | Multi-day scenarios (Scenario 3, the multi-day parts of 4) are tested in full as **fake-clock integration tests** (seconds). Their demo-clock end-to-end versions take about an hour at 120× and are marked `slow`: run before closing a milestone and before the demo |
| Batch harness (DD126) | `backend/tests/harness/` runs `ingest` pipeline functions and the alert engine in one process on the fake clock, fed by the simulator's replay generator as a library; used for the alert-volume dry run |

## 12.3 Suites per TST- requirement

### TST-10 Config resolution, validation, override scope

| Case | Expected |
|---|---|
| Resolution order for every key kind (kit → site → onboarding → region default → default) | Correct value and `source` ([04 §4.2](04-configuration.md)) |
| Property: for random sets of overrides, `resolve` equals the most specific allowed level | `hypothesis` |
| Each disallowed level from the catalogue, e.g. `timezone` on a kit | `OVERRIDE_NOT_ALLOWED` naming key and kit |
| Threshold order broken by a **site** save that is fine on its own but breaks a kit | `THRESHOLD_ORDER` for that kit ([04 §4.4](04-configuration.md)) |
| Kit outside `site_radius_km`, invalid coordinates, missing required keys, duplicate zone | Matching codes |
| YAML import: valid file; one invalid kit → nothing stored; dry run stores nothing | Atomic ([04 §4.6](04-configuration.md)) |
| Effective view vs resolver | Same values for kit/site/default keys |

### TST-11 QC, features, conversions, contract validation

| Case | Expected |
|---|---|
| Contract: every field missing, wrong type, extra field, bad topic, wrong site, unknown/disabled kit, `ts` window | Rejected with the right `reason_code` ([05 §5.2](05-data-pipeline.md)) |
| Identical and conflicting duplicates | Dropped / `conflicting_duplicate`, first kept |
| Tips → mm, sea-level pressure | Golden values (barometric formula, three elevations) |
| Heat index | NOAA reference table values within 0.3 °C |
| Range, spike (with re-anchoring after 3 readings), stuck (incl. RH ≥ 99 % exception), cross-sensor, neighbour (≥ 3 kits), external | Flags and severities as in [05 §5.4](05-data-pipeline.md) |
| DHT11 fallback | `temp_sensor = dht11`, suspicious |
| Derived features with gaps | NULL below 80 % coverage |
| Late reading (≤ 3 h) | Later derived rows recomputed; > 3 h not |
| Rolling hours ([07 §7.3](07-forecast-worker.md)) | Built from 4 buckets; proportional rain split of Open-Meteo values |
| End-labelled hourly series | 10:00–11:00 labelled 11:00 |

### TST-12 Alert engine (DD94: table-driven)

The state machine is tested from **transition tables**: each row gives the current state, the inputs (run probabilities or a reading sequence) and the expected change, so every row of [08 §8.5.3](08-alert-engine.md) and [08 §8.6.3](08-alert-engine.md) is covered.

| Area | Cases |
|---|---|
| Create / upgrade / downgrade / cancel | Upgrade on one run; downgrade after exactly 3 lower runs; a non-lower run resets the counter; cancel when nothing qualifies after 3 runs |
| Hysteresis | 0.62 → Warning; 0.50 stays Warning; 0.44 counts as lower; Watch held down to 0.20 |
| Most severe colour | Orange 72 % + Red 35 % → Red Watch, Orange shown as secondary |
| Far events | Episode > 48 h ahead needs 2 runs (Scenario 3: 09:00 not issued, 09:15 issued) |
| Window ended | Cleared with "Forecast period ended" |
| Live minimum duration | Median over 10 min: isolated gusts ignored; one lull does not reset; coverage < 80 % → no decision |
| Squall (D31) | Mean-wind rise ≥ 30 and mean ≥ 40 for 60 s → immediate Orange Live with `trigger = squall`; then Red after 10 min median gust ≥ 62. A single 45 km/h gust in a calm minute → **no** squall |
| Today windows (D30) | Heatwave Warning for Friday continues after midnight (D0 window); highest 30-minute median meeting the rule → P = 1; a single hot minute does not (DD124). Rain day D0 with 80 mm measured at 02:00 UTC → P = 1, no cancel |
| Window moved (DD101) | Same level, start moves 14:00 → 20:00 → `updated` email; a 1 h move → silent |
| Live heatwave per day (D35) | Evening cool-down → alert stays open; a whole local day below the rule → cleared at the end of that day |
| Take-over scope (DD103) | Live heat today does not take over a forecast alert for tomorrow |
| Live heatwave blocks forecast heat alerts (DD114) | While an Orange Live heatwave is open, an Orange forecast for tomorrow creates no alert; a Red forecast does; after the Live alert clears, forecast alerts resume |
| Rain day D0 source (DD115) | With a `rain_24h` classifier active, D0 still uses measured + TFT; D1–D2 use the classifier (`forecast_run_model`) |
| Sticky audience, end while suppressed (D36) | Recipient with `min_level = orange` gets the downgrade to yellow and the cancel; a suppressed alert's cancel is emailed |
| Normal offset (D33) | Fewer than 28 days → offset 0, "normal not yet calibrated"; afterwards normal + median offset used |
| Clear-down | Timer starts and resets correctly; downgrade to the highest holding level; clear when none |
| Offline | Unknown, not false; cleared "no data" after 60 min |
| Take-over (D29) | Live opens → forecast alert `taken_over`, no email for it, Live email mentions it; higher-colour forecast stays |
| Combination (AL-14) | Median (lower middle for 2 kits), worst, majority, two-kit agreement; per-kit thresholds applied before combining |
| Suppression | Silences emails; colour rise overrides; same-colour Watch → Warning stays suppressed; expiry sends current state once |
| Re-acknowledgement (DD36) | Upgrade clears "acknowledged"; downgrade keeps it |
| Cooldown (DD68) | Escalations immediate; downgrade within 60 min delayed and superseded by a newer change |
| Threshold change (AL-16) | `threshold_changed` on affected open alerts only |
| Restart | Kill `alerts` mid-stream; on restart no duplicate changes or emails (markers, unique keys) |

### TST-13 Concurrency

| Case | Expected |
|---|---|
| Two config saves on the same `base_version` in parallel (20 repetitions) | Exactly one succeeds, the other `409 CONFIG_VERSION_CONFLICT` |
| Ten parallel acknowledgements of one alert | Exactly one row; nine `409 ALREADY_ACKNOWLEDGED` naming the winner |
| Command arriving while a forecast run is being evaluated | Applied in order; no lost update |
| Two mailer instances (accidental double start) | `SKIP LOCKED` → no double sends |
| `ingest` stopped while 2 000 readings are published (DD109) | All 2 000 stored after restart (broker queue not limited) |
| Two operator suppress commands at once | One applied, one rejected ("already suppressed") |

### TST-14 End-to-end

Simulator → MQTT → ingest → forecast → alert → dashboard and email, on the demo clock, with assertions on the database, the WebSocket stream (Playwright page) and Mailpit (§12.4).

### TST-15 Model back-tests

| Case | Expected |
|---|---|
| Lead-time computation on synthetic series with a known onset | Exact lead time |
| Back-test job on a small fixture history | Top-10 events per hazard found; `backtest_result` rows; report renders |
| Real models (optional suite) | Metrics file present per model; held-out locations reported; registry checksums valid |
| Feature contract | A model with a mismatching feature list is refused at load, fallback used, admin warning raised |
| Probability calibration | Calibrated outputs monotonic and within [0, 1] |

### TST-16 Permissions (DD93)

Generated from the OpenAPI schema and the role matrix ([02 §2.8](02-api.md)), so a new endpoint is tested automatically:

| Case | Expected |
|---|---|
| Every non-public endpoint without a session | `401` |
| Every admin endpoint with an operator session | `403 FORBIDDEN` |
| Every write without `X-CSRF-Token` | `403 CSRF_FAILED` |
| Deactivated user: old session, login, WebSocket | `401`, `403 ACCOUNT_DEACTIVATED`, close `4403` |
| WebSocket without session or wrong `Origin` | Refused |
| Operator WebSocket stream | Never contains admin-only fields (`changed_keys`, `failed_emails`) |
| Lockout | 5 failed logins → `423`; unlocked after 15 min (fake clock) |
| Last admin, own role (WEB-05) | `409 LAST_ADMIN`, `403 CANNOT_CHANGE_OWN_ROLE` |
| Invite and reset tokens | Expired, reused, replaced → `410` |

## 12.4 Scenario tests (DD92)

Each scenario of [real-time-scenario.md](../requirements/real-time-scenario.md) is an automated end-to-end test: a simulator scenario file plus an expectation file listing what must happen and when (in simulated time).

| Scenario | Simulator | Key assertions |
|---|---|---|
| 1 Normal minute | `normal.yaml` | Raw + clean + derived rows; `reading.new` on the page ≤ 1 s after receipt (real-clock variant); forecast run at the next slot |
| 2 Squall | `squall.yaml` with forecast probabilities injected from a fixture run | Orange Watch created → upgraded to Warning on one run; acknowledgement race (two browser contexts, one wins); squall Live at onset with `trigger = squall`; Warning `taken_over`; Red after 10 min; clear-down 30 min then cleared; emails: subjects exactly as in [09 §9.3](09-notifications.md), one thread per alert, no repeat within cooldown |
| 3 Heatwave | `heatwave.yaml` at 120× with fixture runs | Far event not issued on first run, issued on the second; Orange Watch → Orange Warning; trend shown; Warning continues past midnight into Friday (D0); Orange Live takes over; stays open Friday night; cleared at the end of Saturday (D35) |
| 4 Rain burst | `rain_burst.yaml` | Yellow Watch (rain 24 h); 100 tips/h → Orange Live intensity; 24 h total → Yellow Live; worst-kit rule with 2 kits |
| 5 Kit offline | `kit_offline.yaml` (`disconnect` fault) | Offline within 2 s via last will; outage 10:02–10:40 recorded; maintenance email once; no live alerts during outage; `silent` variant → offline after 5 min |
| 6 Faulty sensor | `faulty_sensor.yaml` | Cross-sensor suspicious; 6 °C spike faulty and excluded from live alerts and aggregates; DHT fallback variant; maintenance notice |
| 7 Suppression | `suppression.yaml` + API calls | Suppressed Yellow Watch sends nothing; Red run overrides, emails; audit entry with reason |
| 8 Threshold change | API calls | Second save on version 7 → 409 message; next run uses 45 km/h; `threshold_changed` in history; `config.changed` on the WebSocket |
| 9 Demo | `demo.yaml` | Runs end to end without errors; Mailpit shows the squall email; offline shown within seconds; model-reports page loads |

## 12.5 Further design-decision tests

| Decision | Test |
|---|---|
| DD29 one socket per browser | Playwright with three tabs: one WebSocket; one sound; leader tab closed → another takes over and all tabs resync |
| DD30 immutable runs | Second request for a run is served from cache (no network) |
| DD31 columnar series | Same values as row format; gaps as `null` |
| DD32 frame-coalesced rendering | Replay at 60× with 5 kits: no frame > 50 ms, memory flat over 30 min |
| DD34 degraded mode | Block WebSocket in Playwright → polling indicator, alerts still update |
| DD42 strict contract | Simulator `unknown_field` fault rejected |
| DD57 gaps | 4 h outage → `degraded` run with filled hours; 25 h without data → `skipped` |
| DD59 threshold fallback | Kit with `wind_orange_kmh = 35` → TFT-derived probability recorded in `forecast_run_model` |
| DD72 threading | All emails of one alert share `References` |
| DD73 superseded | Stop mailer, create and upgrade an alert, start mailer → only the upgrade is sent |
| DD82 demo clock | Sessions and rate limits unaffected by demo time |
| DD117 weather vs machine time | Demo at 60× for 5 minutes: forecast runs complete (none killed by the timeout), no process shown down, no WebSocket reconnects, heartbeats every 15 real seconds |
| DD118 Open-Meteo pacing | Fake server returning `429` with `Retry-After` during onboarding → waits, resumes, completes |
| DD119 whole-hour windows | Episode 14:15–20:15 → shown and emailed as 14:00–21:00; successive runs moving it by 15 min send no `updated` |
| DD120 heatwave no data | Kit offline 01:00–03:00 during a Live heatwave → alert kept; a whole day without data → cleared "no data" |
| DD121 normal offset | Non-zero offset → heatwave probability source `tft` in `forecast_run_model` |
| DD125 simulator guard | `start.ps1 -Simulator squall` without `-Demo` → refused; real-clock stand-in with a non-local `SMTP_HOST` → refused; simulator `--scenario` with `clock.mode: real` → refused |
| DD122 dev origins | With `-Dev`, socket from `localhost:5173` accepted; without it, refused |
| DD107 demo policies | Demo database has no retention/compression jobs; after 10 minutes of demo no chunk was dropped or compressed |
| DD108, DD116 demo snapshot | `-Demo -Reset` restores the snapshot; the simulator continues from `sim_time` in `demo-snapshot.json`; the first forecast run completes with all kits `ok`; a snapshot from an older migration shows the rebuild warning |
| DD110 catalogue sync | Fresh database: `ingest` and `alerts` started first see the full catalogue; a removed key is `deprecated`, old versions still load |
| Contract copy | `simulator/contract.schema.json` accepts exactly what the backend validator accepts (generated message corpus) |
| OpenAPI | Frontend client regenerated from the live schema has no diff |

## 12.6 Non-functional checks

| Requirement | Check | Pass |
|---|---|---|
| NFR-01 | Real clock, 5 kits: time from MQTT publish to WebSocket message in the browser, 1 000 readings | p95 ≤ 1 s, max ≤ 5 s |
| NFR-02, ML-08 | 100 forecast runs with 5 kits on the demo laptop | p95 ≤ 60 s |
| NFR-03 | Burst of 200 requests/min from one user; 15 logins/min from one IP | `429` with `Retry-After` |
| NFR-04 | Stop and start `api` during a session | Reconnects with backoff, freshness labels, state reloaded |
| NFR-05 | Fresh Windows machine following the setup guide | `start.ps1` brings everything up; `check-setup.ps1` passes |
| NFR-06 | Readings and alerts around midnight IST and around the 03:00 UTC rain-day boundary | Correct day assignment and display |
| NFR-07 | Add a kit and a new installation for a second site through configuration only | No code changes |
| NFR-08 | Repository scan | No secrets committed (`.env`, password files ignored) |
| Frontend budgets ([13 §13.1](13-frontend-performance.md)) | Bundle visualizer in the build | Login ≤ 90 KB, dashboard ≤ 350 KB gzip |
| Alert volume (DD112, DD126, AL-04 – AL-06) | Batch harness: a whole real year for the demo location (ERA5 → minute data, [11 §11.4.1](11-simulator.md)) through the live path, and two months (one wet, one hot) through the forecast path at the real 15-minute cadence; count alerts and emails per week, hazard and level | Within targets agreed with the owner before the demo (e.g. Yellow wind at most a few times a month); counts reported as evidence of false-alarm control |

## 12.7 Coverage targets

| Area | Target |
|---|---|
| `ews.common` (config, clock, events), `ingest`, `alerts` | ≥ 85 % lines; every row of the transition tables |
| `api` | Every endpoint in the role matrix; ≥ 80 % lines |
| `mailer` | Every template × change kind golden file |
| `worker`, `ml` | Feature builder, probability derivation, registry loading ≥ 80 %; training notebooks are not unit-tested (their outputs are) |
| Frontend | Event router, live store, leader election, `LevelBadge`, forms with validation |

## 12.8 Traceability

| Requirement group | Tests |
|---|---|
| HW-07 – HW-12 | §12.3 TST-11 contract; Scenario 5 |
| DP-01 – DP-13 | TST-11; Scenarios 1, 5 |
| DP-20 – DP-26 | TST-11; Scenario 6 |
| CFG-01 – CFG-07 | TST-10, TST-13; Scenario 8 |
| ML-01 – ML-10 | TST-15; DD57/DD59 tests; NFR-02 check |
| AL-01 – AL-17 | TST-12; Scenarios 2, 3, 4, 7, 8 |
| WEB-01 – WEB-08 | TST-16; API suite |
| WEB-20 – WEB-26 | TST-13, TST-16; Scenario 2 acknowledgement race |
| WEB-40 – WEB-46 | Mailer golden files; Scenarios 2, 4, 5, 7 via Mailpit |
| NFR-01 – NFR-08 | §12.6 |
| TST-01 – TST-04 | Simulator self-tests (`python -m simulator validate`), Scenarios 3, 5, multi-kit front |
| D26 – D29 | Single-site topic check; colour rules in TST-12; two-stage models in TST-15; take-over in TST-12 and Scenario 2 |
