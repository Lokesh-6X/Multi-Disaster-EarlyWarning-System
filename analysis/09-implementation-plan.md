# 9. Implementation Plan

> **To work from:** use the checklists in [implementation/](../implementation/README.md): one file per milestone, small tasks with **Do / Check / Ref / Needs** and tick boxes, plus a status table. This document is the overview and the reasoning behind the order.

How to build the system described in [requirements/](../requirements/README.md) and [design/](../design/README.md), in what order, and how to know each step is finished. It refines the build order of [requirements 08 §8.5](../requirements/08-non-functional-and-testing.md) into milestones with tasks, design references, tests and a clear "done when". It contains no dates; sizes are relative (S, M, L, XL).

## 9.1 Principles

| Principle | What it means in practice |
|---|---|
| A working demo early, then better | Milestone M1 already shows a simulated reading on screen. Every later milestone adds to a system that runs end to end |
| Two tracks in parallel | **Backend track** (M0–M9) on the laptop; **ML track** (T1–T8) on Colab. They meet at the model registry: the backend uses a tiny test model set until the real models are ready ([design/12 §12.2](../design/12-testing.md)) |
| Test-first where the rules are | Contract validation, QC, config resolution and above all the **alert state machine** are written from their tables in the design, with the tests first (DD94) |
| Real services in tests | PostgreSQL/TimescaleDB, Mosquitto and Mailpit are used in integration tests, not mocks (DD90) |
| Design is the contract | If code needs a different rule, change the design document first and record a D/DD number (next free: D40, DD127) |
| Always "site" | Never "campus", in code, UI and report |

## 9.2 Overview

```
 M0 Foundations + week-1 checks
   │
   ├── M1 Skeleton: simulator → MQTT → ingest → DB → API → live tile         (demo-able)
   │     │
   │     ├── M2 Data pipeline complete: QC, features, aggregates, kit health
   │     │
   │     ├── M3 Configuration + site onboarding + Open-Meteo
   │     │     │
   │     │     └── M4 Forecast worker (test models) ◄─────────────┐
   │     │           │                                            │
   │     │           └── M5 Alert engine ── M6 Notifications      │
   │     │                         │                              │
   │     └── M7 Users, permissions, audit, admin pages            │
   │                                │                             │
   │                    M8 Dashboard pages complete               │
   │                                │                             │
   └──────────────► M9 Real models, reports, demo, hardening ◄────┤
                                                                  │
 ML track:  T1 download → T2 prepare/normals/labels → T3 baselines → T4 TFT-base
            → T5 TFT-NWP → T6 event classifiers → T7 calibrate/select → T8 evaluate/export
 Hardware:  real kit connected whenever it is ready (requirements 08 §8.5 phase 2)
```

| Milestone | Requirements 08 §8.5 phase | Size |
|---|---|---|
| M0 Foundations | — (before phase 1) | M |
| M1 Skeleton | 1 | M |
| M2 Data pipeline | 1 (completed) | L |
| M3 Configuration API and onboarding (core in M1) | 8 (moved earlier: forecasts need it) | L |
| M4 Forecast worker | 4 | M |
| M5 Alert engine | 5 | XL |
| M6 Notifications | 7 | M |
| M7 Users, permissions, audit | 8 | M |
| M8 Dashboard pages | 6 | L |
| M9 Real models, reports, demo | 9 | L |
| T1–T8 ML track | 3 | XL |
| Real kit | 2 | S (software side) |

Configuration (M3) is moved before the forecast worker because forecasts need onboarding results (normals) and resolved thresholds; the admin **editor UI** stays in M7/M8.

---

## 9.3 M0 Foundations and week-1 checks

**Goal:** the tools are installed, the riskiest assumptions are proven, and the repository skeleton builds and tests.

