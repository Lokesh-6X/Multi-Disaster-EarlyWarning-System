# 11. Kit Simulator

A standalone program that behaves exactly like one or more real kits (same MQTT topics, contract, status messages and last will, [02 §2.4](../requirements/02-hardware.md)), with replay, scenario, fault and multi-kit modes, plus the **demo clock** that lets the whole system run faster than real time. Requirements: [08 §8.2](../requirements/08-non-functional-and-testing.md) (TST-01 – TST-04), Scenario 9 of [real-time-scenario.md](../requirements/real-time-scenario.md).

Decisions referenced: DD82–DD88 in [decisions.md](decisions.md).

## 11.1 Principles

| Principle | Rule |
|---|---|
| Separate program (DD7) | `simulator/` never imports backend code; it only speaks MQTT |
| Same contract | Every normal message is valid against the contract; only fault mode breaks it on purpose |
| Same credentials | Each simulated kit uses a kit user and ACL like a real kit ([01 §1.3.1](01-architecture.md)) |
| Same behaviour | Online retained on connect, last will `offline` retained, no buffering during outages (HW-09, HW-12) |
| Reproducible | A `seed` makes noise, gusts and rain tips identical between runs (tests, [12](12-testing.md)) |
| Never fake hazards for real people (D39, DD125) | Scenario and fault modes run only with `clock.mode: demo` (the demo database, [§11.3.1](#1131-keeping-demo-data-apart-from-real-data-dd95)); the simulator refuses them otherwise. With the real clock it is only a stand-in kit (replay/normal) before the hardware exists, and `start.ps1` allows that only while `SMTP_HOST` is local (Mailpit) |

## 11.2 Structure

```
simulator/
├── __main__.py           CLI: run, list-scenarios, validate
├── config.yaml           broker, kits, clock, default mode   (credentials in simulator/.env)
├── contract.schema.json  copy of the MQTT contract (JSON Schema), checked against the backend in tests
├── kit.py                one simulated kit: MQTT client, last will, publish loop, seq, uptime, fw
├── weather/              replay source, scenario engine, spatial model, sensor model
├── faults/               fault injectors
├── scenarios/            built-in scenario files (§11.5)
└── demo.yaml             Scenario 9 demo script
```

```yaml
# simulator/config.yaml
broker: { host: localhost, port: 1883 }
site_id: abc
clock: { mode: demo, speed: 60, start: "2024-05-25T00:00:00Z" }   # or mode: real
seed: 42
kits:
  - kit_id: KIT-01
    user_env: SIM_KIT01            # username/password from simulator/.env
    lat: 13.081
    lon: 80.271
    elevation_m: 30
    exposure: rooftop
    sampling_interval_s: 60
    fw: "1.0.0-sim"
    sensors: { dht11: true, wind_vane: false }
```

## 11.3 Clock and the demo clock (DD82)

Replaying a week at 60× only works if the **server** agrees on what time it is: otherwise accelerated readings look like future data (rejected by the timestamp window, [05 §5.2.3](05-data-pipeline.md)) or like late data (ignored by live alerts), and the 15-minute forecast schedule would not follow. The system therefore has a single clock abstraction, `ews.common.clock`, used by every backend process for "now", sleeping and scheduling.

| Clock mode | Who sets it | Behaviour |
|---|---|---|
| `real` (default) | — | Wall clock (UTC). The simulator can only run at 1×; replays are time-shifted so the first reading is "now" |
| `demo` | The simulator | Simulator publishes `{"sim_time": "2024-05-25T06:00:00Z", "speed": 60}` retained on topic `sim/clock` every real second; backend processes read it (through `ingest`'s MQTT connection, relayed to the others as a NOTIFY) and interpolate between ticks |

Demo mode is enabled only when `.env` has `EWS_CLOCK=demo`; the UI then shows "DEMO TIME 60×" ([10 §10.3](10-ui.md)) and `/system/status` reports the clock. In demo mode:

| Part | Adapted behaviour |
|---|---|
| `ingest` | `received_at` = demo time at receipt |
| `worker` | The forecast loop waits for demo-time issue times (every 15 s of real time at 60×); runs that cannot keep up are skipped (DD58). The Open-Meteo forecast fetch and the external QC check are off (no forecast exists for a past demo date), so runs use the fallback base models ([07 §7.6](07-forecast-worker.md)) |
| `alerts` | Ticks, clear-down, cooldown and suppression expiry follow demo time |
| `api` | `server_time` in `hello` and `/live` is demo time |
| Sessions, rate limits, tokens | Always wall-clock (security never runs on demo time) |
| Timeouts and health (DD117) | Always wall-clock: forecast run timeout (`forecast_timeout_s`) and start grace of the clock loop (300 s, DD130), HTTP, SMTP and database timeouts, retry backoff, heartbeats and the 60 s "process down" rule, WebSocket pings and the 45 s dead-connection timer |

`ews.common.clock` therefore offers two clocks. **Weather time** (`clock.weather`) is the demo clock in demo mode and is used for reading timestamps, forecast issue times and every alert timer (minimum duration, clear-down, cooldown, suppression expiry, offline timeout, live windows). **Machine time** (`clock.machine`) is always the real clock and is used for everything about software health and networking. Code must name which one it uses; there is no default "now".

### 11.3.1 Keeping demo data apart from real data (DD95)

Demo mode is for presentations and end-to-end tests only, never for real monitoring.

| Safeguard | Rule |
|---|---|
| Separate database | Demo mode uses its own database (`ews_demo`, from `DEMO_DATABASE_URL`). A process started with `EWS_CLOCK=demo` refuses to start if the database is not marked as a demo database (`ALTER DATABASE ews_demo SET ews.is_demo = 'on'`, set at creation, [14 §14.1.2](14-operations.md)); a process started with `EWS_CLOCK=real` likewise refuses a demo database, so real readings, alerts and model reports are never touched |
| Separate site | The demo database holds its own site with `site_id = demo`, so `ingest` subscribes only to `sites/demo/…`; a real kit publishing to `sites/abc/…` is never read in demo mode |
| Demo snapshot (DD108) | `scripts/build-demo-snapshot.ps1` builds `ews_demo` once: imports `config/demo-site.yaml`, waits for onboarding, replays ≥ 7 simulated days before the demo period (so the 168 h encoder is full) and lets a few forecast runs complete; then saves it as `config/demo-snapshot.dump` plus `config/demo-snapshot.json` (`sim_time` where the replay stopped, `alembic_revision`, `created_at`; both git-ignored, rebuilt by the script). The JSON file is how the simulator learns where to continue: it never reads the database (DD7, DD116) |
| Reset | `start.ps1 -Demo -Reset` drops `ews_demo`, **restores the snapshot** (with `timescaledb_pre_restore` / `post_restore`, [14 §14.3.3](14-operations.md)), runs `alembic upgrade head` (warning when the snapshot's `alembic_revision` is older than the code's, so it should be rebuilt), and starts the simulator with `demo.yaml` from the `sim_time` in `demo-snapshot.json` (DD116), so every demo starts clean **and** has forecasts from the first minute. Without a snapshot it falls back to an empty database and warns that forecasts start only after onboarding and 7 simulated days |
| No real-clock policies (DD107) | The demo database has no retention or compression policies ([03 §3.14](03-database-schema.md)): TimescaleDB jobs use the real clock and would drop or compress the historical demo dates |
| Labels | The UI shows "DEMO TIME 60×"; every email subject starts with `[DEMO]` |

Practical limit: forecast inference takes 10–20 s ([07 §7.8](07-forecast-worker.md)), so at 60× roughly every second slot runs; live alerts and the pipeline keep up at any speed up to 120×.

## 11.4 Weather sources

### 11.4.1 Replay (TST-01, DD84)

| Item | Rule |
|---|---|
| Sources | (a) Open-Meteo Archive (ERA5) for a location and period, e.g. Delhi 2024-05-25 – 31 heatwave; (b) a CSV export of real kit data (`ts, temp_c, rh_pct, …`) |
| Hourly → 1-minute | Temperature, humidity, pressure: cubic interpolation; wind average: interpolation plus AR(1) turbulence; **gust** = average × gust factor (1.3–1.7, random walk) with occasional bursts; **rain**: each hour's amount converted to tips and placed with a Poisson process inside the hour |
| Sensors | BME280 values = truth + small noise, rounded to 0.01; DHT11 = truth + noise ±1 °C/±3 %, rounded to integers; optional calibration bias so offsets in config can be tested |
| Time | Demo clock: sim time = the historical dates. Real clock: shifted so the replay starts now, 1× only |
| Speed | 1×–120× in demo mode; `pause`, `resume`, `speed` at runtime |

### 11.4.2 Scenarios (TST-02, DD83)

A scenario is a YAML file: a baseline weather plus a timeline of segments that set, ramp or step variables.

```yaml
# simulator/scenarios/squall.yaml  (Scenario 2)
name: squall
baseline: { temp_c: 33, rh_pct: 55, pressure_hpa: 1006, wind_avg_kmh: 8, gust_factor: 1.5, rain_mm_h: 0 }
timeline:
  - at: "+00:00"  duration: "60m"  ramp:  { pressure_hpa: -4.0 }                           # 4 hPa fall (TST-02)
  - at: "+01:00"  duration: "10m"  ramp:  { pressure_hpa: +2.0, temp_c: -4, rh_pct: +15 }   # precursors: jump, drop, rise
  - at: "+01:08"  duration: "1m"   step:  { wind_avg_kmh: 42, gust_kmh: 55 }               # squall onset: mean ≥ 40 for 1 min (D31)
  - at: "+01:09"  duration: "12m"  hold:  { wind_avg_kmh: { mean: 45, sd: 3 }, gust_kmh: { mean: 66, sd: 4 } }   # ≥ 62 for 10 min → Red
  - at: "+01:21"  duration: "15m"  ramp:  { gust_kmh: 30, wind_avg_kmh: 10 }
  - at: "+01:36"  duration: "45m"  hold:  { gust_kmh: { mean: 20, sd: 4 }, rain_mm_h: 12 }  # calm → clear-down
```

Operations: `set` (jump), `ramp` (linear change over the duration), `step` (jump and keep), `hold` (keep a value or a distribution), `noise` (sd per variable). Times are relative to the scenario start in simulated time.

### 11.4.3 Built-in scenarios

| File | Mirrors | Shows |
|---|---|---|
| `normal.yaml` | Scenario 1 | Normal minute, pipeline and WebSocket timing |
| `squall.yaml` | Scenario 2 | Precursors, squall-triggered Live (mean wind ≥ 40 km/h for a minute), Red upgrade, clear-down |
| `single_gust.yaml` | AN-03 | One 45 km/h gust on a calm minute: **no** squall alert |
| `heatwave.yaml` | Scenario 3 | Multi-day heat build-up (use ≥ 60×) |
| `rain_burst.yaml` | Scenario 4 | 100 tips in one hour → intensity Live; 24 h total 70 mm |
| `kit_offline.yaml` | Scenario 5 | Disconnect 10:02–10:40 (fault overlay) |
| `faulty_sensor.yaml` | Scenario 6 | BME/DHT disagreement, 6 °C spike, DHT fallback |
| `suppression.yaml` | Scenario 7 | Yellow wind then Red (operator suppresses in the UI) |
| `multi_kit_front.yaml` | TST-04 | Gust front crossing five kits |

## 11.5 Faults (TST-03, DD86)

Faults are **overlays**: they can be applied on top of any replay or scenario, from the scenario file or the console.

| Fault | Parameters | Effect on the wire | Expected server reaction |
|---|---|---|---|
| `stuck` | variable, duration | Same value repeated | Stuck flag, maintenance notice ([05 §5.4.4](05-data-pipeline.md)) |
| `spike` | variable, delta, readings | Sudden jump, optionally kept (level change) | Faulty, or accepted after re-anchoring ([05 §5.4.3](05-data-pipeline.md)) |
| `bme_fail` | mode (`range`, `spike`) | BME280 impossible values | DHT11 fallback, suspicious ([05 §5.4.5](05-data-pipeline.md)) |
| `drift` | sensor, offset | DHT11 or BME280 offset | Cross-sensor flag |
| `duplicate` | identical / conflicting | Same message again, or same `ts` with other values | Dropped / `conflicting_duplicate` |
| `clock_skew` | seconds | `ts` offset from simulated time | Clock offset on kit health, notice |
| `late` | delay | Messages held back and sent later, in order | Late handling and recomputation ([05 §5.5.3](05-data-pipeline.md)) |
| `malformed` | `not_json`, `missing_field`, `unknown_field`, `wrong_type`, `kit_id_mismatch`, `ts_out_of_window` | Broken payloads | Rejected with that reason code ([05 §5.2](05-data-pipeline.md)) |
| `disconnect` | duration | TCP connection dropped **without** MQTT DISCONNECT (so the broker sends the last will); readings during the outage are discarded, not buffered; reconnect publishes `online` | Offline immediately, outage recorded (HW-12, DP-13) |
| `silent` | duration | Connection kept, no messages | Offline after the 5-minute timeout (DP-09 backup) |
| `reboot` | — | Reconnect with `seq` and `uptime_s` reset | Normal; seq reset visible on kit health |
| `sensor_off` | sensor | Optional fields sent as `null` | Handled as missing |

## 11.6 Multi-kit (TST-04, DD85)

Several kits share one "true" weather field, with realistic local differences:

| Effect | Model |
|---|---|
| Elevation | Temperature lapse −6.5 °C/km; station pressure from the barometric formula (so sea-level pressure agrees across kits after conversion, [05 §5.3](05-data-pipeline.md)) |
| Exposure | Rooftop: wind × 1.2, +0.5 °C at midday; between buildings: wind × 0.7; under trees: −1 °C by day, wind × 0.6; open ground: reference |
| Local noise | Independent AR(1) noise per kit and variable (small), so kits are correlated but not identical |
| Moving events | Fronts and squalls move with a speed and direction; each kit sees the event delayed by its distance along the direction (e.g. a squall front at 40 km/h crosses a 2 km site in 3 minutes) |
| Localised rain | Rain cells with a radius; kits outside get less or none |

This exercises the neighbour check (≥ 3 kits), the median/worst combination rules and per-zone wind alerts ([08 §8.8](08-alert-engine.md)).

## 11.7 Publishing

| Item | Rule |
|---|---|
| Topics | `sites/{site_id}/kits/{kit_id}/readings` every `sampling_interval_s` of simulated time; `…/status` `online` retained on connect; last will `offline` retained |
| QoS | 1 |
| Payload | Built from the sensor model, rounded to sensor resolution; `seq` increments per message; `uptime_s` from simulated boot time; `rssi_dbm` −55 to −80 with slow variation |
| Validation | Every outgoing normal message is checked against `contract.schema.json`; a mismatch stops the simulator (a bug in the simulator, not a test) |
| Demo clock | When `clock.mode = demo`, the simulator also publishes `sim/clock` (retained) every real second; the broker ACL allows only the `simulator` user to write it |

## 11.8 Running

```
python -m simulator run --scenario squall                 # one built-in scenario
python -m simulator run --replay openmeteo --lat 28.61 --lon 77.21 --from 2024-05-25 --to 2024-05-31 --speed 60
python -m simulator run --kits 5 --scenario multi_kit_front
python -m simulator run --script demo.yaml               # Scenario 9, automated
python -m simulator validate                              # check config and scenarios
scripts/start.ps1 -Demo -Simulator squall                 # started with the rest of the system (01 §1.7.4); scenarios need -Demo (DD125)
```

Interactive console (while running):

| Command | Effect |
|---|---|
| `status` | Kits, connection, simulated time, speed, active faults |
| `speed 60`, `pause`, `resume` | Change the demo clock |
| `scenario rain_burst` | Switch to another scenario at the current simulated time |
| `fault KIT-01 disconnect 10m` | Apply a fault overlay |
| `kit KIT-02 off` / `on` | Stop or start one kit |
| `quit` | Disconnect cleanly (sends `offline` itself, not via last will) |

`demo.yaml` scripts Scenario 9: replay a heatwave at 60× → switch to `squall` → `fault KIT-01 disconnect 5m` → print what to show next (model reports page).

## 11.9 Requirement coverage

| Requirement | Section |
|---|---|
| TST-01 | §11.4.1, §11.3 |
| TST-02 | §11.4.2, §11.4.3 |
| TST-03 | §11.5 |
| TST-04 | §11.6 |
| HW-07 – HW-12 | §11.7, §11.5 (`disconnect`, `reboot`, optional fields) |
| 08 §8.2 (same topics, contract, last will) | §11.1, §11.7 |
| Scenario 9 | §11.8 `demo.yaml` |
| NFR-05 | §11.8 start script option |
