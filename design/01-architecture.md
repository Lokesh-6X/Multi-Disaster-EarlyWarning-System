# 1. Architecture

This document fixes the runtime structure of the system: which processes exist, what each one owns, how they talk, how data flows through them, what happens when one fails, how the repository is laid out and how everything is started on a local Windows machine.

Details are left to later documents: endpoints ([02](02-api.md)), tables ([03](03-database-schema.md)), config keys ([04](04-configuration.md)), QC and features ([05](05-data-pipeline.md)), training ([06](06-ml-training.md)), the forecast run ([07](07-forecast-worker.md)), the alert state machine ([08](08-alert-engine.md)), emails ([09](09-notifications.md)), pages ([10](10-ui.md)) and the simulator ([11](11-simulator.md)).

Decisions referenced: DD1–DD13 in [decisions.md](decisions.md).

## 1.1 Overview

One installation monitors **one site** (D26, DD8). It consists of three external services, five backend processes built from one Python package, a browser app and a separate kit simulator.

```
                         ┌───────────────────────────── one Windows machine ─────────────────────────────┐
                         │                                                                                │
 Kit (external) ─┐       │   Mosquitto :1883                                                              │
                 ├─MQTT──┼─► sites/{site_id}/kits/{kit_id}/readings | status                              │
 Simulator ──────┘       │          │ subscribe (QoS 1, persistent session)                              │
                         │          ▼                                                                     │
                         │      [ingest] ──write──►┌──────────────────────────────┐                        │
                         │                         │  PostgreSQL + TimescaleDB    │◄──read/write── [api] ◄─┼── Browser (React)
                         │      [worker] ─write───►│  tables = durable handoff    │                  :8000 │     REST + WebSocket
                         │   every() clock loops   │  NOTIFY  = wake-up signal    │                        │
                         │          │              └──────────────────────────────┘                        │
                         │          │                 ▲            ▲         │                             │
                         │          │                 │            │         │ NOTIFY                      │
                         │          │            [alerts] ────────►┘    [mailer] ──SMTP──► Mailpit :1025   │
                         │          │          only writer of           only sender      (or real SMTP)    │
                         │          │          alert state                                                 │
                         └──────────┼─────────────────────────────────────────────────────────────────────┘
                                    └──HTTPS──► Open-Meteo (forecast, historical)
```

### External services

| Service | Role | Installed as |
|---|---|---|
| Mosquitto 2.x | MQTT broker between kits and `ingest`; publishes kit last will | Windows service |
| PostgreSQL 16/17 + TimescaleDB | All data, configuration and the hand-off between processes | Windows service |
| Mailpit | Local SMTP server and web inbox for the demo (WEB-46) | Executable started by the start script |
| Open-Meteo (internet) | Forecast for the site (DP-10) and 20–30 years of history for onboarding (§4.5) | HTTPS API, no install |

### Our programs

| Program | Entry point | Purpose |
|---|---|---|
| `api` | `python -m ews.api` | FastAPI REST + WebSocket, authentication, serves the built frontend |
| `ingest` | `python -m ews.ingest` | MQTT subscriber: validate, store, calibrate, QC, derive features, kit status |
| `worker` | `python -m ews.worker` | Clock loops (`ews.common.clock.every`, DD130): Open-Meteo fetch, resampling, 15-minute forecast run, onboarding jobs, housekeeping |
| `alerts` | `python -m ews.alerts` | Alert engine: live path and forecast path; the only writer of alert state |
| `mailer` | `python -m ews.mailer` | Sends queued emails with retries; logs every send |
| Frontend | `frontend/` (React + Vite + TypeScript) | Dashboard for operators and admins |
| Simulator | `python -m simulator` | Behaves like a kit; speaks only the MQTT contract |

Why five backend processes (DD1): CPU-heavy inference must never delay a squall Live alert (AL-02) or a WebSocket push (NFR-01), and slow SMTP retries must never block alerting. All five share one package (`ews`), one virtual environment and one config loader, so merging processes later is a small change.

## 1.2 Process responsibilities