| # | Task | Design |
|---|---|---|
| 0.1 | Install everything on the demo laptop following [14 §14.1](../design/14-operations.md); write `docs/setup-guide.md` while doing it | 14 §14.1 |
| 0.2 | **Week-1 checks 1–6** ([05 §5.3](05-scope-and-plan.md)): TimescaleDB features; Open-Meteo Previous Runs coverage and request weighting; Darts TFT CPU trial; Mosquitto last will + 2 000 queued messages; demo clock driving a 15-minute job; wet-hour p99 and normal maximum for 3 locations | 05 §5.3, DD113 |
| 0.3 | Record the results; apply fallbacks if any check fails (and update the design) | 06 §6.3, 14 §14.1.3 |
| 0.4 | Repository layout of [01 §1.6](../design/01-architecture.md): `backend/` (package `ews`, `pyproject.toml`, Alembic), `frontend/` (Vite + React + TypeScript), `simulator/`, `ml/`, `models/`, `config/`, `scripts/` | 01 §1.6 |
| 0.5 | `ews.common`: settings from `.env`, **clock with weather time and machine time** (DD117), database access, NOTIFY/LISTEN helper, JSON logging (DD96), heartbeat (DD12) | 01 §1.3, 11 §11.3, 14 §14.2 |
| 0.6 | First migration: extensions, enums, `site`, `kit`, `config_*`, `app_user` (referenced by `config_version`), `process_heartbeat`; `config/defaults.yaml` with the full key catalogue and `python -m ews.common.config sync` (DD110) | 03 §3.4–3.5, §3.11, 04 §4.3, §4.7 |
| 0.7 | `scripts/start.ps1`, `stop.ps1`, `run-process.ps1`, `check-setup.ps1`, `test.ps1` (first versions) | 01 §1.7.4, 12 §12.2 |

**Tests:** `check-setup.ps1` all OK; unit tests for the clock (fake, real, demo; weather vs machine time) and the config resolver skeleton.

**Done when:** every week-1 check has a recorded result, `start.ps1` starts five empty processes that write heartbeats, and `test.ps1 -Unit` passes.

---

## 9.4 M1 Skeleton (demo-able)

**Goal:** requirements 08 §8.5 phase 1: "a simulated reading appears on screen within seconds".

| # | Task | Design |
|---|---|---|
| 1.0 | **Configuration core** (no API, no UI yet): resolver, validator (all 7 steps), versioned storage, YAML import used by `start.ps1 -Seed config/example-site.yaml` and for the demo site (AN-44) | 04 §4.2, §4.4, §4.6, 03 §3.5 |
| 1.0b | **Shared feature and label code** `ews.ml.features`, `ews.ml.labels`: heat index, end-labelled hourly series, hazard labels, wet-hour percentile, normals; golden-value tests. The ML track uses this module from T2 on (AN-45) | 06 §6.4–6.6, 05 §5.5, §5.7 |
| 1.0c | Users and email-preference tables with defaults for every user (enabled, all hazards and types, min level yellow, maintenance on); UI comes in M7 (AN-48) | 03 §3.11 |
| 1.1 | Simulator: `kit.py` (MQTT client, last will, online/offline, seq, uptime), `contract.schema.json`, replay/normal mode at 1×; guard of DD125 | 11 §11.2, §11.7, DD125 |
| 1.2 | Mosquitto config: users, ACL, persistence, `max_queued_messages 0` | 01 §1.3.1, DD109 |
| 1.3 | `ingest`: subscribe, strict contract validation, dedup, store raw + clean (calibration, tips → mm, sea-level pressure), kit status from status topic and timeout, `reading.ingested` NOTIFY | 05 §5.1–5.3, §5.6 |
| 1.4 | Tables: `reading_raw`, `reading_clean` (both config versions, DD123), `kit_status_event`, `rejected_message` as hypertables | 03 §3.6 |
| 1.5 | `api`: first-run setup, login/logout, cookie sessions + CSRF (minimal, full user management in M7), `GET /live`, WebSocket with `hello`, `ping`, `reading.new`, `kit.status`, `DEV_ORIGINS` | 02 §2.2, §2.6.1, §2.6.4, §2.7, DD122 |
| 1.6 | Frontend: shell, login, live tiles for one kit, connection pill, freshness label | 10 §10.3, §10.4.1, 13 §13.3.8 |

**Tests:** TST-10 core cases (resolution order, override scope, threshold order, atomic import); golden values for heat index and labels; TST-11 contract cases; Scenario 1 (normal minute) at real clock: publish → screen ≤ 5 s (target ≈ 1 s); kit disconnect → offline at once via last will.

**Done when:** `start.ps1` + the stand-in simulator show live readings on the dashboard, and the kit goes offline within seconds when the simulator is killed.

---

## 9.5 M2 Data pipeline complete

**Goal:** every DP- requirement works; the kit-health page shows it.

