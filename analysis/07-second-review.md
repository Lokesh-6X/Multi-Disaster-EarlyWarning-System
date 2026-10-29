# 7. Second Review

A second full pass over requirements and design after the fixes of the first review (D30–D36, DD99–DD116). It looks at things the first pass did not trace: timers in demo mode, limits of the external data service, how alert windows look to people, and how the new rules interact with the old ones.

Done 2026-10-30. **All nine fixes applied the same day** (owner choices: windows rounded for display, scope "India only"), as requirement decisions D37–D38, future enhancement F3 and design decisions DD117–DD123 (DD59 revised); see §7.4.

| ID | Finding | Severity |
|---|---|---|
| AN-32 | In demo mode, timeouts and watchdogs would run 60× fast and kill every forecast run | High |
| AN-33 | Open-Meteo counts big requests as many calls; the planned download speed breaks its limits | Medium |
| AN-34 | Forecast windows start at odd times and shift every 15 minutes | Medium |
| AN-35 | Forecast rain-burst alerts will almost never fire | Medium |
| AN-36 | A night-time kit outage ends a multi-day heatwave alert | Medium |
| AN-37 | Heatwave classifiers ignore the normal offset | Low |
| AN-38 | The 08:30 IST rain day and IMD rules make the system India-only | Low |
| AN-39 | The WebSocket origin check blocks the development server | Low |
| AN-40 | A clean reading records the kit's config version but not the site's | Low |

---

## AN-32 In demo mode, timeouts and watchdogs would run 60× fast — High

**Where:** demo mode makes every backend process use the simulator's clock for "now", sleeping and scheduling ([11 §11.3](../design/11-simulator.md), DD82). Only "sessions, rate limits, tokens" are explicitly kept on real time. Nothing is said about **timeouts and health checks**.

**What happens at 60×** if they follow demo time:

| Timer | Setting | In real time at 60× | Effect |
|---|---|---|---|
| Forecast run hard timeout | `forecast_timeout_s` 300 s | **5 s** | Inference takes 10–20 s ([07 §7.8](../design/07-forecast-worker.md)), so **every run is killed** and marked `failed`; no forecast ever completes in the demo |
| Run start grace | `misfire_grace_time` 300 s | 5 s | Most slots skipped |
| Process "down" | 60 s without a heartbeat | 1 s | Processes shown as down at random |
| Heartbeat interval | 15 s | 0.25 s | Four database writes a second per process |
| Open-Meteo / SMTP timeouts | 20 s / SMTP client | 0.3 s | Every request "times out" |
| WebSocket ping / dead-connection timer | 20 s / 45 s | 0.3 s / 0.75 s | Browsers disconnect constantly |

**Suggested fix:** two kinds of time in `ews.common.clock`:

| Kind | Uses | Examples |
|---|---|---|
| **Weather time** (demo clock in demo mode) | Anything about the weather and alerts | Reading timestamps, forecast issue times, alert timers (minimum duration, clear-down, cooldown, suppression expiry), offline timeout, live windows |
| **Machine time** (always the real clock) | Anything about software health and networking | Timeouts of runs, HTTP, SMTP and database calls; heartbeats and "process down"; WebSocket pings; retries' backoff; sessions, rate limits, tokens (already) |

Add a test: demo at 60× for 5 minutes → forecast runs complete, no process shown down, no WebSocket reconnects.

---

## AN-33 Open-Meteo counts big requests as many calls — Medium

**Where:** training download "one request per location per year … about 1 000 requests over two days" ([06 §6.3](../design/06-ml-training.md)); onboarding "one request per year, 1 s apart" ([05 §5.8.2](../design/05-data-pipeline.md)).

**The problem:** the free Open-Meteo API weights requests: a request for a long period (more than about 2 weeks) or many variables counts as **several** calls, and there are limits per minute, per hour and per day. One year of six hourly variables is therefore roughly 25+ calls, not 1 (check the current terms before downloading).

| Download | Requests | Approx. weighted calls | Problem |
|---|---|---|---|
| Training history: 24 locations × 35 years | 840 | ≈ 20 000+ | More than one day's free limit; "two days" is too short |
| Onboarding: 35 years, 1 s apart | 35 in 35 s | ≈ 900 in under a minute | Over the **per-minute** limit → `429` errors → onboarding fails → no forecasts for the site |

**Suggested fix:**

- Onboarding: pace by **weighted calls** (e.g. one yearly request every 5–10 s), and on `429` wait for `Retry-After` and resume (yearly commits already allow resuming). Onboarding then takes a few minutes, not seconds; the progress view already handles that.
- Training: plan the download over several days with the same pacing, or shorten history requests to the years actually used (normals 1991–2020 need only daily maxima; model training starts in 2008).
- Week-1 check 2 ([05 §5.3](05-scope-and-plan.md)) also records the real weighting.

