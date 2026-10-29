# 8. Alert Engine

The `alerts` process: how forecast probabilities and live readings become Watch / Warning / Live alerts, the state machine (create, upgrade, downgrade, cancel, clear), hysteresis, minimum duration, clear-down, far-event agreement, multi-kit combination, squall detection, take-over, suppression, manual alerts and the notification decisions. Requirements: [06](../requirements/06-hazards-and-alerts.md) (AL-01 – AL-17), D10, D27, D29. Tables: [03 §3.9](03-database-schema.md). Settings: [04 §4.3.6 – 4.3.7](04-configuration.md).

Decisions referenced: DD62–DD68 in [decisions.md](decisions.md).

## 8.1 Principles

| Principle | Rule |
|---|---|
| One writer (DD2) | Only `alerts` changes alert state; operator actions arrive as commands |
| Computed once (WEB-20) | Alerts are evaluated on the server; clients only read them |
| Never silent (AL-08) | Every change is an `alert_change` row; every change that matters to people is announced (§8.11) |
| Stored state (DD13) | Timers, counters and pending agreements live in `live_condition` and `forecast_condition`; a restart resumes exactly |
| Colour = severity, type = certainty (D27) | `level` comes from the threshold category; `type` is watch / warning / live |
| Safety first | Escalations are never delayed by cooldown or suppression; live alerts never depend on the forecast (AL-02) |

## 8.2 Vocabulary (DD62)

| `event` | `hazard` | Levels | Sources | Scope (AL-14) | Probability windows / live measure |
|---|---|---|---|---|---|
| `gust` | high_wind | yellow 39, orange 50, red 62 km/h | forecast, live, manual | **per zone** (kit) | 3 h / 6 h blocks; median gust of the last 10 min |
| `rain_intensity` | heavy_rain | `rain_intensity_level` (orange) | forecast, live, manual | **site** (worst kit) | 3 h blocks 0–6 h; rolling 1 h rain vs the rain-burst threshold (D32) |
| `rain_24h` | heavy_rain | yellow 64.5, orange 115.6, red 204.5 mm | forecast, live, manual | **site** (worst kit) | IMD rain days D0–D2 (D0 includes rain already measured, D30); rolling 24 h rain |
| `heatwave` | heatwave | orange = heatwave, red = severe heatwave | forecast, live, manual | **site** (median of kits) | local days D0 (rest of today)–D3 (D30); 30-min median temperature vs normal + offset (D33) |

- A severe heatwave is the **red level of the `heatwave` event**, not a separate event, so one alert moves between orange and red.
- A **squall is a trigger**, not an event: the squall rule opens (or upgrades) the live `gust` alert of that zone immediately (§8.6.2). The change records `trigger = squall`, and emails say "High wind (squall)".
- Site wind status (dashboard) = worst zone; it is shown, not issued as a separate alert.
- `site` scope alerts have `kit_no = NULL`; their "zone" in emails is the site name.

**Severity order** used for every comparison: colour first, then certainty.

```
yellow watch < yellow warning < yellow live < orange watch < orange warning < orange live < red watch < red warning < red live
```

So an alert that goes from 🟠 Orange Warning to 🔴 Red Watch is an **upgrade** (a more severe outcome became possible).

**Triggers** recorded on each change: `forecast`, `sustained` (live threshold held), `squall`, `manual`, `system` (window ended, take-over, no data, config).

## 8.3 Alert identity and lifecycle

An alert is identified by **(event, source, zone)**; at most one is open per key (partial unique index, [03 §3.9.2](03-database-schema.md)).

```
                 create (created)
     (none) ─────────────────────────► ACTIVE ──────────── cancel (cancelled) ──► CLOSED
                                        │  ▲                 forecast no longer expects it
              upgrade / downgrade ──────┘  │
              suppress / unsuppress ───────┘            ── clear (cleared) ────► CLOSED
              threshold_changed, advice_updated               live condition ended (clear-down),
                                                              forecast window passed, no data,
                                                              manual clear
                                                         ── taken_over ────────► CLOSED
                                                              a Live alert replaced it (D29)
```