| # | Task | Design |
|---|---|---|
| 2.1 | QC per measurement: range, spike with re-anchoring, stuck, cross-sensor, DHT11 fallback, neighbour (≥ 3 kits), external; `reading_qc_flag` | 05 §5.4 |
| 2.2 | Derived features, rolling windows in memory, late-reading recomputation (≤ 3 h) | 05 §5.5 |
| 2.3 | Continuous aggregates `reading_15m`, `reading_1h`; views `series_15m`, `series_1h` (end-labelled, coverage); policies (not in the demo database, DD107) | 03 §3.6.2, 05 §5.7 |
| 2.4 | Maintenance notices (in `alerts`, minimal process for now) | 05 §5.4.9 |
| 2.5 | API: readings (rows + columnar), kit health, status history, QC flags, rejected messages, system status | 02 §2.6.4–2.6.5 |
| 2.6 | Simulator fault overlays (demo mode only) and the demo database + `-Demo` | 11 §11.3, §11.5 |
| 2.7 | Kit-health page | 10 §10.4.4 |

**Tests:** TST-11 complete (QC, features, conversions, late data); Scenarios 5 and 6 as end-to-end tests on the demo clock; `ingest` stopped while 2 000 readings are published → all stored.

**Done when:** every fault overlay produces the expected flag, notice or rejection on the kit-health page.

---

## 9.6 M3 Configuration, onboarding and Open-Meteo

**Goal:** a site can be created, onboarded and configured; thresholds resolve correctly for every kit.

| # | Task | Design |
|---|---|---|
| 3.1 | Extend the M1 configuration core: onboarding-computed defaults and their source, validation warnings | 04 §4.2, §4.4 |
| 3.2 | Config API: schema, site/kit/recipients CRUD with `base_version`, effective values, validate, history, import/export endpoints | 02 §2.6.8, 04 §4.6 |
| 3.3 | `config.changed` reload in every process | 01 §1.3.3 |
| 3.4 | `worker` process: APScheduler on weather time, Open-Meteo forecast fetch (hourly, `past_days=7`), `external_forecast*` | 05 §5.8.1, 07 §7.9 |
| 3.5 | Onboarding job: paced history download (DD118), normals, wet-hour rain-burst threshold with 20 mm/h floor (DD104), labels, top-10 events, progress events; back-tests come in M9 | 04 §4.5 (req), 05 §5.8.2, 03 §3.8 |
| 3.6 | Normal-offset job (DD105; runs only once 28 days of kit data exist) | 07 §7.9 |
| 3.7 | First-run wizard (admin → site → kits → recipients → onboarding progress) | 10 §10.6 |

**Tests:** TST-10 complete (hypothesis property tests); TST-13 config conflict; onboarding against a fake Open-Meteo returning `429` → resumes; Scenario 8 (threshold change).

**Done when:** `start.ps1 -Seed config/example-site.yaml` creates the site, onboarding finishes in a few minutes, and `/config/effective` shows the right value and source for every key.

---

## 9.7 M4 Forecast worker (with test models)

**Goal:** requirements phase 4: "forecast page shows 72 h charts", using the tiny test model set until T8 delivers.

| # | Task | Design |
|---|---|---|
| 4.1 | Model registry loading with feature contract (checked against `ews.ml.features` from M1) and checksums, fallback rules | 06 §6.5, §6.11, 07 §7.6 |
| 4.2 | Tiny test model set in `models/test/` with the real feature contract | 12 §12.2 |
| 4.3 | Persistent inference child process with machine-time timeout (DD60, DD117) | 07 §7.2 |
| 4.4 | Rolling hours, gap filling, pseudo-observations, `skipped` reasons | 07 §7.3–7.4 |
| 4.5 | Probabilities per event/level/window, **D0 windows** with measured values (DD99, DD115, DD124), calibration maps, classifier rules (DD59, DD121) | 07 §7.5, 06 §6.8.4 |
| 4.6 | Storage with `COPY`, `forecast.run_completed`; integer hypertables (or plain tables first, 05 §5.4) | 07 §7.7, 03 §3.7 |
| 4.7 | Forecast API (run-addressed, immutable caching) and forecast page with charts and probability table | 02 §2.6.6, 10 §10.4.2, 13 §13.3.3 |

**Tests:** rolling-hour and D0 unit tests; DD57/DD59/DD121 tests; 100 runs with 5 kits ≤ 60 s p95 (NFR-02).

**Done when:** a run every 15 minutes appears on the forecast page with P10–P90 bands and probabilities.

---

## 9.8 M5 Alert engine

**Goal:** requirements phase 5: "simulated storm triggers correct alerts". The largest and most important milestone.

Build it **test-first from the transition tables**, in this order, each step with its tests green before the next:

| # | Step | Design |
|---|---|---|
| 5.1 | Transition-table test harness with the fake clock; alert tables (`alert`, `alert_change`, `live_condition`, `forecast_condition`, markers) | 08 §8.13, 03 §3.9, 12 §12.3 |
| 5.2 | Live path for one kit: gust (10-min median), rain intensity, rain 24 h, heatwave (30-min median, normal + offset, per-day end D35/DD106, no-data rule DD120); clear-down; offline = unknown | 08 §8.6 |
| 5.3 | Squall rule on the 1-minute mean wind (DD100) and precursors | 08 §8.6.2 |
| 5.4 | Forecast path: episodes, hysteresis, upgrade fast / downgrade slow, far-event agreement, window end, stale forecast, `updated` with whole-hour windows (DD101, DD119) | 08 §8.5 |
| 5.5 | Take-over (DD103) and the Live-heatwave block (DD114) | 08 §8.7, §8.5.3 |
| 5.6 | Multi-kit combination (median, worst first; majority and two-kit agreement later) | 08 §8.8 |
| 5.7 | Commands: suppress, unsuppress, manual raise/clear; API wait-then-202 | 08 §8.9–8.10, 02 §2.5 |
| 5.8 | Notification decisions: addressees, sticky audience (DD102), cooldown, end always sent; outbox rows | 08 §8.11 |
| 5.9 | Threshold changes (`threshold_changed`), restart catch-up and idempotence | 08 §8.12–8.13 |
| 5.10 | Alerts API (list, detail, history, acknowledge, notes, advice, commands) + WebSocket `alert.*` | 02 §2.6.7 |

**Tests:** TST-12 complete (every transition row); TST-13 acknowledgement race and command ordering; Scenarios 2, 3, 4, 7 as **fake-clock integration tests** (seconds) and as end-to-end tests with fixture runs on the demo clock, the multi-day ones marked `slow` (AN-47).

**Done when:** all scenario tests pass and killing `alerts` mid-stream produces no duplicate change or email after restart.

---

## 9.9 M6 Notifications

**Goal:** requirements phase 7: "alert emails arrive for create/upgrade/cancel".

| # | Task | Design |
|---|---|---|
| 6.1 | `mailer`: claim with `SKIP LOCKED`, supersede check, render, SMTP send, attempts, retries/backoff (machine time), crash recovery | 09 §9.2, §9.6–9.7 |
| 6.2 | Templates (plain text + HTML) for both audiences, maintenance, invite, reset; subjects with whole-hour windows; "open on the control PC" | 09 §9.3–9.4, §9.12 |
| 6.3 | Threading headers, `[DEMO]` prefix | 09 §9.8 |
| 6.4 | Notifications admin API and page; failed-email banner | 02 §2.6.10, 10 §10.2 |

**Tests:** golden file per template × change kind; Mailpit-based Scenario 2 email assertions; DD72 threading; DD73 superseded; two mailers → no double send.

**Done when:** every email of Scenario 2 arrives in Mailpit with exactly the subjects of 09 §9.3, as one thread per alert.

---

## 9.10 M7 Users, permissions and audit

| # | Task | Design |
|---|---|---|
| 7.1 | Invite, accept, resend, reactivate, deactivate, roles, last-admin and own-role rules, lockout, password reset | 02 §2.2, §2.6.1–2.6.3 |
| 7.2 | Audit log for every write, with `reason` where required | 02 §2.6.11, DD20 |
| 7.3 | Rate limits | 02 §2.1, NFR-03 |
| 7.4 | Admin pages: users, audit, configuration editor (effective values, validation, version conflict dialog, import/export) | 10 §10.4.5–10.4.6 |
| 7.5 | Email preferences: profile API and page (tables and defaults exist since M1) | 02 §2.6.2 |

**Tests:** TST-16 generated from OpenAPI and the role matrix; lockout with the fake clock; token expiry/reuse; TST-13 config conflict through the UI (Playwright).

**Done when:** "a kit can be added from the UI" (requirements phase 8) and the permission suite covers every endpoint.

---

## 9.11 M8 Dashboard pages complete

| # | Task | Design |
|---|---|---|
| 8.1 | Alert banner on every page, alerts list and detail with operator panel, raise-alert dialog, acknowledge flow from email links | 10 §10.3, §10.4.3 |
| 8.2 | Live dashboard complete: all kits, site status, probability strip, squall precursors | 10 §10.4.1 |
| 8.3 | Frontend data architecture: event router patching the cache, ring buffers, frame scheduler, critical-first loading; single socket per tab first, leader tab later (05 §5.4) | 13 |
| 8.4 | Error handling, reconnect with backoff, reload after reconnect | 10 §10.7–10.8, 02 §2.7.1 |

**Tests:** Vitest for event router and live store; Playwright for banner, acknowledgement race and reconnect; frontend budgets.

