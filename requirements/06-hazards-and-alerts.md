# 6. Hazards and Alerts

## 6.1 Hazard definitions (system defaults)

### Heatwave (IMD criteria)

| Region type | Minimum max temperature | Heatwave | Severe heatwave |
|---|---|---|---|
| Plains | ≥ 40 °C | 4.5–6.4 °C above normal | > 6.4 °C above normal |
| Coastal | ≥ 37 °C | ≥ 4.5 °C above normal | > 6.4 °C above normal |
| Hilly | ≥ 30 °C | 4.5–6.4 °C above normal | > 6.4 °C above normal |
| Any | — | Actual ≥ 45 °C | Actual ≥ 47 °C |

"Normal" is computed automatically per site and day of year (1991–2020) from reanalysis. Because a kit (often on a rooftop) and a 28 km reanalysis grid cell are different references, a **normal offset** per kit (median difference of daily maxima, kit − reanalysis) is computed after 4–8 weeks of kit data and added to the normal; until then heatwave alerts are marked "normal not yet calibrated" (D33). The heat index (temperature + humidity) is also shown and used for heat-stress advice. Heatwave uses daily maximum temperature, forecast for **today and the next 3 days**; for today, the maximum already measured counts (D30). A Live heatwave alert stays open through the night and ends only after a whole local day without heatwave conditions (D35).

The same rule applies to the 24 h rainfall of the current rain day: rain already measured since the rain day began is added to the forecast for the remaining hours (D30).

IMD declares a heatwave when the criteria hold at two stations on two consecutive days; a one-site system uses a single site and a single day, a deliberate difference stated in the report.

### Heavy rainfall (IMD, 24-hour accumulation)

| Category | 24 h rainfall |
|---|---|
| Heavy | 64.5–115.5 mm |
| Very heavy | 115.6–204.4 mm |
| Extremely heavy | ≥ 204.5 mm |

Plus an **hourly intensity alert** ("heavy rain burst"): rain above the site's 99th-percentile hourly rainfall **of wet hours** (hours with ≥ 0.1 mm), but never below **20 mm/h** (D32), because sites waterlog from short bursts. Horizon 1–6 h.

### High-speed wind (Beaufort, gust speed)

| Level | Gust | Beaufort |
|---|---|---|
| 🟢 Green | < 39 km/h | 0–5 |
| 🟡 Yellow | 39–49 km/h | 6 |
| 🟠 Orange | 50–61 km/h | 7 |
| 🔴 Red | ≥ 62 km/h | 8+ |

**Squall** (IMD-style, on the **1-minute mean wind**, not the 3-second gust, D31): sudden increase of the mean wind by ≥ ~30 km/h, reaching a mean of ≥ ~40 km/h, sustained ≥ 1 minute. Squall precursors: pressure jump (1–3 hPa in minutes), sharp temperature drop, humidity rise. Horizon 0–3 h.

All thresholds are configurable (site and kit level).

## 6.2 Alert types

| Type | Based on | Meaning |
|---|---|---|
| Watch | Forecast probability moderate (default 30–60 %) | Hazard possible — be prepared |
| Warning | Forecast probability high (default > 60 %) | Hazard likely — take action |
| Live | Current measured value exceeds threshold | Hazard happening now |

Alert rule form: `P(variable exceeds threshold within horizon) > cut-off`. Cut-offs are configurable.

**Colour and type are independent (D27).** The colour (level) comes from the severity category of the event; the type says how certain it is.

| Hazard | 🟡 Yellow | 🟠 Orange | 🔴 Red |
|---|---|---|---|
| High wind (gust) | 39–49 km/h | 50–61 km/h | ≥ 62 km/h |
| Heavy rainfall (24 h) | Heavy | Very heavy | Extremely heavy |
| Heatwave | — | Heatwave | Severe heatwave |
| Hourly rain intensity, squall | — | Default (configurable) | — |

Example: a 35 % chance of gusts ≥ 50 km/h is an 🟠 **Orange Watch**; at 75 % it becomes an 🟠 **Orange Warning**; measured gusts ≥ 62 km/h give a 🔴 **Red Live** alert.

## 6.3 Requirements

| ID | Requirement | Priority |
|---|---|---|
| AL-01 | The system shall issue forecast alerts (Watch/Warning) from exceedance probabilities and live alerts from current readings. | M |
| AL-02 | Live alerts shall work independently of the forecast (safety net for missed events such as sudden squalls). | M |
| AL-03 | Each alert shall record hazard, level, type, zone/kit, forecast run, probability, expected time window, issue time and advice text. | M |
| AL-04 | **Minimum duration** before raising a live alert (e.g. 10 min for wind) to ignore single random gusts. | M |
| AL-05 | **Clear-down delay** after conditions improve (e.g. 30 min); a Live heatwave clears only after a whole local day without heatwave conditions (D35). | M |
| AL-06 | **Notification cooldown** for repeated notifications of the same alert (e.g. 1 h). | M |
| AL-07 | Forecasts shall be **rolling**: re-run every 15 min with a 72 h window; the newest run supersedes older runs for overlapping times. | M |
| AL-08 | On each run, alerts shall be created, upgraded, downgraded or cancelled; every change shall send a clear message ("Upgraded…", "Cancelled: … no longer expected"). Alerts are never removed silently: everyone who was told about an alert is told about its later changes and its end, even while it is suppressed or below their personal filters (D36). | M |
| AL-09 | **Upgrade fast, downgrade slow**: upgrade on one run; downgrade only after 2–3 consecutive lower runs. | M |
| AL-10 | **Hysteresis**: separate up/down probability cut-offs (e.g. up at 60 %, down below 45 %). | M |
| AL-11 | Alerts for events 2–3 days ahead require agreement of 2 consecutive runs; near-term alerts act on one run. | S |
| AL-12 | **Every forecast run shall be stored** (issue time, target time, values, quantiles, probabilities, model version). | M |
| AL-13 | The alert view shall show the probability trend across runs (e.g. "35 % → 75 % → 85 %"). | S |
| AL-14 | Site combination rule per hazard: heatwave = **median of kits**; heavy rain = **worst kit** (after QC); wind = **per-zone alerts** + worst kit for site status. Configurable. | M |
| AL-15 | Operators may suppress an alert with a mandatory reason and expiry; the system shall override the suppression if the level would increase (e.g. to Red). | M |
| AL-16 | Threshold changes shall apply from the next forecast run and be logged in the alert history. | M |
| AL-17 | Alerts shall use IMD colour codes (Green/Yellow/Orange/Red) and include zone-specific advice where configured. | M |

## 6.4 Example timeline (heatwave, rolling forecast)

| Day | Run covers | Forecast | Alert |
|---|---|---|---|
| Mon | Tue–Thu | Normal | None |
| Tue | Wed–Fri | Fri 35 % | 🟠 Watch (heatwave) |
| Wed | Thu–Sat | Fri 75 %, Sat 50 % | 🟠 Warning |
| Thu | Fri–Sun | Fri 85 %, Sat 70 % | Warning continues |
| Fri | live | 43 °C, +5 °C above normal | 🟠 Live (severe heatwave, > 6.4 °C above normal, would be 🔴) |
