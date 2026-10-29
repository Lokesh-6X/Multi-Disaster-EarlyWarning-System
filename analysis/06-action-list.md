# 6. Action List

Every finding, its fix, and where the fix was applied. All 31 findings were applied to requirements and design on 2026-10-30, with requirement decisions **D30–D36** ([requirements/09](../requirements/09-decisions-and-open-questions.md)) and design decisions **DD99–DD113** ([design/decisions.md](../design/decisions.md)); revised older decisions keep their number and are marked **Revised** (DD11, DD45, DD55, DD65, DD67, DD80).

## 6.1 Owner decisions (answered 2026-10-30)

| ID | Question | Answer | Recorded as |
|---|---|---|---|
| AN-11 | How is the heavy-rain-burst threshold set? | 99th percentile of **wet hours** (≥ 0.1 mm), never below **20 mm/h** | D32, DD104 |
| AN-12 | How is the heatwave normal made comparable with the kit? | Plain normal first ("normal not yet calibrated"); after 4–8 weeks a per-kit **normal offset** is added | D33, DD105 |
| AN-27 | Where can the dashboard be opened? | **Only on the server machine**; no phones or other computers | D34, DD80 Revised |
| AN-07 | When does a multi-day Live heatwave end? | After a **whole local day** without heatwave conditions | D35, DD106 |

## 6.2 All findings

| ID | Sev | Finding | Fix applied | Decision | Documents changed |
|---|---|---|---|---|---|
| AN-01 | H | Heatwave forecast never covers today | D0 window "rest of today" with the measured maximum | D30, DD99, DD55 Revised | req 06 §6.1, scenario 3, features; design 06 §6.6 §6.8.4, 07 §7.5, 08 §8.2 |
| AN-02 | H | Rain-day D0 ignores rain already fallen | Measured rain + forecast for the rest; P = 1 if already met | D30, DD99 | req 06 §6.1; design 06 §6.8.4, 07 §7.5, 08 §8.2 |
| AN-03 | H | Squall met by one 3-s gust | Rule on the 1-minute mean wind; `squall_min_wind_kmh`; simulator scenarios | D31, DD100 | req 06 §6.1, scenarios 2 and 9, features; design 04, 05 §5.5.2, 08 §8.6.2, 11, 12 |
| AN-04 | M | Alert window moves silently | `updated` change kind, `alert_window_shift_notify_h` | DD101 | design 02, 03, 04, 08, 09, 12 |
| AN-05 | M | Alert ending while suppressed is silent | End always emailed | D36, DD102, DD67 Revised | req 06 AL-08; design 08 §8.3 §8.9 §8.11, 12 |
| AN-06 | M | Filters hide later changes | Sticky audience | D36, DD102 | design 08 §8.7 §8.11, 09 §9.5, 12 |
| AN-07 | M | Multi-day heatwave restarts daily | Live heatwave per local day | D35, DD106 | req 06 AL-05, scenario 3; design 04, 08 §8.6.3, 12 |
| AN-08 | M | Take-over closes later-day forecast alerts | Only a forecast alert covering now | D29 wording, DD103, DD65 Revised | req 09 D29; design 08 §8.7, 12 |
| AN-09 | L | Live 24 h rain stays open after rain stops | Wording "in the last 24 h" | — | design 08 §8.6.1, 09 §9.3 |
| AN-10 | L | Cancellation delayed by cooldown | Accepted; stated as a limitation | — | design 08 §8.11 |
| AN-11 | H | p99 threshold far too low | Owner decision 6.1 | D32, DD104 | req 04 §4.5, 06 §6.1, scenario 4, features; design 03, 04, 05 §5.8.2, 06 §6.5 §6.6 §6.8.4, 08 |
| AN-12 | H | Heatwave departure biased | Owner decision 6.1; `normal_offset` table and daily job | D33, DD105 | req 04 §4.5, 06 §6.1, features; design 03 §3.8, 04, 05, 06 §6.10 §6.14, 07 §7.9, 08 §8.6.1, 09, 12 |
| AN-13 | M | "Beats baselines" unrealistic | Pass marks per model | DD111 | req 08 §8.5; design 06 §6.9 |
| AN-14 | M | Archive coverage uncertain | Week-1 check; dates in manifest; fallback | DD113 | design 06 §6.3 |
| AN-15 | M | Colab may not finish | Per-epoch checkpoints, subset search, CPU trial | DD113 | design 06 §6.8.2 §6.13 §6.14 |
| AN-16 | M | Unknown alert volume | Alert-volume dry run | DD112 | design 12 §12.6 |
| AN-17 | L | One-day vs IMD two-day heatwave | Stated as a deliberate difference | — | req 06 §6.1; design 06 §6.14 |
| AN-18 | L | Acknowledgement key described two ways | 01 corrected | — | design 01 §1.2 |
| AN-19 | M | API config example used wrong keys | Flat keys `kit_zone`, `cal_*`, `kit_enabled` | — | design 02 §2.6.8 |
| AN-20 | L | Replay rates 60× too high | 1 msg/s per kit at 60× | — | design 05 §5.9, 13 §13.1 §13.3.5 |
| AN-21 | L | Very late readings and aggregates | DD45 text corrected | DD45 Revised | design decisions |
| AN-22 | L | Run IDs in two styles | Integer-style IDs everywhere | — | design 02 |
| AN-23 | L | Scenario 4 "next 24 h" | "Current rain day, ending 08:30 tomorrow" | — | scenario 4 |
| AN-24 | L | Run-ID retention assumes 96 runs/day | Cut-off run found from `issue_time` | — | design 03 §3.14 |
| AN-25 | H | Real-clock jobs delete demo data | No retention/compression policies in the demo database | DD107 | design 03 §3.14, 11 §11.3.1, 12, 14 |
| AN-26 | H | Reset demo has no forecasts | Demo snapshot; `no_fill_data` skip reason | DD108 | scenario 9; design 01 §1.7.4, 03 (`forecast_run_kit.reason`), 07 §7.4, 11 §11.3.1, 12, 14 |
| AN-27 | M | Dashboard unreachable from phones | Owner decision 6.1: server machine only | D34, DD80 Revised | req 07 §7.1; design 01 §1.7.2, 09 §9.4.2, 10 §10.1, 14 §14.1.4 |
| AN-28 | H | Broker queue limit 1 000 | `max_queued_messages 0`, check and test | DD109, DD11 Revised | design 01 §1.3.1, 12, 14 |
| AN-29 | M | Catalogue loaded by the 4th process | Synced by `start.ps1`; keys deprecated, never deleted | DD110 | design 01 §1.7.4, 03 §3.5.2 §3.15, 04 §4.7, 12 |
| AN-30 | M | TimescaleDB on Windows unproven | Feature check in `check-setup.ps1` + week-1 check + fallback | DD113 | design 14 §14.1.3 |
| AN-31 | L | MQTT unencrypted on Wi-Fi | Stated as a limitation; TLS 8883 for real installs | — | design 14 §14.1.4 |

