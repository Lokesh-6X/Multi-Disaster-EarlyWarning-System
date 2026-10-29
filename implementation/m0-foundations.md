# M0 Foundations and week-1 checks

**Goal:** everything installed, the risky assumptions proven, the empty system starts and tests run.
**Done when:** every week-1 check has a written result, `scripts/start.ps1` starts five processes that write heartbeats, and `scripts/test.ps1 -Unit` passes.

Write the result of every week-1 check (M0.3–M0.6, M0.9) into the [week-1 results](#week-1-results) table at the end of this file.

---

- [x] **M0.1 Install the software**
  - Do: install Python 3.13 (DD129), Node 24 LTS (DD127), PostgreSQL 16/17, matching TimescaleDB, Mosquitto 2.x, Mailpit (`tools/mailpit.exe`), Git. Note every step in `docs/setup-guide.md` as you go.
  - Check: `python --version`, `node --version`, `psql --version`, `mosquitto -h` print the expected versions.
  - Ref: [design/14 §14.1.1](../design/14-operations.md)

- [x] **M0.2 Create the databases**
  - Do: `shared_preload_libraries = 'timescaledb'`, restart PostgreSQL; create role `ews` and databases `ews`, `ews_test`, `ews_demo`; mark the demo database (`ews.is_demo = on`); `CREATE EXTENSION timescaledb, citext` in each.
  - Check: `psql -U ews -d ews_demo -c "SHOW ews.is_demo"` → `on`; `\dx` lists both extensions in all three.
  - Ref: [design/14 §14.1.2](../design/14-operations.md) step 3 · Needs: M0.1

- [x] **M0.3 Week-1 check 1: TimescaleDB features**
  - Do: in `ews_test` create a hypertable, a continuous aggregate with `materialized_only = false`, a compression policy, a retention policy, and an integer hypertable with `set_integer_now_func`; then drop them. Save the SQL as `scripts/sql/timescale-check.sql` (reused by `check-setup.ps1`).
  - Check: all five statements succeed. **If not:** record it and switch to the fallback (plain partitions + `worker` refresh behind the `series_*` views) before M2.
  - Ref: [analysis/05 §5.3](../analysis/05-scope-and-plan.md), DD113 · Needs: M0.2

- [x] **M0.4 Mosquitto config and week-1 check 4**
  - Do: `config/mosquitto/conf.d/ews.conf` (no anonymous, password file, ACL, `persistence true`, `max_queued_messages 0`); users `ingest`, `KIT-01`, `simulator`. With a 20-line Python script: connect a kit with a last will and kill it → `offline` appears; subscribe `ingest` with a persistent session, disconnect, publish 2 000 messages, reconnect.
  - Check: last will arrives at once; all 2 000 messages are delivered; anonymous login is refused.
  - Ref: [design/01 §1.3.1](../design/01-architecture.md), DD11, DD109 · Needs: M0.1

- [x] **M0.5 Week-1 check 2: Open-Meteo archives and limits**
  - Do: for one location, request the Previous Runs API for the six variables and find the first date with data per variable; read the current request-weighting rules and limits.
  - Check: start dates per variable and the weighting written in the results table. If coverage starts after early 2024, note the change to the stage-2 splits.
  - Ref: [design/06 §6.3](../design/06-ml-training.md), DD118

- [x] **M0.6 Week-1 check 3: Darts TFT on CPU**
  - Do: in a scratch venv with the pinned versions: TFT with 5 targets, static + past + future covariates, 9 quantiles; 2 locations of ERA5, 1 epoch; save, reload, predict.
  - Check: reload gives identical predictions; inference for one series < 10 s. Pin the working versions in `ml/requirements.txt` and `backend/pyproject.toml`.
  - Ref: [design/06 §6.8.2](../design/06-ml-training.md) · Needs: M0.1

- [x] **M0.7 Repository skeleton**
  - Do: `git init`; folders of [design/01 §1.6](../design/01-architecture.md); `.gitignore` (`.env`, `logs/`, `backups/`, `tools/`, `models/*/`, `config/mosquitto/passwd`, `config/demo-snapshot.*`); `.env.example` with every variable of 01 §1.7.3; `backend/pyproject.toml` (package `ews`, dev extras: pytest, hypothesis, httpx); `frontend/` from `npm create vite` (React + TS); `simulator/pyproject.toml`.
  - Check: `pip install -e backend[dev]` and `npm ci` succeed; `git status` shows no secrets.
  - Ref: [design/01 §1.6–1.7](../design/01-architecture.md)

- [x] **M0.8 `ews.common`: settings and logging**
  - Do: settings from `.env` (fail with a clear message if missing); JSON-line logger with `process`, `event`, rotation 10 MB × 10, secrets never logged.
  - Check: unit test: a log record is one JSON line with the required fields; a password field is masked.
  - Ref: [design/14 §14.2](../design/14-operations.md), DD96 · Needs: M0.7

- [x] **M0.9 `ews.common.clock` and week-1 check 5**
  - Do: `clock.weather` and `clock.machine` (DD117) with `real`, `demo` and `fake` sources; demo source follows `sim/clock` ticks and interpolates. Prove that an APScheduler job (or a small custom loop) fires every 15 minutes of **weather** time while the demo clock runs at 60×.
  - Check: unit tests for fake and demo clocks; the job fires every 15 real seconds at 60×. If APScheduler cannot follow the custom clock, write the custom loop and note it.
  - Ref: [design/11 §11.3](../design/11-simulator.md), DD82, DD117 · Needs: M0.8

- [x] **M0.10 Database access, events, heartbeat**
  - Do: async connection pool; `notify(type, payload)` / `listen()` helpers (payload < 8 000 bytes); heartbeat task writing `process_heartbeat` every 15 s of machine time.
  - Check: integration test: a NOTIFY sent after commit is received; a heartbeat row updates.
  - Ref: [design/01 §1.3.2](../design/01-architecture.md), §1.5 · Needs: M0.2, M0.9

- [x] **M0.11 First migration and the settings catalogue**
  - Do: Alembic migration with extensions, all enums, `site`, `kit`, `config_key` (+ `deprecated`), `config_key_region_default`, `config_version`, `config_value`, `app_user`, `process_heartbeat`; `config/defaults.yaml` with every key of design/04 §4.3; `python -m ews.common.config sync`.
  - Check: `alembic upgrade head` on an empty `ews_test`; `sync` loads ≈ 130 keys; running it twice changes nothing; a removed key becomes `deprecated`.
  - Ref: [design/03 §3.4–3.5, §3.11](../design/03-database-schema.md), [design/04 §4.3, §4.7](../design/04-configuration.md), DD110 · Needs: M0.10

- [x] **M0.12 Scripts**
  - Do: `start.ps1` (steps 1–7 of design/01 §1.7.4, five empty processes `python -m ews.<name>` that only heartbeat), `stop.ps1`, `run-process.ps1` (restart after 5 s, logs, PID file), `check-setup.ps1` (table of design/14 §14.1.3), `test.ps1 [-Unit] [-Integration] …`.
  - Check: `check-setup.ps1` all OK; `start.ps1` → five heartbeats in `process_heartbeat`; kill one process → it is back within 10 s; `test.ps1 -Unit` passes.
  - Ref: [design/01 §1.7.4](../design/01-architecture.md), [design/14 §14.1.3](../design/14-operations.md) · Needs: M0.11

---

## Week-1 results

| Check | Result | Consequence |
|---|---|---|
| 1 TimescaleDB features (M0.3) | **Pass** (2026-10-30). TimescaleDB 2.31.0 on PostgreSQL 17.11, Windows, license `timescale`; run as role `ews` in `ews_test` with `scripts/sql/timescale-check.sql`. All five work: hypertable; continuous aggregate with `materialized_only = false` returns rows before any refresh; compression policy (a chunk really compressed and still readable, also on the continuous aggregate); retention policy; integer hypertable on `run_id` with `set_integer_now_func` plus compression and retention policies. 6 jobs created, all removed on drop | No fallback needed; plain partitions not used. Memory note: TimescaleDB tuning set `shared_buffers` too high for this laptop, lowered to 512 MB (setup guide §1.4) |
| 2 Open-Meteo archives and limits (M0.5) | **Done** (2026-10-30), Delhi 28.61, 77.21, default model (`best_match`), `scripts/checks/openmeteo_coverage.py`. **First date per variable** (lead day 1 / 2 / 3): `relative_humidity_2m`, `wind_speed_10m`, `wind_gusts_10m`, `precipitation`, `pressure_msl` 2024-01-19 / 01-20 / 01-21, then complete to 2025-12-31 (only the first day partial); `temperature_2m` 2021-03-24 / 03-25 / 03-26 (GFS archive), 21–23 incomplete days. All 18 columns complete from **2024-01-22**. **Limits (free, non-commercial):** 600 / min, 5 000 / h, 10 000 / day, 300 000 / month (monthly not enforced yet). **Weighting:** calls = (variables / 10) × (days / 14), fractional, at least 1; one year of six variables ≈ 16 calls (design estimate "≈ 25 or more" is on the safe side); six years of six variables measured as ≈ 94 | Coverage starts in early 2024, so the stage-2 splits stay (validation 2024, test 2025). 2024-01-01 – 01-21 has no lead-correct inputs: use stitched Historical Forecast data there (as 06 §6.3 already allows) and record the start date 2024-01-22 in `ml/data/manifest.json` (ML track). Ignore the longer temperature-only archive so all inputs share one start. Download sizes: onboarding 35 years ≈ 560 calls (fits with 10 s pacing); training ≈ 16 000 calls in total (history ≈ 13 000) → at least 2 days under the 10 000 / day limit, as DD118 plans |
| 3 Darts TFT on CPU (M0.6) | **Pass** (2026-10-30), `scripts/checks/tft_cpu_trial.py` on the laptop CPU, Python 3.13.17, torch 2.11.0+cpu, pytorch-lightning 2.6.6, Darts 0.48.1, LightGBM 4.7.0, pandas 2.3.3. TFT with 5 targets, static (lat, lon, elevation, region) + past (wind, pressure tendency, 24 h rain) + future covariates (hour, day of year, month, normal max), 9 quantiles, 168 h → 72 h, hidden 64; ERA5 2023–2024 for Delhi and Chennai, 1 epoch, 3 000 samples per location: training 43 s; model 3.7 MB; reloaded model gives **identical** predictions (72 h × 45 columns); inference for one series **0.04 s** | Versions pinned in `ml/requirements.txt` and `backend/pyproject.toml`. Training moved to Kaggle (D40, DD128) and Python to 3.13 to match Kaggle (DD129). Setup findings: plain `darts` needs `pytorch-lightning` installed explicitly; Windows Smart App Control blocks pandas 3.1.0, so pandas 2.3.3 is pinned (setup guide §1.1) |
| 4 Mosquitto (M0.4) | **Pass** (2026-10-30). Mosquitto 2.1.2 as Windows service on 1883, settings from `scripts/setup-mosquitto.ps1` (no anonymous, password file, ACL, `persistence true`, `max_queued_messages 0`); `scripts/checks/mqtt_check.py`: anonymous refused; 2 000 readings published while `ingest` (persistent session) was away all delivered; last will `offline` 0.00 s after killing the kit process; ACL drops a kit publishing to another kit and any publish by `ingest` | No `mosquitto.conf` change needed. Setup finding: `mosquitto_passwd` 2.1 makes the password file readable by the current user only, so the service (SYSTEM) quit at start; the script now grants SYSTEM read. ACL uses `sites/+/…` until the site exists (re-run with `-SiteId`) |
| 5 Demo clock drives a 15-minute job (M0.9) | **Pass** (2026-10-30), `scripts/checks/demo_clock_check.py` through the Mosquitto service: a stand-in simulator publishes `sim/clock` (retained, user `simulator`) every real second; a follower (user `ingest`) feeds `DemoClock`; `ews.common.clock.every()` fired on consecutive weather slots 06:15, 06:30, 06:45, 07:00 every **15.00 s** real at 60× (gaps 14.99 / 15.00 / 15.00 s) and every **7.50 s** at 120×. Unit tests for fake and demo clocks (interpolation, speed change, late tick held, reset jump, pause, skip of missed slots) | **APScheduler 3 cannot follow the custom clock** (its scheduler calls `datetime.now()` directly in 5 places and waits on real-time timers), so the planned fallback is used: the custom loop `every()` on the clock abstraction for weather-time jobs (analysis/05 §5.3). APScheduler is not needed for weather-time scheduling; the worker design (M4) uses `every()` |
| 6 Wet-hour p99 and normals for 3 locations ([ml-track.md](ml-track.md) T2b) | | |