| `change` | Status after | Sends email (§8.11) | Needs acknowledgement (DD36) |
|---|---|---|---|
| `created` | active | ✅ | ✅ |
| `upgraded` | active | ✅ | ✅ |
| `downgraded` | active | ✅ | — |
| `updated` | active | ✅ (window moved, DD101; cooldown applies) | — |
| `cancelled` | cancelled | ✅ ("Cancelled: … no longer expected"), also while suppressed (D36) | — |
| `cleared` | cleared | ✅ ("Cleared: …" with the reason), also while suppressed (D36) | — |
| `taken_over` | cleared | — (the Live alert's email says what it replaces) | — |
| `suppressed`, `unsuppressed`, `suppression_expired` | active | — (operators see it on the dashboard) | — |
| `suppression_overridden` | active | ✅ (together with the upgrade that caused it) | ✅ |
| `threshold_changed`, `advice_updated` | active | — | — |

## 8.4 Inputs and wake-ups

| Wake-up | Work |
|---|---|
| `reading.ingested` | Live path for that kit (§8.6), then site combination for heat and rain (§8.8) |
| `forecast.run_completed` | Forecast path for every open or possible forecast alert (§8.5) |
| `alert.command` | Apply operator commands in order (§8.10) |
| `kit.status_changed` | Offline handling (§8.6.4); maintenance notices ([05 §5.4.9](05-data-pipeline.md)) |
| `kit.qc_flag` | Maintenance notices |
| `config.changed` | Reload; `threshold_changed` on affected open alerts (§8.12) |
| Tick every 60 s | Clear-down expiry without new readings, offline hold, suppression expiry, forecast window end, stale-forecast flag, pending commands |
| Start-up | Catch up from `reading_marker` and `run_marker`; then normal operation |

## 8.5 Forecast path

### 8.5.1 Per run

```
for each event and scope (zone for gust; site for the others):
    p[level][window] = probabilities of the run                       (07 §7.5)
                       site scope: combined over kits (§8.8)
    skip if the run has no usable data for this scope (kit skipped)    → nothing counts, nothing changes
    episode = earliest group of consecutive windows where some level qualifies (below)
    p_L     = max probability of level L over the episode's windows
    target  = (level, type) from §8.5.2, or none
    apply the transition rules of §8.5.3
    write alert_run_probability for every open forecast alert          (AL-13 trend)
```

The alert's **window** is the episode's start and end; its **probability** is `p_L` of its displayed level. People see the window in **whole hours** (start rounded down, end rounded up, requirements D38, DD119): the model's blocks start at the issue time (e.g. 14:15–20:15), which would read oddly and shift by 15 minutes every run. The rounded window is stored on the change, used in emails, the UI and the "window moved" check (DD101); the exact block times stay in `forecast_probability`. The other levels' probabilities are kept for the alert detail and emails ("Orange: 72 %").

### 8.5.2 Target state with hysteresis (AL-10, DD63)

With the current alert at (Lc, Tc), or none:

```
qualifies(L) = p_L ≥ watch_on                              (new or higher level)
            or (alert open and L ≤ Lc and p_L ≥ watch_off) (hysteresis keeps current and lower levels)
Lt = highest qualifying level                                (most severe colour shown, owner decision)
Tt = warning  if p_Lt ≥ warning_on
            or (Tc = warning and Lt = Lc and p_Lt ≥ warning_off)
     watch    otherwise
```

Defaults: `watch_on` 0.30, `watch_off` 0.20, `warning_on` 0.60, `warning_off` 0.45.

### 8.5.3 Transitions (AL-08, AL-09, AL-11)

| Comparison of target with current | Action |
|---|---|
| No alert, target exists, episode starts within `alert_far_event_h` (48 h) | **Create** now |
| No alert, target exists, episode starts later (far event) | Count agreement in `forecast_condition`; create when the target has held for `alert_far_agreement_runs` (2) consecutive runs (AL-11) |
| Target **higher** (severity order) | **Upgrade** on this run (upgrade fast, AL-09); far episodes need the same agreement as creation |
| Target **equal** | Update probability and window; reset the lower-run counter. Silent, unless the shown (whole-hour, DD119) window start moves by more than `alert_window_shift_notify_h` (3 h) or to another local day: then **`updated`** ("Updated: now expected 20:00–23:00"), DD101 |
| Target **lower** or none | Increment the lower-run counter; after `alert_downgrade_runs` (3) consecutive lower runs → **downgrade** to the target, or **cancel** if there is none (downgrade slow, AL-09). A run that is not lower resets the counter |
| Episode window has ended (now > window end) and no later window qualifies | **Clear** at once: "Forecast period ended" |

- Only **completed, non-shadow runs** count; missed runs simply do not exist (DD58).
- **Stale forecast** (no completed run for `forecast_stale_after_runs` slots): forecast alerts keep their state and show "forecast not updated since …"; counters do not advance; window-end clearing still applies.
- While a **Live alert** of the same event and zone is open, no forecast alert is created for an episode that starts within `live_takeover_hold_h` (6 h), unless its colour is higher than the Live alert's (§8.7).
- **Heatwave exception (DD114):** while a Live heatwave alert is open (it can stay open for days, D35), **no** forecast heatwave alert at the same or a lower colour is created for any episode, near or far; only a higher colour (e.g. Red forecast during an Orange Live) gets a forecast alert. Forecast heatwave alerts resume once the Live alert is cleared. Without this, tomorrow's forecast alert would run beside the Live alert when tomorrow becomes today.

### 8.5.4 Scenario 2 traced (wind, KIT-01)

| Run | p(orange) | p(red) | Target | Counter | Result |
|---|---|---|---|---|---|
| 11:00 | 0.35 | 0.05 | orange watch | — | **created** 🟠 Watch |
| 11:15–12:15 | 0.38–0.44 | < 0.1 | orange watch | 0 | equal; trend 35 % → 44 % |
| 12:30 | 0.72 | 0.12 | orange warning | 0 | **upgraded** to Warning |
| 14:18 | — | — | — | — | Live alert opens → **taken_over** (§8.7) |

## 8.6 Live path

### 8.6.1 Conditions per kit (AL-02, AL-04)

Evaluated on each new reading from `reading_clean` / `reading_derived` (faulty values are NULL and never count; suspicious values count). A level **holds** when:

| Event | Level holds when (thresholds from the kit's effective config) |
|---|---|
| `gust` | **Median** gust over the last `live_min_duration_wind_min` (10) minutes ≥ the level's threshold, with ≥ 80 % of the minutes present (DD64) |
| `rain_intensity` | `rain_1h_mm` ≥ `rain_intensity_1h_mm` (level = `rain_intensity_level`) |
| `rain_24h` | `rain_24h_mm` (rolling 24 h) ≥ the level's threshold |
| `heatwave` orange | Median temperature over `live_min_duration_heat_min` (30) ≥ `heat_min_tmax_c` **and** ≥ today's normal max + `heat_departure_c`; **or** ≥ `heat_absolute_c` |
| `heatwave` red | Median ≥ `heat_min_tmax_c` **and** > normal + `heat_severe_departure_c`; **or** ≥ `heat_severe_absolute_c` |

"Normal max" is the kit's normal: the climate normal plus its normal offset (D33, DD105) when one exists. Until then the heatwave alert and its emails carry "normal not yet calibrated".

Emails and the UI describe a Live 24 h rain alert as "64.5 mm or more in the last 24 hours", not "happening now": the rolling sum stays above the threshold for up to a day after the rain stops (analysis AN-09).

The median makes AL-04's minimum duration robust: single gusts are ignored, but one calm minute does not reset the timer. Readings that arrive more than `live_max_age_min` (15) after their timestamp update the rolling values but never open or upgrade a live alert by themselves.

### 8.6.2 Squall rule (§6.1 of the requirements, D8)

```
wind     = wind_avg_kmh, the kit's 1-minute mean wind (D31, DD100)
baseline = mean of wind over squall_baseline_min (10 min), ending 2 min before now
squall   = wind(now) − baseline ≥ squall_rise_kmh (30)
           and the last readings covering ≥ squall_sustain_s (60 s) all have wind ≥ squall_min_wind_kmh (40)
```

The rule works on the **mean** wind, as the IMD/WMO squall definition does. Each message carries one 1-minute mean, so "covering 60 s" means a whole minute whose mean is ≥ 40 km/h. The 3-second gust is not used here: one message's gust is a single 3-second peak and would let one gust raise an Orange Live alert.

When `squall` is true, the zone's live `gust` alert is **opened or upgraded immediately** to `squall_level` (orange) without waiting for the minimum duration, with `trigger = squall`. From then on the normal sustained rules move it up (e.g. to red after 10 minutes with median ≥ 62) and down.

**Precursors** (not an alert): over `squall_precursor_window_min` (15 min), at least two of: pressure rise ≥ 1 hPa, temperature drop ≥ 3 °C, humidity rise ≥ 10 %. Computed on read and shown on the dashboard as "Squall precursors" (`squall_precursor` in `/live` and `reading.new`, [02](02-api.md)).

### 8.6.3 Transitions (AL-05)

| Situation | Action |
|---|---|
| No alert, some level holds | **Create** at the highest holding level (`trigger = sustained` or `squall`) |
| A higher level holds | **Upgrade** immediately |
| The current level stops holding | Start clear-down: `live_condition.unmet_since = now` |
| Current level holds again before the clear-down ends | Timer reset |
| `cleardown_<hazard>_min` (wind 30, rain 60) passed with the current level unmet | Move to the highest level that holds now (**downgrade**), or **clear** if none holds |
| **Heatwave** (D35, DD106) | A level, once reached on a local day, holds for the rest of that day and through the night. At the end of a local day on which the current level was **not** reached, move to the highest level reached that day (**downgrade**), or **clear** if none was reached. One alert covers a whole multi-day heatwave |

Scenario 2: 14:18 squall → 🟠 Live created (takes over the Warning); 14:28 median ≥ 62 for 10 min → 🔴 upgraded; 14:45 below 39 → clear-down starts; 15:15 nothing holds → **cleared**.

### 8.6.4 Offline kits and missing data

| Situation | Action |
|---|---|
| Kit offline or no valid data for the event's measure | Conditions are **unknown**, not false: no clear-down progress, no new alerts from this kit |
| Unknown for `live_offline_hold_min` (60) with an open per-zone alert (not heatwave, see below) | **Clear** with "Cleared: no data from Main Block Rooftop since 10:02" |
| Site-scope alerts | Combined over the kits that have data; if none has data, held like the above |
| **Heatwave** (DD120) | Missing data never clears a Live heatwave during the day it is held for (D35). At the end of the local day: if the day's 11:00–17:00 local hours had less than 80 % coverage, the alert is **kept** and shows "no data from …"; it is cleared after a day with enough data that did not meet the rule, or after a whole local day with no data at all ("Cleared: no data since …") |

### 8.6.5 State

`live_condition` ([03 §3.9.4](03-database-schema.md)) holds per scope, event and level: `met_since`, `unmet_since`, `updated_at`. The medians themselves are recomputed from the database window on each reading, so nothing is lost on restart.

## 8.7 Live takes over forecast (D29, DD65)

```
when a Live alert opens or is upgraded for (event, zone) at colour C:
    for the open forecast alert of the same (event, zone) with colour ≤ C
        whose window includes now or starts within live_takeover_hold_h (DD103):
        close it: change = taken_over, status = cleared, related_alert = the Live alert,
                  explanation "Now happening — see Live alert"
    the Live alert's email adds: "Replaces the 🟠 Orange Warning issued 11:00 IST"
```

- A forecast alert whose colour is **higher** than the Live alert stays open (e.g. Live orange, but a red outcome is still forecast).
- A forecast alert for a **later** episode (e.g. tomorrow's heat) is not taken over (DD103).
- The Live alert's emails also go to the audience of the alert it replaces (DD102).
- While the Live alert is open, no forecast alert is created for an episode starting within 6 h unless its colour is higher (§8.5.3). Later episodes (e.g. tomorrow's heat) are alerted normally.

## 8.8 Multi-kit combination (AL-14, DD66)

| Hazard (config key) | Default rule | Forecast path | Live path |
|---|---|---|---|
| Heatwave (`combine_heatwave`) | `median` | Median over kits of each level's probability per window | Median over kits of the level each kit reaches (ordered green < orange < red) |
| Heavy rain (`combine_heavy_rain`) | `worst` | Max over kits | Highest level over kits |
| High wind (`combine_high_wind`) | `worst` | Per-zone alerts; site wind status = worst zone | same |

Other allowed rules: `majority` (the level reached by more than half of the kits with data), `two_kit_agreement` (the second-highest kit level; needs ≥ 2 kits). Common rules:

- Each kit is first evaluated **with its own effective thresholds** (local risk), then combined.
- Only kits with usable data take part (QC applied; skipped/degraded kits use their forecast status, [07 §7.4](07-forecast-worker.md)).
- With an even number of kits, `median` takes the **lower** middle value, so one hot rooftop cannot raise a site heatwave alone.
- With one kit every rule gives that kit's value.

## 8.9 Suppression (AL-15, DD67)

| Rule | Detail |
|---|---|
| Effect | The alert stays visible (badge "Suppressed by Priya until 17:00: Known construction crane test, safe") and keeps being evaluated; **no emails** for its changes while suppressed |
| Limits | Reason required; `expires_at` in the future and ≤ `suppression_max_h` (24 h) |
| Safety override | If the alert's **colour** would rise (e.g. yellow → red), the suppression ends at once (`suppression_overridden`, `ended_how = overridden`) and the upgrade is announced normally |
| Certainty rise at the same colour | Watch → Warning while suppressed: applied and shown, no email (the operator suppressed this colour knowingly); it still needs acknowledgement (DD36) |
| Expiry | On the tick: `suppression_expired`; if the alert's state differs from what was last emailed, one email with the current state is sent |
| End early | `unsuppress` command; same rule as expiry |
| Close | Closing the alert ends the suppression (`alert_closed`); the `cancelled` / `cleared` email **is sent** to everyone emailed about the alert before (D36, DD102), so no alert ends silently |

Scenario 7: 15:05 a 🟡 Watch is suppressed until 17:00; 15:40 a run gives 🔴 → `suppression_overridden` + `upgraded`, emailed.

## 8.10 Commands and manual alerts

Commands are applied in `requested_at` order, each in its own transaction with a row lock on the alert ([02 §2.5](02-api.md)).

| Command | Checks (rejected → `COMMAND_REJECTED` with reason) | Result |
|---|---|---|
| `suppress` | Alert active; not manual; not already suppressed; expiry valid | `suppressed` |
| `unsuppress` | Suppression active | `unsuppressed` |
| `manual_raise` | Event/level valid for the event (§8.2); zone valid for the scope; no open manual alert with the same key | New alert, `source = manual`, `trigger = manual`, emailed like any alert |
| `manual_clear` | Alert is manual and active | `cleared` |

Manual alerts are never changed by the engine, except that one with a `window_end` is cleared automatically when the window ends. They do not take over or block automatic alerts.

## 8.11 Notification decisions (WEB-40 – WEB-43, AL-06)

The engine decides **who** gets **which** change; `mailer` renders and sends ([09](09-notifications.md)). For each change that sends email (§8.3), in the same transaction, one `email_message` row per addressee:

| Addressees | Selected when |
|---|---|
| Recipient lists (`recipient`) | Active; hazard in `recipient_hazard`; alert colour ≥ `min_level`; and either no `recipient_zone` rows, or the alert's zone is listed, or the alert is site-scope |
| Operators and admins (`app_user`) | Active; preferences (`user_alert_preference`, hazards, types, `min_level`) match; get the detailed version with probability, run and "Acknowledge" link (WEB-43) |
| **Sticky audience** (D36, DD102) | Everyone who received an earlier email of this alert and is still an active user or active recipient, whatever their filters now say (a downgrade below `min_level`, or a cancel, still reaches them). A Live alert that takes over another alert also goes to that alert's audience |

Filters decide who is told **first**; once told, an addressee hears every later change and the end.

**Cooldown (AL-06, DD68):**

| Change | Cooldown behaviour |
|---|---|
| `created`, `upgraded`, `suppression_overridden` (escalations) | Always sent **immediately** |
| `downgraded`, `updated`, `cancelled`, `cleared` within `notify_cooldown_min` (60) of the last email of this alert to that addressee | Queued with `next_attempt_at` = end of the cooldown; if another change of the same alert is queued before then, the older one is skipped as superseded (`email_skip_superseded`), so the addressee gets the latest state once |

Suppressed alerts queue nothing except their end (`cancelled`, `cleared`, §8.9). Known limitation, stated in the report: a cancellation within the cooldown can reach people up to an hour late (the safe direction; analysis AN-10). The subject follows WEB-40: `[ORANGE WARNING] High wind – Sports Ground – 14:00–17:00 IST`; site-scope alerts use the site name; Live alerts end with "– now"; squall-triggered ones say "High wind (squall)".

## 8.12 Configuration changes (AL-16, CFG-05)

On `config.changed` the engine reloads the resolved config. For each open alert whose effective threshold (for its event and level) changed, it writes `threshold_changed` with the old and new value. The live path uses the new value from the next reading; the forecast path from the next run (whose probabilities were computed with the new value, [07 §7.5](07-forecast-worker.md)).

## 8.13 Processing and restarts

| Item | Rule |
|---|---|
| Ordering | One event loop; per wake-up, work is done per (event, scope) in its own transaction, locking the alert row (`SELECT … FOR UPDATE`) |
| Catch-up | Live path: readings with `received_at` after `reading_marker` (per kit); forecast path: completed runs after `run_marker`, oldest first. Markers advance in the same transaction as the work |
| Idempotence | Re-processing a reading or run after a crash produces no duplicate changes (state comparison) and no duplicate emails (unique key per change and addressee, [03 §3.10](03-database-schema.md)) |
| Budget | Live path ≤ 100 ms per reading; forecast path ≤ 2 s per run |
| Outputs | `alert.changed` (and `alert.command_result`) NOTIFY after commit; `email.queued` when emails were queued |

## 8.14 Requirement coverage

| Requirement | Section |
|---|---|
| AL-01, D10 | §8.5, §8.6 |
| AL-02 | §8.6 (independent of forecasts), §8.4 |
| AL-03 | Alert + change rows ([03 §3.9](03-database-schema.md)), §8.5.1 window and probability |
| AL-04 | §8.6.1 median over the minimum duration |
| AL-05 | §8.6.3 clear-down |
| AL-06 | §8.11 cooldown |
| AL-07 | §8.5 (newest run supersedes; one evaluation per run) |
| AL-08 | §8.3 |
| AL-09 | §8.5.3 |
| AL-10 | §8.5.2 |
| AL-11 | §8.5.3 far-event agreement |
| AL-12, AL-13 | `alert_run_probability` (§8.5.1) |
| AL-14 | §8.8 |
| AL-15 | §8.9 |
| AL-16 | §8.12 |
| AL-17, D27 | §8.2 colours, advice from config or operator, §8.11 |
| D29 | §8.7 |
| D30, D31, D33, D35, D36 | §8.2, §8.6.1, §8.6.2, §8.6.3, §8.9, §8.11 |
| DD36 | §8.3 acknowledgement column |
| DP-26 | Maintenance notices on `kit.qc_flag` / `kit.status_changed` |