## 6.3 Follow-up check of the fixes (2026-10-30)

A second read of the changed documents found six issues created by the fixes themselves; all applied.

| # | Issue | Fix | Decision | Documents changed |
|---|---|---|---|---|
| 1 | With D35 a Live heatwave stays open for days, so tomorrow's forecast heatwave alert would run beside it | No same-or-lower-colour forecast heatwave alert while a Live heatwave is open | DD114 | design 04 §4.3.7, 08 §8.5.3, 12 |
| 2 | Two possible sources for the current rain day (classifier or measured + forecast) | D0 always measured + TFT; classifiers D1–D2 only | DD115 | design 06 §6.8.3, 07 §7.5, 12 |
| 3 | The simulator could not know the snapshot's simulated time (it never reads the database) | `demo-snapshot.json` with `sim_time` | DD116 | design 11 §11.3.1, 12 |
| 4 | Snapshot could be from an older schema | Migrations after restore; warning; rebuild after migrations | DD116 | design 11 §11.3.1, 14 §14.1.2 |
| 5 | Sticky audience vs "deactivated users get nothing" | Sticky emails still skip deactivated users and inactive recipients | DD102 wording | design 08 §8.11, 09 §9.5 |
| 6 | `cleardown_heat_min` no longer used after D35 | Key removed; note under the alert-behaviour table | DD106 | design 04 §4.3.7 |

## 6.4 Still to do

| Step | When |
|---|---|
| Week-1 checks ([05 §5.3](05-scope-and-plan.md)); write the results back into design 06 §6.3 and 14 §14.1 | Start of implementation |
| Agree alert-volume targets for the dry run (DD112) with the owner | When the alert engine runs |
| Set the final rain-burst floor if week-1 check 6 shows 20 mm/h is unsuitable | After week-1 check 6 |