| Process | Does | Owns (only writer) | Reads | Wakes on |
|---|---|---|---|---|
| `ingest` | Subscribe to readings and status topics; validate against the contract (DP-12); check topic `site_id` = installation site and topic `kit_id` = payload `kit_id` = a configured kit; dedup on `(kit_id, ts)` (DP-02); store raw values with kit and server timestamps (DP-01, DP-03); apply calibration, tips → mm, sea-level pressure (DP-04, DP-05); QC flags (DP-20 – DP-25); per-reading derived features (DP-06); kit online/offline from the status topic and the no-data timeout (DP-09, DP-13) | Raw and clean readings, rejected messages, QC flags, kit status and outage history | Kit config, latest Open-Meteo value (DP-25) | MQTT message; 30 s timer (no-data timeout) |
| `worker` | Fetch Open-Meteo forecast for the site (DP-10); 15-minute and hourly series are TimescaleDB continuous aggregates refreshed by the database itself (DP-07, DP-08, [03 §3.6.2](03-database-schema.md)); run the forecast every 15 minutes: TFT + LightGBM rain classifier, exceedance probabilities, store the full run (AL-07, AL-12, ML-08, ML-09); run onboarding jobs (§4.5); retention and cleanup | External forecasts, forecast runs and values, normals, onboarding results, back-test reports, jobs | Clean readings, config, model files | Schedule; `onboarding.requested` |
| `alerts` | **Live path**: on each new reading, evaluate live thresholds and squall rules (AL-02, §6.1) per kit/zone. **Forecast path**: on each finished run, evaluate Watch/Warning per hazard with hysteresis, upgrade-fast/downgrade-slow and far-event agreement (AL-08 – AL-11). **Tick** every 60 s: minimum duration, clear-down, suppression expiry, cooldown (AL-04 – AL-06, AL-15). Combine kits per hazard (AL-14). Apply operator commands. Decide every notification and queue it. Turn kit faults and outages into maintenance notices (DP-26) | Alerts, alert history, suppressions, manual alerts, alert-related rows in the email outbox | Clean readings, forecast runs, kit status, config, operator commands, email send log (cooldown) | `reading.ingested`, `forecast.run_completed`, `kit.status_changed`, `kit.qc_flag`, `alert.command`, `config.changed`; 60 s tick |
| `mailer` | Take emails from the outbox, render plain text + HTML (WEB-45), send over SMTP, retry with backoff, record every attempt; mark repeated failures for admins (WEB-44) | Email send log, outbox delivery status | Outbox, templates | `email.queued`; 30 s poll as backup |
| `api` | REST endpoints, login and sessions, role checks (WEB-21); config edits with version check and audit (CFG-04, WEB-25); acknowledgements and notes (WEB-23); write operator commands; queue account emails (invite, reset, WEB-03); forward events to WebSocket clients by role (WEB-24); cache the 72 h forecast per run (NFR-03); serve the built frontend | Users, sessions, config versions, audit log, acknowledgements, notes, advice text, operator commands, account rows in the email outbox | Everything (read-only outside its own tables) | HTTP/WS requests; all NOTIFY events (for WebSocket fan-out) |

### Alert state has one writer (DD2)

Only `alerts` changes alert level and status, starts or stops timers, and decides notifications. This removes races between the live path, the forecast path and operators.

| Operator action | How it reaches the alert | Why |
|---|---|---|
| Acknowledge (WEB-23) | `api` inserts into `alert_acknowledgement`, keyed by the alert and its latest escalation (DD36); the first insert wins ([03 §3.9.3](03-database-schema.md)) | Not a state change; needs an immediate answer |
| Internal note, advice text edit | `api` writes directly | Not a state change |
| Suppress, end suppression, raise manual alert, clear manual alert (AL-15, §7.2) | `api` inserts a row into an **operator command** table and sends `alert.command`; `alerts` applies it within about a second and reports the result as `alert.changed`. The API waits briefly for the result (details in [02](02-api.md)) | Goes through the same state machine, so the safety override of a suppression (AL-15) and notifications behave exactly like automatic changes |

## 1.3 Communication

### 1.3.1 MQTT (kit ↔ `ingest` only)