---

## AN-34 Forecast windows start at odd times and shift every 15 minutes — Medium

**Where:** probability windows are 3 h / 6 h blocks **counted from the issue time** ([06 §6.6](../design/06-ml-training.md), DD55), and runs are every 15 minutes with rolling hours (DD56).

**What happens:** a run issued at 11:15 has gust windows 11:15–14:15, 14:15–17:15, …; the next run has 11:30–14:30, 14:30–17:30, …. An alert's window is the episode's start and end, so:

- emails say "High wind – Main Block Rooftop – **14:15–20:15 IST**", odd for people to read;
- the alert's window moves by 15 minutes **every run**, so the window in the last email is almost never the current one;
- Scenario 2's "14:00–18:00" cannot occur (windows are 3 h blocks, so an episode is 3, 6 or 9 h long).

**Suggested fix (no model change):** keep the model's windows as they are, but **show and compare whole hours**: an alert's displayed window = start rounded **down** and end rounded **up** to the hour. DD101's "window moved" check uses the rounded window. Scenario 2's example becomes "14:00–20:00" (two 3 h blocks).

---

## AN-35 Forecast rain-burst alerts will almost never fire — Medium

**Where:** rain-burst threshold ≥ 20 mm/h (D32); models trained on ERA5, which smooths rain over a 28 km cell ([06 §6.14](../design/06-ml-training.md)).

**The consequence:** ERA5 hours of ≥ 20 mm are very rare, so the `rain_intensity` classifier will usually have fewer than 30 positive windows and is not trained (06 §6.6), and the TFT, trained on the same smoothed data, almost never puts much probability above 20 mm/h. In practice, **forecast** rain-burst Watch/Warning alerts will hardly ever be raised; the **Live** rain-burst alert does the real work.

**This is acceptable** (Live alerts are the designed safety net, AL-02), but it must not be promised otherwise:

- State in the report and on the model-reports page that rain-burst lead time is not expected from reanalysis-trained models; measure it with kit data after fine-tuning.
- The model-reports page shows "not enough events to train" for events without a classifier (already in the model card, make it visible).
- The 24 h heavy-rain forecast (`rain_24h`) is unaffected: daily totals are far less smoothed.

---

## AN-36 A night-time kit outage ends a multi-day heatwave alert — Medium

**Where:** an open live alert is cleared after `live_offline_hold_min` (60 min) without data ([08 §8.6.4](../design/08-alert-engine.md)); a Live heatwave stays open through the night until a whole day without heat (D35, DD106).

**What happens:** Friday's Live heatwave is open; the only kit loses power from 01:00 to 03:00. After 60 minutes the heatwave is **cleared** ("no data"); on Saturday afternoon a **new** heatwave alert is created, with new emails and a new acknowledgement. One power cut undoes D35.

**Suggested fix:** for the heatwave, "no data" never clears the alert during the day it is held for; it is decided at the end of the local day like any other day: if the day had too little data to judge (for example less than 80 % coverage of the afternoon hours), the alert is **kept** and shows "no data from …"; it is cleared only after a day with enough data that did not meet the rule, or after a whole day with no data at all.

---

## AN-37 Heatwave classifiers ignore the normal offset — Low

**Where:** heatwave LightGBM classifiers were trained with ERA5 normals at the default rule ([06 §6.8.3](../design/06-ml-training.md)); DD59 uses a classifier only at "the threshold it was trained for"; D33 adds a per-kit normal offset.

**The gap:** with an offset, the effective heatwave threshold (normal + offset + 4.5 °C) is no longer the one the classifier was trained for, but DD59 only compares the threshold **keys**, which did not change.

**Suggested fix:** DD59 treats a non-zero normal offset like a changed threshold: the heatwave probability then comes from the TFT, which works for any threshold. Until the offset exists (first 4–8 weeks), the classifier is used as now.

---

## AN-38 The 08:30 IST rain day and IMD rules make the system India-only — Low

**Where:** goal 5 "Works for **any location** by changing configuration only" ([requirements 01 §1.2](../requirements/01-overview.md)) and NFR-07; but the rain day ends at 03:00 UTC (08:30 IST, fixed in the model windows, DD55), heatwave rules are IMD's (by Indian region type), training locations are all in India, and the default timezone is Asia/Kolkata.

**Suggested fix:** write the scope honestly: "any location **in India**" in goal 5, NFR-07 and the report. Other countries would need their own rain-day boundary, hazard rules and retrained or re-validated models, which is a future enhancement (F3).

---

## AN-39 The WebSocket origin check blocks the development server — Low

