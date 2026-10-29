# 10. Fourth Review

A fourth pass, done 2026-10-30, this time checking the **implementation plan** ([09](09-implementation-plan.md)) against the design: is every milestone buildable with only what earlier milestones deliver, and are the planned tests feasible in the time they need? The design documents themselves showed no new issues. The plan had five ordering and timing problems, all fixed the same day.

| ID | Finding | Severity | Fixed by |
|---|---|---|---|
| AN-44 | M1 cannot accept readings: kits must be configured, but configuration arrives in M3 | Medium | Plan: config core + YAML seed moved to M1 |
| AN-45 | The ML track needs the shared feature code early; the plan builds it in M4 | Medium | Plan: shared feature and label code in M1 |
| AN-46 | The alert-volume dry run of a year through the simulator would take days | Medium | DD126 (batch harness) |
| AN-47 | Multi-day scenario tests take about an hour each at 120× | Low | Test levels split (12 §12.2) |
| AN-48 | The alert engine (M5) needs user email preferences that the plan builds in M7 | Low | Plan: tables and defaults in M1, UI in M7 |

---

## AN-44 M1 cannot accept readings: kits must be configured first — Medium

**Where:** `ingest` rejects messages from a kit that is not configured (`unknown_kit`, [05 §5.2.1](../design/05-data-pipeline.md)), and it needs the kit's resolved configuration for calibration, mm per tip and elevation ([05 §5.3](../design/05-data-pipeline.md)). The plan builds the resolver, validator and YAML import in **M3**, after M1 and M2.

**What happens:** in M1 there is no way to create the site and the kit, so every simulated reading is rejected and the M1 "done when" cannot be reached. The same blocks M2's demo database, which needs `config/demo-site.yaml` imported.

**Fix:** move the **configuration core** into M1: resolver, validator, versioned storage and YAML import used by `start.ps1 -Seed` (no API and no UI yet). M3 keeps the config API, history, export, the wizard and onboarding. The M0 migration also creates `app_user`, because `config_version.created_by` refers to it.

---

## AN-45 The ML track needs the shared feature code early — Medium

**Where:** feature and label code is shared: it lives in `backend/ews/ml/` and the notebooks import it (DD10, DD50, [06 §6.1](../design/06-ml-training.md)). The plan builds it in M4 task 4.1 and lets T2 use "a frozen copy" until then.

**What happens:** T2 (prepare, normals, labels) starts right after the downloads, long before M4. With a frozen copy, training features and live features may drift apart, which is exactly what DD50 is meant to prevent, and T2–T8 would have to be re-run once the real module exists.

**Fix:** build `ews.ml.features` and `ews.ml.labels` (including the heat-index function, hazard labels, wet-hour percentile, end-labelled hourly series) as an **M1 task**, test-first with golden values, so the ML track uses the real module from the start. M4 adds only registry loading and inference.

---

## AN-46 The alert-volume dry run of a year would take days — Medium

**Where:** DD112: "a real year replayed through `ingest` and `alerts`" with the simulator at high speed ([12 §12.6](../design/12-testing.md)).

**What happens:**

| Part | Cost through the live system |
|---|---|
| Live path, one year at 120× | 365 days ÷ 120 ≈ **3 days** of real time |
| Forecast path, 96 runs/day × 365 | ≈ 35 000 runs × 10–20 s ≈ **4–8 days** of CPU |

Not feasible before a demo, and any default change would need a re-run.

**Fix (DD126): a batch harness** that runs the same `ingest` pipeline functions and alert-engine code in one process with the **fake clock**, reading minute data generated from ERA5 (the simulator's replay generator, used as a library inside the harness, without MQTT and without the demo clock):

| Part | Scope | Expected time |
|---|---|---|
| Live path | Full year, all live rules | Minutes to an hour |
| Forecast path | Two months with the real 15-minute cadence (one wet month, one hot month), real or test models | Hours |
| Output | Alerts and emails per week, hazard and level; compared with the owner's targets | Report table |

The simulator itself stays independent of `ews` (DD7); only the harness, which is a test tool in `backend/tests/`, imports both.

---

## AN-47 Multi-day scenario tests take about an hour each — Low

**Where:** end-to-end tests run on the demo clock at 60–120× "so a 1-hour scenario runs in about a minute" ([12 §12.2](../design/12-testing.md)); Scenario 3 covers Tuesday to Saturday.

**What happens:** five simulated days at 120× is about **one hour** of real time per run, too slow for every test run.

**Fix:** two levels. The full behaviour of multi-day scenarios (3, and the multi-day parts of 4) is tested as **integration tests with the fake clock** (seconds). The end-to-end versions on the demo clock are marked `slow` and run before a milestone is closed and before the demo, not on every `test.ps1` run.

---

## AN-48 The alert engine needs email preferences that the plan builds in M7 — Low

**Where:** M5 task 5.8 selects operator addressees by `user_alert_preference` ([08 §8.11](../design/08-alert-engine.md)); the plan adds email preferences in M7.

**Fix:** the preference tables are created in M1 (with users), with defaults for every user (enabled, all hazards and types, minimum level yellow, maintenance notices on). M7 adds only the profile API and page.

---

## Checked and sound

| Topic | Result |
|---|---|
| M4 after M3 (normals and thresholds before forecasts) | Correct |
| M5 with fixture runs before real models | Correct; no dependency on T8 |
| M6 after M5 (outbox rows exist) | Correct |
| Back-tests in M9 (need models) | Correct |
| Demo snapshot build time | Onboarding ≈ 6 min + 7 simulated days at 120× ≈ 1.4 h, once per rebuild: acceptable |
| Every design section cited by the plan exists | Yes |