| Item | Choice |
|---|---|
| Topics | As in the final contract ([02 §2.4](../requirements/02-hardware.md)); `ingest` subscribes to `sites/{site_id}/kits/+/readings` and `sites/{site_id}/kits/+/status` for the installation's `site_id` |
| QoS | 1 for readings and status (at-least-once; duplicates are removed by DP-02) |
| `ingest` session | Fixed client ID with a persistent session (`clean_session = false`), and Mosquitto persistence on, so readings published while `ingest` is restarting are queued by the broker and delivered afterwards. `max_queued_messages 0` removes the default limit of 1 000 queued messages, which would otherwise drop readings during a long outage (DD109) |
| Security (DD11) | Anonymous access off; password file; ACL: each kit user may publish only to `sites/{site_id}/kits/{its kit_id}/#`; the `ingest` user may only subscribe; simulator kits use the same kit users as real kits |
| Internal events | **Not** carried over MQTT (DD3) |
| Demo clock | Only with `EWS_CLOCK=demo`: the simulator publishes `sim/clock` (retained; only the `simulator` user may write it); `ingest` relays it to the other processes as a NOTIFY ([11 §11.3](11-simulator.md), DD82) |

### 1.3.2 PostgreSQL as the hand-off between processes (DD3)

- Every hand-off is a **row in a table**, committed in the same transaction as the data it describes.
- After commit, the writer sends `NOTIFY ews, '<json>'` as a **wake-up signal** only. The payload is small (type plus IDs, or a single reading for the WebSocket) and stays below PostgreSQL's 8000-byte limit.
- Each consumer stores a **processed-up-to marker** (e.g. last reading ID per kit, last evaluated forecast run). On start-up and on every wake-up it processes everything after its marker. A missed NOTIFY (consumer down or reconnecting) therefore loses nothing.
- No process keeps state that matters only in memory (DD13): alert timers, cooldowns and suppressions are stored as timestamps, so a restart resumes exactly where it stopped.

| Event (`type`) | Sent by | Received by | Meaning |
|---|---|---|---|
| `reading.ingested` | `ingest` | `alerts`, `api` | New clean reading stored (payload includes the values for the WebSocket) |
| `kit.status_changed` | `ingest` | `alerts`, `api` | Kit went online/offline |
| `kit.qc_flag` | `ingest` | `alerts`, `api` | Reading or kit flagged suspicious/faulty |
| `message.rejected` | `ingest` | `api` | Contract validation failed (kit health view) |
| `forecast.run_completed` | `worker` | `alerts`, `api` | New run stored |
| `onboarding.requested` | `api` | `worker` | Site created or location changed |
| `onboarding.progress` | `worker` | `api` | Step finished or failed |
| `alert.command` | `api` | `alerts` | Operator command waiting |
| `alert.changed` | `alerts` | `api` | Alert created / upgraded / downgraded / cancelled / cleared / suppressed |
| `alert.acknowledged` | `api` | `api` | Broadcast acknowledgement to all clients |
| `config.changed` | `api` | `ingest`, `worker`, `alerts`, `api` | New config version; processes reload resolved config |
| `email.queued` | `alerts`, `api` | `mailer` | Outbox has new rows |
| `clock.tick` | `ingest` | all | Demo mode only: simulated time from `sim/clock` ([11 §11.3](11-simulator.md)) |

### 1.3.3 Configuration reload

Each process caches the resolved configuration ([04](04-configuration.md)) and reloads it on `config.changed`. Effect (CFG-05, AL-16):

| Process | Uses the new version from |
|---|---|
| `ingest` | The next reading (calibration, mm per tip, elevation, enabled sensors, QC limits) |
| `worker` | The next forecast run |
| `alerts` | Forecast path: the next forecast run. Live path: the next reading. The change is noted in alert history |

### 1.3.4 Browser ↔ `api`

The browser talks only to `api`: REST for reads and writes, one WebSocket for pushed events (WEB-24), session token for both. Contract in [02](02-api.md).

### 1.3.5 Outgoing

| From | To | What |
|---|---|---|
| `mailer` | SMTP (Mailpit locally; real server from `.env`) | All email |
| `worker` | Open-Meteo HTTPS | Forecast every hour; historical download during onboarding |

## 1.4 Data flows

### 1.4.1 A reading's journey (Scenario 1, NFR-01 ≤ 5 s)