**Where:** the WebSocket handshake requires `Origin` = `APP_BASE_URL` (`http://localhost:8000`) ([02 §2.2.1](../design/02-api.md)); in development the page is served by Vite on port 5173 and the socket is forwarded to 8000 ([01 §1.7.2](../design/01-architecture.md)).

**What happens:** the browser sends `Origin: http://localhost:5173`, the handshake is refused, and live updates do not work in development.

**Suggested fix:** with `start.ps1 -Dev`, also allow `http://localhost:5173` (a `DEV_ORIGINS` setting that is empty in normal runs).

---

## AN-40 A clean reading records the kit's config version but not the site's — Low

**Where:** `reading_clean.config_version_id` is "kit config used (recompute, audit)" ([03 §3.6.1](../design/03-database-schema.md)). But clean values also use **site-level** values: the site's `elevation_m` when the kit has none (sea-level pressure), and QC limits that may be set at site level.

**The gap:** a row cannot always be recomputed exactly from raw + the recorded version, which is the stated purpose of N1.

**Suggested fix:** record both versions (`kit_config_version_id`, `site_config_version_id`), or a single "resolved config" version that `ingest` stores when it reloads configuration.

---

## 7.1 Checked again and sound

| Topic | Result |
|---|---|
| Live heatwave + take-over + DD114 over a 3-day heatwave | One alert thread: the forecast episode includes today, so it is taken over; no new forecast alert at the same colour while the Live alert is open |
| D36 sticky audience vs unique `(alert_change_id, to_address)` | No duplicates; deactivated users excluded |
| `updated` change through API enums, schema enum, emails, cooldown | Consistent in 02, 03, 08, 09 |
| Hysteresis cut-offs and defaults after the changes | Still satisfy `watch_off < watch_on ≤ warning_off < warning_on` |
| Session cookie `SameSite=Strict` with acknowledge links from email | Works: the first navigation has no cookie, but the app's own requests do, so the user lands on the alert page (or logs in once) |
| Demo snapshot restore path | Uses the same pre/post-restore procedure as backups |

## 7.2 Severity overview

9 new findings: 1 High, 4 Medium, 4 Low. Two need a choice by the owner:

| ID | Question | Suggested |
|---|---|---|
| AN-34 | Show alert windows rounded to whole hours, or change the model windows to fixed clock blocks? | Round for display (no retraining) |
| AN-38 | State "India only", or make the rain day and hazard rules configurable? | State "India only"; other countries as future enhancement F3 |

## 7.3 Fixes and documents to change

| ID | Fix | Documents |
|---|---|---|
| AN-32 | Weather time vs machine time in the clock abstraction; test | design 01 §1.5, 07 §7.1 §7.2, 11 §11.3, 12 §12.5, decisions (new DD) |
| AN-33 | Pace downloads by weighted calls; resume on `429`; plan several days | design 05 §5.8.2, 06 §6.3 §6.13 |
| AN-34 | Display and compare windows rounded to whole hours; Scenario 2 example | design 08 §8.5.1, 09 §9.3, 10; req real-time-scenario 2, 06 §6.2 example |
| AN-35 | State as an expected limitation; show "not enough events" on reports | design 06 §6.14, 10 §10.4.7 |
| AN-36 | Heatwave "no data" decided at the end of the day; keep the alert | design 08 §8.6.4, 12 |
| AN-37 | Non-zero normal offset → TFT-derived heatwave probability | design 07 §7.5, DD59 |
| AN-38 | "Any location in India"; F3 future enhancement | req 01 §1.2, 08 NFR-07, 09 §9.2 |
| AN-39 | `DEV_ORIGINS` for `-Dev` | design 01 §1.7.3, 02 §2.2.1 |
| AN-40 | Record site and kit config versions on clean rows | design 03 §3.6.1 |

## 7.4 Applied

| ID | Decision | Documents changed |
|---|---|---|
| AN-32 | DD117 | design 01 §1.5, 07 §7.1 §7.2, 11 §11.3, 12 §12.5 |
| AN-33 | DD118 | design 05 §5.8.2, 06 §6.3 §6.13 |
| AN-34 | D38, DD119 | req 09; design 08 §8.5.1 §8.5.3, 09 §9.3, 12 |
| AN-35 | — (limitation) | design 06 §6.14, 10 §10.4.7 |
| AN-36 | DD120 | design 08 §8.6.4, 12 |
| AN-37 | DD121, DD59 Revised | design 07 §7.5, 12 |
| AN-38 | D37, F3 | req 01 §1.2, 08 NFR-07, 09 §9.1 §9.2 |
| AN-39 | DD122 | design 01 §1.7.3, 02 §2.2.1 §2.7.1, 12 |
| AN-40 | DD123 | design 03 §3.2 §3.6.1, 04 §4.5 |
