# 7. Forecast Worker

The 15-minute forecast run inside `worker`: schedule, inputs, the rolling-hour input series, gap handling, inference, exceedance probabilities, storage, timing and failure behaviour. It also lists every other scheduled job of `worker`. Requirements: AL-07, AL-12, ML-05, ML-08, ML-09, NFR-02. Models: [06](06-ml-training.md). Tables: [03 §3.7](03-database-schema.md).

Decisions referenced: DD56–DD61 in [decisions.md](decisions.md).

## 7.1 Schedule

| Item | Rule |
|---|---|
| Issue times | Every 15 minutes on the UTC grid: :00, :15, :30, :45 (`forecast_interval_min`) |
| Start | `issue_time + forecast_start_offset_s` (120 s): the grace period (DP-08) has passed, so the 15-minute bucket ending at the issue time is complete |
| Data cut-off | Only readings with `ts ≤ issue_time` are used, even if newer ones exist when the run starts |
| One at a time | `ews.common.clock.every()` on weather time (DD130): one run at a time; slots missed while a run was busy are coalesced (only the latest one still within the start grace runs, older ones are skipped, DD58); start grace 300 s (machine time, DD117) |
| Missed runs (DD58) | Not back-filled. If a slot cannot start within 5 minutes (worker down, previous run still busy), it is skipped and logged; the next run uses the next issue time. Missing runs show as gaps in `/forecast/runs`; the alert engine counts only runs that exist ([08](08-alert-engine.md)) |
| Before onboarding is complete | No runs (normals are an input; [01 §1.4.5](01-architecture.md)) |

## 7.2 Run steps

```
 0 create forecast_run (status running, issue_time)
 1 resolve config for the site and every enabled kit (record versions → forecast_run_config)
 2 choose models from registry.json (active or fallback, §7.6)
 3 per kit: build the rolling-hour input series (§7.3) and fill gaps (§7.4)
 4 inference child process: TFT for all kits in one batch → 9 quantiles × 5 variables × 72 steps
 5 event classifiers (LightGBM) for the selected events
 6 probabilities per kit, event, level and window (§7.5), calibrated
 7 one transaction: forecast_value (P10/P50/P90), forecast_probability, forecast_run_model,
                    forecast_run_kit, run status completed
 8 NOTIFY forecast.run_completed
```

Steps 3–6 run in a **persistent inference child process** (DD60): it loads the models once at start-up and on `models.reload`, receives the prepared inputs over a pipe and returns outputs. If it crashes or exceeds `forecast_timeout_s` (300 s, always real seconds, also in demo mode, DD117) it is killed and restarted, and the run is marked `failed`. The scheduler, the Open-Meteo fetch and other jobs keep running in the main process.

## 7.3 Rolling hours (DD56)

The TFT is an hourly model, but every 15-minute run must see new data (otherwise four runs per hour would be copies, and "downgrade after 3 lower runs" (AL-09) could fire on repeats). Each run therefore uses **hours that end at its issue time**:

```
issue 09:15 → encoder steps  … | 07:15–08:15 | 08:15–09:15 |      (168 steps)
              decoder steps  | 09:15–10:15 | 10:15–11:15 | …     (72 steps, target times 10:15, 11:15, …)
issue 09:30 → encoder steps  … | 07:30–08:30 | 08:30–09:30 |
```

| Input | How a rolling hour is built |
|---|---|
| Kit observations | From `series_15m` ([05 §5.7](05-data-pipeline.md)): the 4 buckets ending at the hour's end. Mean of means (equal bucket length), max of gust maxima, sum of rain, circular mean of wind direction; NULL if fewer than 3 of the 4 buckets are valid |
| Hour of day | Fractional (e.g. 9.25), as sin/cos — the same encoding as training, where it was always whole |
| Normal max temperature | Of the target's local day |
| Open-Meteo forecast | From the latest fetch: instantaneous variables (temperature, humidity, pressure) interpolated linearly to the rolling hour's end; hourly sums (rain) split proportionally between the two clock hours it overlaps (e.g. 09:15–10:15 = ¾ of the 10:00 value + ¼ of the 11:00 value); gust = the larger of the two overlapping hourly maxima |

- The model was trained on whole clock hours; rolling hours have the same statistics, so no retraining is needed. The report notes this.
- Target times are stored as they are (10:15, 11:15, …); charts and the API simply show the stored times. Verification compares them with rolling-hour observations built the same way.
- Calendar windows (24 h rain day ending 03:00 UTC, heatwave local days, [06 §6.6](06-ml-training.md)) take the steps whose hour **ends** inside the window; the up-to-45-minute misalignment at the window edges is accepted.

## 7.4 Gaps and new kits (DD57)

The encoder needs 168 rolling hours per kit.