```
Kit ─► Mosquitto ─► ingest ─────────────────────────────► DB commit ─► NOTIFY reading.ingested
                     validate → dedup → store raw →                      │            │
                     calibrate/convert → QC → derive features            ▼            ▼
                                                                       alerts        api ─► WebSocket ─► dashboards
                                                                    (live path)
```

| Step | Target time |
|---|---|
| Broker → `ingest` → commit | < 300 ms |
| NOTIFY → `api` → WebSocket → browser | < 500 ms |
| Total, server receive → screen | ≈ 1 s (budget 5 s) |

### 1.4.2 Forecast run every 15 minutes

```
worker (clock loop, every 15 min)
  1. load resolved config + active model versions (registry)
  2. read hourly series per kit + latest Open-Meteo forecast + static inputs
  3. TFT → quantiles (P10/P50/P90), LightGBM → P(heavy rain)
  4. derive exceedance probabilities per hazard / level / horizon window
  5. store run (issue time, model versions, values, quantiles, probabilities) in one transaction
  6. NOTIFY forecast.run_completed
       ├─► alerts: forecast path → create / upgrade / downgrade / cancel → outbox → NOTIFY email.queued
       └─► api: drop forecast cache, push "new run" to dashboards
```

Inference runs in a child process of `worker`, so the scheduler stays responsive and a crash in model code does not stop other jobs. Exact timing offset, inputs and time budget are in [07](07-forecast-worker.md).

### 1.4.3 Live alert to email (Scenario 2, squall)

```
reading.ingested ─► alerts (live path)
                      squall rule / live threshold met (after minimum duration)
                      ├─ alert row created, history row written, outbox rows written   ← one transaction
                      ├─ NOTIFY alert.changed ─► api ─► banner on dashboards
                      └─ NOTIFY email.queued  ─► mailer ─► SMTP ─► Mailpit / recipient lists + operators
```

### 1.4.4 Operator command (Scenario 7, suppression)

```
browser ─POST─► api: check role, insert operator command, audit log, NOTIFY alert.command
                     wait up to a few seconds for the result
alerts: apply command through the state machine, write history, NOTIFY alert.changed
api: reply to the browser with the result; WebSocket pushes the change to everyone
```

### 1.4.5 First run and site onboarding

```
1. First start: no users → first-run setup creates the first admin (WEB-01)
2. Admin enters site config (site_id, name, lat, lon, elevation, timezone, region type)
   → api saves version 1, NOTIFY onboarding.requested
3. worker runs onboarding steps (04 §4.5): download history → normals → labels →
   top-10 events → back-test with the global model → validation report
   → progress pushed to the browser via onboarding.progress
4. Admin adds kits (kit_id, zone, location, calibration); kits can connect at any time
5. Forecast runs start when onboarding is complete (normals are a model input and
   heatwave thresholds need them); until then the dashboard shows live data and
   live wind/rain alerts only, with an "onboarding in progress" notice
```

- `site_id` is fixed once kits have connected, because it is part of the MQTT topics.
- Changing site latitude, longitude, elevation or region type re-runs onboarding (CFG-07). The previous normals stay in use until the new ones are ready.

## 1.5 Failure behaviour

| Failure | Effect | Recovery |
|---|---|---|
| Mosquitto down | Kits cannot publish; readings lost (HW-09); no last will is possible | `ingest` marks kits offline after the no-data timeout (DP-09); reconnects with backoff |
| `ingest` down | Readings queue in the broker (persistent session) | On restart the queue is delivered; dedup handles repeats |
| PostgreSQL down | No process can write | `ingest` disconnects from MQTT so the broker queues readings for its session; all processes retry the connection; nothing is acknowledged as stored until committed |
| `worker` down | No new forecast runs; dashboards show the age of the last run ("forecast stale") | Live alerts continue (AL-02). Forecast alerts keep their state; the rule for a stale forecast is defined in [08](08-alert-engine.md). Next run on restart |
| `alerts` down | No alert changes, no new alert emails | On restart catches up from its markers; timers continue from stored timestamps |
| `mailer` down | Emails wait in the outbox | Sent on restart; emails for changes already replaced by a newer change of the same alert are skipped (rules in [09](09-notifications.md)) |
| `api` down | Dashboards show "reconnecting" and data age (NFR-04) | No data lost; clients reconnect and reload |
| A process crashes | — | The start script's wrapper restarts it after 5 s (§1.7) |

