# 9. Decisions

## 9.1 Decisions made

| # | Decision | Reason |
|---|---|---|
| D1 | Hazards: heatwave, heavy rainfall, high-speed wind | Measurable and forecastable with local kits |
| D2 | Cyclone prediction dropped; high-speed wind instead | Cyclones are hundreds of km wide; local kits (even 5 on one site) cannot predict them |
| D3 | BME280 added for pressure | Pressure tendency is the key signal for rain and squalls |
| D4 | DHT11 kept as backup/cross-check | Fault detection |
| D5 | Location is configuration (site config), not hard-coded | System works for any location |
| D6 | Three config layers: system defaults → site → kit, resolved per key | Minimal config per site; per-kit physical differences |
| D7 | Main model: Temporal Fusion Transformer, global model pre-trained on many Indian locations, fine-tuned per site | Multi-target, multi-horizon, quantiles, static config inputs |
| D8 | LightGBM classifier for heavy-rain probability; rules for squalls | Zero-inflated rain; squalls need instant reaction |
| D9 | Baselines: persistence, Open-Meteo, LightGBM, Chronos-Bolt | Evidence for model choice in the report |
| D10 | Alerts from forecast probabilities (Watch/Warning) plus live alerts | Lead time plus a safety net |
| D11 | Rolling 72 h forecast every 15 min; all runs stored | Accuracy by lead time, trend display |
| D12 | ~~Public read-only dashboard~~ **Revised:** no public page and no viewer accounts. Only operator and admin accounts (invited, no self sign-up) | Owner decision. Trade-off: students, staff and visitors are reached only via email alerts and operators relaying alerts |
| D13 | Alerts reach people at the site by email to configured recipient lists; operators/admins also get detailed emails and the dashboard banner | Only direct channel to people without accounts |
| D14 | Deployment out of scope; runs locally with locally installed services, no Docker | Project constraint; owner decision |
| D15 | One physical kit now; everything designed for many kits | Current hardware limit |
| D16 | No kiosk/TV view | Owner decision |
| D17 | Email is the only notification channel (SMTP; Mailpit for the local demo). SMS and Telegram are future enhancements | Owner decision; slower delivery for sudden squall Live alerts accepted |
| D18 | Sensor kit hardware and firmware are out of scope (built separately); this project defines only the kit interface ([02](02-hardware.md)) and uses the simulator until a kit is connected | Owner decision |
| D19 | No fixed first site in the requirements; the demo site is created through site onboarding ([04 §4.5](04-configuration.md)) | Location is configuration (D5) |
| D20 | ~~The 20–30 training locations are chosen during training-data preparation~~ **Revised (design phase):** a fixed list of 24 locations (8 plains, 8 coastal, 8 hilly; 3 held out) in [design/06 §6.2](../design/06-ml-training.md) (ML-01) | Reproducible training; held-out locations test ML-05 |
| D21 | Wind direction is optional in the MQTT contract; squall detection uses it when present | Works with or without a wind vane |
| D22 | MQTT message contract is final ([02 §2.4](02-hardware.md), D25); the API endpoint list is written in [design/02-api.md](../design/02-api.md) | Contracts first |
| D23 | Model-reports page (accuracy by lead time, baseline comparison, back-tests, variable importance) is in scope, visible to operators and admins | Evidence that the model works; read-only, no sensitive data |
| D24 | Alert email recipient lists are set by admins in site config; the SMTP account is an environment setting (Mailpit for the local demo) | Configuration, not a requirement |
| D25 | MQTT contract final ([02 §2.4](02-hardware.md)): readings topic + status topic with MQTT last will; no offline buffering, no separate health message, no contract version field. Readings taken during an outage are lost | Owner decision; keep the kit simple |
| D26 | One installation monitors one site. Another site means another installation with its own database and configuration (still no code changes, NFR-07). The `{site_id}` in MQTT topics must match the installation's site | Owner decision (design phase); keeps the UI, permissions and data model simple |
| D27 | Alert colour comes from the event's severity category (wind: Beaufort levels; rain: heavy = Yellow, very heavy = Orange, extremely heavy = Red; heatwave = Orange, severe heatwave = Red; rain intensity and squall: Orange by default). Watch/Warning/Live expresses certainty only. Scenarios 3 and 4 and 06 §6.4 corrected accordingly | Owner decision (design phase); the earlier scenarios mixed the two rules; IMD colours stay meaningful |
| D28 | The global TFT is trained in two stages: **TFT-base** on ERA5 with calendar-only future inputs (ML-02 split 2008–2019 / 2020–2021 / 2022–2025), then **TFT-NWP** fine-tuned with archived Open-Meteo forecasts as future inputs (2022–2023 / 2024 / 2025). The better one is used per hazard | Archived forecasts exist only from about 2022; reanalysis as a stand-in forecast would leak the future (owner decision, design phase) |
| D29 | When a Live alert opens for the same hazard event and zone at the same or a higher colour, it **takes over** the forecast alert, which closes with "Now happening — see Live alert"; the Live alert's email says what it replaces. Only a forecast alert whose window includes now is taken over; alerts for later days stay open (analysis AN-08). Scenarios 2 and 3 corrected accordingly | One alert thread per event during the event; no duplicate emails (owner decision, design phase) |
| D30 | Forecasts cover **today**: the heatwave is forecast for today and the next 3 days, and the current day's 24 h rain probability adds the rain already measured; what has already happened counts as certain. Scenario 3 updated | Without it, a Friday Warning was moved to Saturday or cancelled at midnight on Friday (analysis AN-01, AN-02) |
| D31 | The squall rule uses the **1-minute mean wind** for "reaching ≥ ~40 km/h, sustained ≥ 1 minute"; Scenarios 2 and 9 updated | One message per minute carries a single 3-second gust, so one gust met the old rule; IMD defines squalls on the mean wind (analysis AN-03) |
| D32 | The heavy-rain-burst threshold is the 99th percentile of **wet hours** (≥ 0.1 mm), never below **20 mm/h**; Scenario 4 updated | The percentile of all hours is only a few mm/h and would alert on ordinary showers (owner decision, analysis AN-11) |
| D33 | After 4–8 weeks of kit data a **normal offset** per kit (median of kit − reanalysis daily maximum) is added to the heatwave normal; until then heatwave alerts say "normal not yet calibrated" | A rooftop kit and a 28 km grid normal are different references; the readings themselves are never corrected (owner decision, analysis AN-12) |
| D34 | The dashboard is used **only on the server machine**; no access from phones or other computers | No dashboard traffic over the Wi-Fi; email links open on the control PC (owner decision, analysis AN-27) |
| D35 | A Live heatwave alert stays open overnight and clears only after a **whole local day without heatwave conditions**; Scenario 3 updated | A heatwave is a daily condition; one alert per heatwave instead of new alerts every afternoon (owner decision, analysis AN-07) |
| D36 | Everyone who was told about an alert is told about all its later changes and its end, whatever their filters, and even while it is suppressed (AL-08) | No one is left believing an alert is still active (analysis AN-05, AN-06) |
| D37 | Scope is **any location in India** (goal 5, NFR-07); other countries are future enhancement F3 | IMD hazard rules, the 08:30 IST rain day, Indian region types and Indian training locations are built in (owner decision, analysis AN-38) |
| D38 | Alert time windows are **shown to people in whole hours** (start rounded down, end rounded up), e.g. "14:00–20:00 IST"; the models keep their 3 h / 6 h blocks counted from the issue time | Readable emails; the shown window no longer shifts by 15 minutes every run (owner decision, analysis AN-34) |
| D39 | Simulated hazards never reach real people: simulator scenario and fault modes run only in demo mode (separate database); in the real installation the simulator may only stand in for a missing kit, and only while email goes to the local test inbox | A demo of a squall must not email the site's mailing list or pollute real data (analysis AN-42) |
| D40 | Model training runs on **Kaggle Notebooks GPU** instead of Google Colab (05 §5.5) | The owner trains on Kaggle; free GPU about 30 h per week with background (committed) runs that keep their output (owner decision 2026-10-30, M0.6) |
| D41 | Scheduling inside `worker` is a loop on the system clock instead of APScheduler (08 §8.4) | APScheduler reads the wall clock directly and cannot follow the demo clock; the loop runs on weather time in demo mode (week-1 check 5, owner decision 2026-10-30, M0.9) |

## 9.2 Future enhancements (not part of this project)

| # | Enhancement | Why later |
|---|---|---|
| F1 | SMS alerts (operators and site recipient lists) | Needs a paid SMS gateway; faster than email for sudden squall Live alerts |
| F2 | Telegram alerts (site channel and operator chats) | Push delivery; dropped from current scope by owner decision (D17) |
| F3 | Sites outside India | Needs that country's hazard rules and rain-day boundary as configuration, and models re-validated (or retrained) on its locations (D37) |