**Done when:** all "M" pages of requirements 07 §7.2 work on the demo clock at 60× without dropped frames.

---

## 9.12 M9 Real models, reports, demo and hardening

| # | Task | Design |
|---|---|---|
| 9.1 | Load the real models from T8 into `models/`; run with them; compare with the test set | 06 §6.11, 07 §7.6 |
| 9.2 | Back-tests during onboarding; model-reports API and page (accuracy, hazard skill, back-tests, importance, live verification) | 02 §2.6.12, 10 §10.4.7 |
| 9.3 | Demo snapshot script and `-Demo -Reset` restore (DD108, DD116); `demo.yaml` script for Scenario 9 | 11 §11.3.1, §11.8 |
| 9.4 | **Alert-volume dry run** with the batch harness (DD126): live path over a full real year, forecast path over two months at the real cadence; agree targets with the owner; tune defaults (DD112) | 12 §12.6 |
| 9.5 | Non-functional checks of 12 §12.6 (NFR-01 … NFR-08) | 12 §12.6 |
| 9.6 | Backup/restore scripts and a practice restore (DD97, DD98) | 14 §14.3 |
| 9.7 | Map page (could) if time allows | 10 §10.2 |
| 9.8 | Report material: architecture, results vs pass marks (DD111), limitations (06 §6.14, AN-17, AN-31, AN-35) | 06 §6.9, §6.14 |

**Done when:** Scenario 9 runs from `start.ps1 -Demo -Reset` without errors, all suites of `test.ps1` pass, and the setup guide has been followed once on a clean machine.

---

## 9.13 ML track (Colab, in parallel)

| # | Step | Notebook | Done when |
|---|---|---|---|
| T1 | Download ERA5 history and archived forecasts for 24 locations, paced by weighted calls over several days (DD118) | `01_download` | Manifest with checksums and real archive start dates |
| T2 | Prepare Parquet, global scaler, normals, wet-hour percentiles, labels | `02_prepare`, `03_normals_labels` | Label counts per event printed; events with < 30 positives listed |
| T3 | Baselines: persistence, climatology, Open-Meteo, LightGBM quantile, Chronos-Bolt | `04_baselines` | Metrics on validation and test |
| T4 | TFT-base: search on a subset, final run with per-epoch checkpoints (DD113) | `05_tft_base` | Pass mark vs persistence and climatology met |
| T5 | TFT-NWP fine-tune | `06_tft_nwp` | Not worse than Open-Meteo |
| T6 | Event classifiers (base, NWP) | `07_event_classifiers` | One per event with ≥ 30 positives |
| T7 | Calibration and selection on validation | `08_calibrate_select` | `selection.json` |
| T8 | Test once, held-out locations, back-tests, explainability, export to `models/` | `09_evaluate`, `10_export` | Registry entries load in `worker` (feature contract OK) |

**Hand-over:** the shared feature and label code in `backend/ews/ml/` is built in M1 (task 1.0b) and imported by the notebooks from T2 on, so training and live inference compute identical inputs (DD50). T1 (downloads) can start in M0.

## 9.14 Real kit (when the hardware is ready)

| Step | Design |
|---|---|
| Add the kit in configuration (zone, position, elevation, calibration offsets from the builders) | 14 §14.1.4 |
| Create its MQTT user; firewall rule for 1883 on private networks | 14 §14.1.4 |
| Watch kit health for a day: QC flags, clock offset, rejected messages | 10 §10.4.4 |
| After 28 days: normal offset appears (D33); after 4–8 weeks: fine-tuning (ML-06) | 06 §6.10, 07 §7.9 |

## 9.15 Definition of done (every task)

| Check | Rule |
|---|---|
| Tests | Unit/integration tests for the task are written and pass in `test.ps1` |
| Design | Behaviour matches the cited design section; any difference is first written into the design with a new D/DD number |
| Logging | New events use stable `event` codes (14 §14.2) |
| Traceability | Requirement IDs appear in test names or docstrings (12 §12.8) |
| Demo | `start.ps1` still starts the whole system |

## 9.16 Progress checklist

| Milestone | State |
|---|---|
| M0 Foundations + week-1 checks | Not started |
| M1 Skeleton | Not started |
| M2 Data pipeline | Not started |
| M3 Configuration and onboarding | Not started |
| M4 Forecast worker | Not started |
| M5 Alert engine | Not started |
| M6 Notifications | Not started |
| M7 Users, permissions, audit | Not started |
| M8 Dashboard pages | Not started |
| M9 Real models, reports, demo | Not started |
| T1–T8 ML track | Not started |
| Real kit | Waiting for hardware |