**Heartbeats (design addition, DD12):** each process updates its row in a heartbeat table every 15 s of real time (machine time, also in demo mode, DD117) (process name, PID, start time, last beat, version). The API reports a process as down after 60 s without a beat; admins see it on the kit-health page and the dashboard shows a warning. This is not in the requirements; it supports NFR-04 and makes failures visible during the demo.

## 1.6 Repository structure

```
Disaster Predection/
├── requirements/                 source of truth (requirements)
├── design/                       these documents
├── backend/
│   ├── pyproject.toml            one package "ews", one virtual environment
│   ├── ews/
│   │   ├── common/               settings (.env), clock (real/demo/fake), DB access, config resolution, events (NOTIFY/LISTEN),
│   │   │                         logging, heartbeat, domain types shared by all processes
│   │   ├── api/                  FastAPI app: routers, auth, WebSocket hub, static frontend
│   │   ├── ingest/               MQTT client, contract validation, QC, conversions, derived features, kit status
│   │   ├── worker/               scheduler, Open-Meteo client, resampling, forecast run, onboarding
│   │   ├── ml/                   inference code: model loading, feature building, probability derivation
│   │   ├── alerts/               alert engine: live path, forecast path, combination rules, commands
│   │   └── mailer/               outbox reader, sender interface, SMTP sender, templates
│   ├── migrations/               Alembic database migrations
│   └── tests/                    unit, integration and end-to-end tests (see 12)
├── frontend/                     React + Vite + TypeScript; API types generated from OpenAPI
├── simulator/                    standalone kit simulator (does not import ews), scenario files
├── ml/                           training: notebooks and scripts for Kaggle, data download, evaluation
├── models/                       model files + registry.json (files git-ignored, registry committed)
├── config/
│   ├── defaults.yaml             system defaults (the rulebook shipped with the software)
│   ├── example-site.yaml         example site and kits for the demo
│   └── mosquitto/                mosquitto.conf, ACL file (password file git-ignored)
├── scripts/                      start.ps1, stop.ps1, check-setup.ps1, run-process.ps1, logs.ps1, backup.ps1, restore.ps1 (14)
├── backups/                      database dumps (git-ignored, 14 §14.3)
├── tools/                        mailpit.exe (git-ignored)
├── docs/setup-guide.md           installs and first-time setup (NFR-05)
├── logs/                         per-process logs (git-ignored)
├── .env.example                  every environment variable with a safe example value
└── .env                          real secrets (git-ignored, NFR-08)
```

| Rule | Reason |
|---|---|
| `simulator/` never imports `ews` (DD7) | It must behave exactly like an external kit; only the MQTT contract connects them |
| Training code (`ml/`) and inference code (`backend/ews/ml/`) are separate (DD10) | Training runs on a Kaggle GPU with heavy dependencies; the backend only needs CPU inference |
| Feature-building code used by both training and inference lives in `backend/ews/ml/` and is imported by `ml/` | The same features in training and in live inference |
| `models/registry.json` names the active version per model | Every stored forecast records the versions it used (ML-09) |

## 1.7 Running locally

### 1.7.1 Installs (listed in the setup guide)

| Software | Version | Notes |
|---|---|---|
| Python | 3.13 (DD129) | Backend, worker, simulator; CPU builds of PyTorch |
| Node.js | 24 LTS (DD127) | Building the frontend; Vite dev server in development |
| PostgreSQL + TimescaleDB | 16 or 17 + matching TimescaleDB | Windows service |
| Mosquitto | 2.x | Windows service with `config/mosquitto/mosquitto.conf` |
| Mailpit | latest | Single executable |

### 1.7.2 Ports

| Port | Service |
|---|---|
| 8000 | `api` (REST, WebSocket and built frontend) |
| 5173 | Vite dev server (development only; forwards `/api` and `/ws` to 8000) |
| 1883 | Mosquitto |
| 5432 | PostgreSQL |
| 1025 / 8025 | Mailpit SMTP / web inbox |

Only 1883 is reachable from the network (kits). All other ports, including the dashboard on 8000, are local to the server machine (requirements D34); `APP_BASE_URL` is `http://localhost:8000`.

