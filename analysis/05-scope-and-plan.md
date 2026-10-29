# 5. Scope and Plan

How big the designed system is, which parts lie on the critical path, what to prove in the first week before building on it, and which parts can start in a simpler form without breaking a requirement. This document does not change the scope; it helps decide the order of work. The build order itself stays as in [requirements 08 §8.5](../requirements/08-non-functional-and-testing.md).

## 5.1 Size of the design

| Part | Count | Source |
|---|---|---|
| Backend processes | 5 (+ inference child process) | [design/01](../design/01-architecture.md) |
| Database tables | 62 after the fixes (+ views, 2 continuous aggregates, 7 hypertables) | [design/03](../design/03-database-schema.md) |
| REST endpoints | 75 | [design/02](../design/02-api.md) |
| WebSocket event types | 15 | [design/02 §2.7.3](../design/02-api.md) |
| Configuration keys | ≈ 130 | [design/04](../design/04-configuration.md) |
| Frontend routes | 17 | [design/10 §10.2](../design/10-ui.md) |
| Training notebooks | 10; 6 model families (TFT ×2, LightGBM classifiers ×2, LightGBM quantile, Chronos-Bolt) + 3 simple baselines | [design/06](../design/06-ml-training.md) |
| Simulator | Replay, scenario language, 12 fault types, multi-kit spatial model, demo clock | [design/11](../design/11-simulator.md) |
| Automated scenario tests | 9 end-to-end + table-driven alert tests + generated permission tests | [design/12](../design/12-testing.md) |

This is a large system for a project. It is well specified, which saves time, but there is little slack. Order the work so that **a working demo exists early** and every later step makes it better, rather than finishing each layer completely before the next one starts.

## 5.2 Critical path

```
Week-1 checks (5.3)
   │
   ├─► Phase 1 skeleton: simulator → MQTT → ingest → DB → live chart        ──┐
   │                                                                          │
   ├─► Phase 3 training (parallel, Colab): download → baselines → TFT-base     │
   │        → TFT-NWP → classifiers → calibrate → export                      │
   │                     (longest, most uncertain; start early)               │
   │                                                                          ▼
   │                        Phase 4 forecast worker ◄── tiny test model set (12 §12.2)
   │                                   │
   │                        Phase 5 alert engine  ◄── fixture runs, so it does not wait for training
   │                                   │
   │                        Phase 6–7 pages, emails
   │                                   │
   └───────────────────────► demo snapshot (AN-26), alert-volume dry run (AN-16), report
```

| Observation | Consequence |
|---|---|
| Training is the longest and least predictable task | Start downloads in week 1; the backend never waits for it, thanks to the tiny test model set |
| The alert engine is the heart of the system and has the most rules | Build it test-first from the transition tables (DD94), with fixture runs, before the real models exist |
| ML-06 fine-tuning needs 4–8 weeks of **real** kit data | Its date depends on the hardware team; if the kit arrives late, ML-06 (priority S) may not fit, and the report says so |
| The demo depends on a prepared snapshot | Build the snapshot script with the first end-to-end run, not at the end |

## 5.3 Week-1 checks

Short experiments that prove the riskiest assumptions before anything is built on them. Each has a clear pass mark and a fallback.

| # | Check | Pass when | If it fails | Finding |
|---|---|---|---|---|
| 1 | Install PostgreSQL + TimescaleDB on the demo laptop; create a hypertable, a continuous aggregate (`materialized_only = false`), compression, retention and an integer hypertable | All five work | Plain PostgreSQL partitions + `worker` refresh behind the `series_*` views | AN-30 |
| 2 | Download one location's Open-Meteo **Previous Runs** data for all six variables | Start date per variable known and written down | Move stage-2 validation/test to the covered period | AN-14 |
| 3 | Darts TFT on CPU: 2 locations, 5 targets, static + past + future covariates, 9 quantiles, 1 epoch; save, reload with the same pinned versions, predict | Runs end to end, reload gives identical output | Reduce to fewer targets per model, or pin other versions | AN-15 |
| 4 | Mosquitto: kit user with ACL, last will on hard disconnect, persistent session for `ingest` with 2 000 queued messages | `offline` arrives at once; all 2 000 messages delivered | Adjust `mosquitto.conf` | AN-28 |
| 5 | Demo clock: simulator publishes `sim/clock`, one process follows it, a 15-minute APScheduler job fires every 15 s at 60× | Job fires on demo time | Custom scheduler loop on the clock abstraction instead of APScheduler triggers | DD82 |
| 6 | Notebook `03_normals_labels` on 3 locations: all-hours and wet-hours p99 hourly rain, normal maximum | Numbers printed | — (input for the owner decision) | AN-11, AN-12 |

## 5.4 Parts that can start simpler

These parts can be built first in a simpler form that still meets the requirement, and upgraded to the full design if time allows. Nothing here removes a "must" requirement.

| Designed | Simpler first version | Still meets | Upgrade later |
|---|---|---|---|
| One WebSocket per browser via leader tab (DD29) | One socket per tab (already the documented fallback, [13 §13.3.1](../design/13-frontend-performance.md)) | WEB-24, NFR-01 | Leader election, one alert sound per browser |
| IndexedDB persistence of runs (DD35) | In-memory query cache only | All | Persist when everything else works |
| Degraded polling mode (DD34) | Reconnect with backoff only | NFR-04 | Polling fallback |
| Chronos-Bolt shadow runs in the worker (DD61) | Chronos-Bolt compared **offline** in notebook 04 only | ML-03, D9 (comparison in the report) | Live shadow runs (phase 2) |
| Neighbour QC check (DP-24, S) | Not run (needs ≥ 3 kits; one kit exists) | M requirements | When TST-04 multi-kit is built |
| `majority`, `two_kit_agreement` combination rules | `median` and `worst` only (the AL-14 defaults) | AL-14 | The other two values of `combine_*` |
| Bulk invite (WEB-07, C), map (C) | Not built | M and S requirements | If time allows |
| Forecast tables as integer hypertables (DD25) | Plain tables with the same keys | AL-12 | Convert with `create_hypertable(… migrate_data => true)` once months of runs exist |

Parts that should **not** be simplified, because the requirements and the safety of the alerts depend on them: the alert state machine and its stored timers, the email outbox with dedup, strict contract validation, backend permission checks, and the separation of demo data.

## 5.5 Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Too many alerts with real kit data | High | High (alerts ignored, poor demo) | Fix AN-03, AN-11, AN-12; alert-volume dry run (AN-16) |
| Demo starts without forecasts | High | High | Demo snapshot (AN-26), demo policies (AN-25) |
| TFT training interrupted on Colab | Medium | Medium | Checkpoints, tuning on a subset (AN-15) |
| Lead-correct archives cover less than planned | Medium | Medium | Week-1 check 2 (AN-14) |
| TimescaleDB not installable on the laptop | Low–medium | High | Week-1 check 1, fallback (AN-30) |
| Real kit arrives late | Unknown (outside the project) | Medium (ML-06, phase 2 of the build order) | Everything runs on the simulator; state in the report |
| Overall size of the system | Medium | High | Early working demo, simpler first versions (5.4) |