| Situation | Handling | Kit status in this run |
|---|---|---|
| All hours present | — | `ok` |
| Gaps of ≤ 3 h (`gap_interpolate_max_h`) | Linear interpolation (rain: 0 is **not** assumed; the gap's rain is interpolated from neighbouring hours only if both sides are dry, otherwise filled as below) | `ok` |
| Longer gaps, or a new kit with < 7 days of history | Filled with **pseudo-observations** from Open-Meteo: the past hours of the latest fetch (fetched with `past_days=7`, [05 §5.8.1](05-data-pipeline.md)), corrected by the kit's bias (median kit − Open-Meteo difference per variable over the last 7 days, when ≥ 24 overlapping hours exist) | `degraded` |
| Long gap or short history but **no Open-Meteo fetch** to fill it (e.g. demo mode, where fetching is off) | Kit not forecast; reason `no_fill_data` recorded. The demo avoids this by starting from a snapshot with ≥ 7 days of readings (DD108) | `skipped` |
| No valid kit data in the last 24 h (`kit_skip_no_data_h`) | Kit not forecast | `skipped` |
| Kit disabled | Not forecast | — |

- `degraded` forecasts are stored and used normally; the UI marks them ("forecast partly based on Open-Meteo data") and the run detail lists filled hours per kit.
- `skipped` kits get no forecast probabilities, so the alert engine raises no forecast alerts for that zone; live alerts and site alerts based on other kits continue ([08](08-alert-engine.md)).
- Per-kit status, coverage and filled hours are stored in `forecast_run_kit` ([03 §3.7.2](03-database-schema.md)).

## 7.5 Probabilities

For every forecast kit, the run produces calibrated probabilities for each event, level and window of [06 §6.6](06-ml-training.md):

| Event | Levels | Windows | Rows per kit |
|---|---|---|---|
| `gust` | yellow, orange, red | 3 h blocks 0–24 h (8), 6 h blocks 24–72 h (8) | 48 |
| `rain_intensity` | `rain_intensity_level` | 3 h blocks 0–6 h (2) | 2 |
| `rain_24h` | yellow, orange, red | rain days D0–D2 (3) | 9 |
| `heatwave` | orange (heatwave), red (severe) | local days D0 (rest of today)–D3 (4) | 8 |
| | | | **≈ 67** |

**Windows that have already started (D30, DD99).** For the current rain day (D0) and today's heatwave window (D0), what has already been measured counts:

| Window | Probability |
|---|---|
| Rain day D0 (since 03:00 UTC) | Measured rain since the window start (`series_15m`, valid buckets) + forecast for the remaining hours; P = 1 if the measured amount already reaches the level's threshold. Always computed this way, from the TFT-derived probability for the remaining hours, even when the registry selects a classifier for `rain_24h`; classifiers are used only for D1–D2 (DD115) |
| Heatwave D0 (today, local) | Daily max = max(measured maximum today, forecast for the remaining hours). "Measured maximum" is the **highest 30-minute median temperature** of the local day, the same measure as the Live heatwave, so one hot minute does not count (DD124) against normal + offset (D33); P = 1 if the measured maximum already meets the rule. Classifiers are trained for D1–D3 only, so D0 always uses the TFT-derived probability |

Without this, the probability of a day that is already under way falls towards zero as the day runs out, and forecast alerts would be cancelled while the event is happening.

Source of each probability (DD59):

```
for each (event, level):
    threshold = effective value for this kit (config, at run time)
    model     = selected model for event_level in registry (or its fallback, §7.6)
    if model is a classifier AND threshold == the threshold it was trained for
                             AND the window has not started yet (not D0, DD115)
                             AND (event is not heatwave OR the kit's normal offset is 0, DD121):
        p = calibrate(classifier(features, window))
    else:
        p = calibrate(raw score from the TFT quantiles at this threshold)      (06 §6.8.4)
    store p, threshold, window; record the model actually used in forecast_run_model
```

Classifiers are trained for the default thresholds (e.g. gust ≥ 50 km/h). When a site or kit overrides a threshold (local risk, e.g. Sports Ground orange at 35 km/h), the classifier no longer answers the right question, so the TFT-derived probability is used, which works for any threshold. The same applies to heatwave classifiers once a kit has a non-zero normal offset (D33): they were trained against the plain ERA5 normal (DD121). Calibration maps were fitted at the default thresholds; applying them to nearby thresholds is an approximation, noted on the model-reports page.

Site-level combination (median / worst kit, AL-14) is **not** done here; the alert engine combines the per-kit probabilities ([08](08-alert-engine.md)).

## 7.6 Model choice per run

| Condition | Model used |
|---|---|
| Normal | Active model per variable and per event from `registry.json` |
| Latest Open-Meteo fetch older than `nwp_max_age_h` (6 h) or missing | The **fallback** (stage-1 / base) model for every output whose active model needs NWP inputs |
| Active model failed to load (feature contract or checksum mismatch, [06 §6.11](06-ml-training.md)) | Fallback; admin warning in `/system/status` |
| Fallback also unavailable | Run `failed` for those outputs; earlier runs remain the latest valid forecast |
| `shadow_chronos_enabled` | Chronos-Bolt runs **once per hour** (at :00) after the main outputs are committed, for comparison only (phase 2); its outputs are stored as a separate run marked `shadow` and never used for alerts |

## 7.7 Storage

| Table | Rows per kit per run | Notes |
|---|---|---|
| `forecast_value` | 5 variables × 72 steps = 360 | P10/P50/P90 only (DD51) |
| `forecast_probability` | ≈ 67 | with the threshold applied (N4) |
| `forecast_run_model` | ≈ 25 per run | which version produced each output |
| `forecast_run_config` | 1 + number of kits | config versions used (CFG-05) |
| `forecast_run_kit` | 1 | status `ok` / `degraded` / `skipped` / `failed`, coverage, filled hours, NWP used |

All rows of a run are written with `COPY` in one transaction, then the run is set to `completed` and `forecast.run_completed` is sent. A run that fails before commit leaves only its `forecast_run` row with status `failed` and the error. Consumers (alert engine, API) only read `completed` runs; the newest one supersedes older ones for overlapping times (AL-07).

## 7.8 Timing budget (ML-08, NFR-02)

Estimate for 5 kits on a laptop CPU:

| Step | Time |
|---|---|
| Config, registry, inputs from the database | 1–2 s |
| Rolling hours, gap filling, features | ≈ 1 s |
| TFT inference, all kits in one batch | 3–10 s |
| Event classifiers | < 1 s |
| Probabilities and calibration | < 1 s |
| Write (`COPY` ≈ 2 150 rows) | < 1 s |
| **Total** | **≈ 10–20 s** (target ≤ 60 s; hard timeout 300 s; slot 900 s) |
| Chronos-Bolt shadow (hourly, if enabled) | + 20–40 s, after the main run |

The run's duration is stored (`started_at`, `finished_at`) and shown on the system status; three runs in a row above 60 s raise an admin warning.

## 7.9 Other `worker` jobs

| Job | When | What |
|---|---|---|
| Forecast run | Every 15 min, +120 s | This document |
| Open-Meteo fetch | Hourly at :05 | [05 §5.8.1](05-data-pipeline.md) (now with `past_days=7`) |
| Onboarding | On `onboarding.requested` | [04 §4.5 of the requirements](../requirements/04-configuration.md), [05 §5.8.2](05-data-pipeline.md); back-test inference runs in small batches **between** forecast runs so it never delays them |
| Live verification | Daily at 01:00 site time | Previous day's runs vs rolling-hour observations → `verification_daily` |
| Heat normal offset | Daily at 01:15 site time | Per kit, once ≥ `heat_normal_offset_min_days` (28) complete local days exist: download ERA5 daily maxima for those days (Open-Meteo Archive, `models=era5`, ≈ 5 days latency), store median(kit daily max − ERA5 daily max) in `normal_offset` (D33, DD105); recomputed daily over the last 90 days |
| Neighbour spread | Daily at 01:30 | `qc_neighbour_spread` (DP-24) |
| Retention and cleanup | Daily at 02:00 | Rejected messages, sessions, tokens, old history datasets ([03 §3.14](03-database-schema.md)); TimescaleDB policies do the rest |
| Model registry reload | `python -m ews.worker models reload` | Re-read `registry.json`, verify, register new versions, restart the inference child |
| Heartbeat | Every 15 s | `process_heartbeat` |

## 7.10 Failure behaviour

| Failure | Effect |
|---|---|
| Inference child crash or timeout | Run `failed`; child restarted; next slot runs normally |
| Database unavailable at write | Run `failed`; retried at the next slot, not back-filled |
| One kit's inputs fail | That kit `failed` in `forecast_run_kit`; the run completes for the other kits |
| No completed run for `forecast_stale_after_runs` (4) slots | Dashboards show "forecast stale"; the alert engine's rule for stale forecasts applies ([08](08-alert-engine.md)) |

## 7.11 Requirement coverage

| Requirement | Section |
|---|---|
| AL-07 | §7.1, §7.3 (every run has new data), §7.7 (newest supersedes) |
| AL-12, ML-09 | §7.7 |
| ML-05 | Global model on any kit; pseudo-observations for new kits (§7.4) |
| ML-08, NFR-02 | §7.8 |
| CFG-05, AL-16 | Config resolved and recorded at run start (§7.2) |
| AL-14 | Per-kit probabilities here; combination in [08](08-alert-engine.md) |
| Phase 2 (requirements 05 §5.6) | Chronos-Bolt shadow (§7.6) |