### 1.7.3 Environment file (`.env`)

Names only; values in `.env.example`.

| Variable | Used by |
|---|---|
| `DATABASE_URL` | all backend processes |
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_INGEST_USER`, `MQTT_INGEST_PASSWORD` | `ingest` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS` | `mailer` |
| `APP_BASE_URL` | links in emails (acknowledge, invite, reset); allowed WebSocket origin |
| `DEV_ORIGINS` | `api`; extra allowed WebSocket origins, empty except with `-Dev` (`http://localhost:5173`, DD122) |
| `SECRET_KEY` | session tokens |
| `OPEN_METEO_FORECAST_URL`, `OPEN_METEO_ARCHIVE_URL` | `worker` |
| `MODELS_DIR`, `LOG_DIR`, `LOG_LEVEL` | all |
| `EWS_CLOCK` (`real` default, or `demo`) | all; `demo` follows the simulator's clock ([11 §11.3](11-simulator.md)) |
| `DEMO_DATABASE_URL` | all, in demo mode only (separate `ews_demo` database) |

Simulator kit credentials are in the simulator's own config file, not in the backend `.env`.

### 1.7.4 Start and stop scripts (PowerShell, DD12)

`scripts/start.ps1 [-Dev] [-Simulator <scenario>] [-Seed <site.yaml>] [-Demo [-Reset]]` (`-Seed` imports a site file when no site exists, [04 §4.6](04-configuration.md); `-Demo` runs everything on the demo clock against the separate demo database, `-Reset` restores it from the prepared demo snapshot, [11 §11.3.1](11-simulator.md), DD108)

1. Load `.env`; stop with a clear message if it is missing.
2. Check that PostgreSQL and Mosquitto services are running (start them if allowed); start Mailpit if `SMTP_HOST` is local and it is not running.
3. Check the database connection and the TimescaleDB extension; run `alembic upgrade head`; sync `config/defaults.yaml` into the settings catalogue (`python -m ews.common.config sync`, DD110), so every process starts with the current catalogue.
4. Frontend: without `-Dev`, build `frontend/` if the build is missing or older than the source; with `-Dev`, start the Vite dev server.
5. Start `ingest`, `alerts`, `mailer`, `worker`, `api` (in that order), each through `run-process.ps1`, which restarts the process 5 s after a crash, writes `logs/<name>.log` and a PID file.
6. With `-Simulator <scenario>`, start the simulator in that mode ([11](11-simulator.md)). Scenario and fault modes are refused without `-Demo`; without `-Demo` only the replay/normal stand-in kit is allowed, and only while `SMTP_HOST` is local (Mailpit), so simulated hazards can never email real people (requirements D39, DD125).
7. Print the URLs: dashboard `http://localhost:8000`, Mailpit `http://localhost:8025`.

`scripts/stop.ps1` stops everything started by `start.ps1` (using the PID files) and leaves the Windows services running. `scripts/check-setup.ps1` checks the installs and versions without starting anything.

## 1.8 Requirement coverage

| Requirement | Where |
|---|---|
| HW-12, DP-09, DP-13 | `ingest` (status topic, no-data timer) |
| DP-01 – DP-06, DP-11, DP-12, DP-20 – DP-25 | `ingest` |
| DP-07, DP-08, DP-10 | `worker` |
| DP-26 | `ingest` (detect) → `alerts` (notice) → `mailer` |
| CFG-04, CFG-05, CFG-07 | `api` (versions, audit, onboarding trigger), `config.changed` reload, `worker` (onboarding) |
| ML-08, ML-09, AL-07, AL-12 | `worker` forecast run, model registry |
| AL-01 – AL-17 | `alerts` |
| WEB-20 | Forecasts and alerts computed only in `worker` / `alerts` |
| WEB-21 – WEB-25 | `api` |
| WEB-26, WEB-40 – WEB-46 | `alerts` (decide, queue) → `mailer` (send, log) |
| NFR-01 | §1.4.1 timing |
| NFR-04 | WebSocket reconnect in the frontend, heartbeats |
| NFR-05, NFR-08 | §1.7 |
| NFR-07 | One site per installation; kits and site are configuration (D26) |
| TST-01 – TST-04 | `simulator/` |
