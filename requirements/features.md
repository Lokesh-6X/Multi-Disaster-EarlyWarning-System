# Features

A list of everything the system does, grouped by area. Each feature links to the requirement IDs that define it in detail. Priority: **M** = must have, **S** = should have, **C** = could have.

## 1. Data collection

| Feature | What it does | Priority | Requirements |
|---|---|---|---|
| MQTT ingestion | Receives one reading per minute from each kit over MQTT and stores it | M | HW-07, DP-01 |
| Contract validation | Rejects and logs messages that do not match the MQTT contract | M | DP-12 |
| Kit online/offline status | Marks a kit offline immediately when it disconnects (MQTT last will), with a 5-minute no-data timeout as backup | M | HW-12, DP-09 |
| Outage history | Records every online/offline change per kit | M | DP-13 |
| Duplicate protection | Ignores repeated messages using `(kit_id, timestamp)` | M | DP-02 |
| Raw data kept | Stores original values unchanged; cleaned values stored separately | M | DP-03 |
| Unit conversion | Rain tips → mm; station pressure → sea-level pressure | M | DP-04, DP-05 |
| Calibration | Applies each kit's calibration offsets from config | M | CFG (kit), §2.3 |
| Derived features | Pressure tendency (1 h, 3 h), rain totals (1/3/24 h), rain rate, heat index, gust trends, temperature change | M | DP-06 |
| Resampling | Builds 15-minute and hourly series for the model | M | DP-07 |
| External forecast | Fetches the Open-Meteo forecast for the site on a schedule | M | DP-10 |
| Multi-kit ready | Every record carries `kit_id`, so more kits need no redesign | M | DP-11 |

## 2. Data quality

| Feature | What it does | Priority | Requirements |
|---|---|---|---|
| Range check | Flags impossible values (e.g. temperature outside −10 to 55 °C) | M | DP-20 |
| Spike check | Flags sudden jumps (e.g. > 5 °C in 1 minute) | M | DP-21 |
| Stuck check | Flags a sensor reporting the same value for too long | M | DP-22 |
| Cross-sensor check | Flags the kit if BME280 and DHT11 temperatures differ by > 4 °C | S | DP-23 |
| Neighbour check | Compares a kit with other kits (multi-kit) | S | DP-24 |
| External check | Compares a kit with the current Open-Meteo value | S | DP-25 |
| Maintenance notice | Shows faults in kit health and notifies operators | S | DP-26 |

## 3. Configuration and site onboarding

| Feature | What it does | Priority | Requirements |
|---|---|---|---|
| Three-layer settings | System defaults → site → kit; the most specific value wins | M | CFG-01 |
| Override rules | Rejects settings changed at a level where they are not allowed | M | CFG-02 |
| Validation on save | Checks unique kit IDs, threshold order, coordinates, required fields | M | CFG-03 |
| Edit conflict protection | Rejects a save based on an outdated version | M | CFG-04, WEB-22 |
| Effective values view | Shows each setting's final value and where it came from | S | CFG-06 |
| Automatic site onboarding | Downloads 20–30 years of history, computes local normals, generates labels, finds top-10 past events, runs back-tests | M | CFG-07, §4.5 |
| Local risk per zone | Lower thresholds and zone-specific advice for exposed areas (e.g. sports ground) | S | §4.6 |

## 4. Forecasting

| Feature | What it does | Priority | Requirements |
|---|---|---|---|
| 72-hour forecast | Temperature, humidity, gust, rain and pressure, hourly up to 72 h | M | §5.3 |
| Uncertainty ranges | P10 / P50 / P90 for every value | M | §5.3 |
| Global TFT model | Pre-trained on 20–30 Indian locations; works on a new site without retraining | M | ML-01, ML-05 |
| Heavy-rain classifier | LightGBM model for the probability of heavy rain | M | §5.1 |
| Rolling forecast | Re-runs every 15 minutes; newest run replaces older ones | M | AL-07, ML-08 |
| All runs stored | Every forecast run saved with its model version | M | AL-12, ML-09 |
| Baseline comparison | Persistence, Open-Meteo, LightGBM, Chronos-Bolt on the same test data | M | ML-03 |
| Fine-tuning per site | Fine-tunes on kit data after 4–8 weeks | S | ML-06 |
| Explainability | Variable importance (TFT) and SHAP (LightGBM) | S | ML-10 |
| Short-range model | 15-minute model for 0–6 h once enough kit data exists | C | ML-07 |

## 5. Hazards and alerts

| Feature | What it does | Priority | Requirements |
|---|---|---|---|
| Heatwave detection | IMD rules by region type, based on departure from the local normal (with a per-kit normal offset after 4–8 weeks, D33); today and the next 3 days (D30) | M | §6.1 |
| Heavy-rain detection | IMD 24-hour categories plus an hourly intensity alert (wet-hour 99th percentile, at least 20 mm/h, D32) | M | §6.1 |
| High-wind detection | Beaufort-based Green/Yellow/Orange/Red gust levels | M | §6.1 |
| Squall detection | Rules on live data: pressure jump, temperature drop, sudden rise of the 1-minute mean wind (D31) | M | §5.1, §6.1 |
| Watch / Warning alerts | From forecast probabilities (30–60 % Watch, > 60 % Warning) | M | AL-01 |
| Live alerts | From measured values; work even if the forecast misses | M | AL-01, AL-02 |
| False-alarm control | Minimum duration, clear-down delay, notification cooldown | M | AL-04 – AL-06 |
| Upgrade fast, downgrade slow | Upgrade on one run; downgrade after 2–3 lower runs; separate up/down cut-offs | M | AL-09, AL-10 |
| Agreement for far events | Alerts 2–3 days ahead need 2 consecutive runs | S | AL-11 |
| Clear change messages | Every create / upgrade / downgrade / cancel is announced | M | AL-08 |
| Probability trend | Shows how the probability changed across runs | S | AL-13 |
| Multi-kit combination | Heatwave = median of kits; rain = worst kit; wind = per zone | M | AL-14 |
| Suppression with safety override | Operator can suppress with reason and expiry; overridden if the level rises | M | AL-15 |
| IMD colour codes and advice | Green/Yellow/Orange/Red with zone-specific advice | M | AL-17 |

## 6. Notifications

| Feature | What it does | Priority | Requirements |
|---|---|---|---|
| Site alert emails | Every alert change emailed to the site's recipient lists | M | WEB-40, WEB-41 |
| Operator alert emails | Detailed email with probability and an "Acknowledge" link | M | WEB-43 |
| Reliable sending | Background sending with retries, send log, no duplicates, cooldown | M | WEB-44, WEB-26 |
| Personal email preferences | Operators choose which alert emails they get | S | WEB-08 |
| Dashboard banner | Alert banner with optional sound for logged-in users | M | §7.6 |
| Local test inbox | Mailpit captures all emails during the local demo | M | WEB-46 |

## 7. Web application

| Feature | What it does | Priority | Requirements |
|---|---|---|---|
| Live dashboard | Current readings, heat index, alert banner, last-updated time, kit status | M | §7.2 |
| Forecast page | 72 h charts with shaded ranges, hazard probabilities, alert timeline | M | §7.2 |
| Alerts page | Active alerts, advice, history, probability trend | M | §7.2 |
| Operator panel | Acknowledge, internal notes, advice message, suppress, manual alert | M | §7.2 |
| Kit health | Online/offline, outage history, rejected messages, QC flags, signal, firmware | M | §7.2 |
| Configuration editor | Site and kit settings with validation and effective values | S | §7.2 |
| User management | Invite, change role, deactivate | M | §7.2 |
| Audit log | Who did what, when and why | M | WEB-25 |
| Model reports | Accuracy by lead time, baseline comparison, back-tests, variable importance | S | §7.2, D23 |
| Site map | Kits and zones coloured by alert level | C | §7.2 |
| Real-time updates | New readings, forecasts and alert changes pushed over WebSocket | M | WEB-24, NFR-01 |
| Auto-reconnect | Reconnects after network loss and shows stale data | M | NFR-04 |

## 8. Users and security

| Feature | What it does | Priority | Requirements |
|---|---|---|---|
| Two roles | Operator and admin; no public page, no self sign-up | M | §7.1 |
| First-run setup | Creates the first admin when no users exist | M | WEB-01 |
| Invitations | One-time invite link by email, expires after 48 h | M | WEB-02, WEB-03 |
| Account lifecycle | Invited → active → deactivated; never deleted | M | WEB-04 |
| Role safety | Last admin cannot be removed; admins cannot change their own role | M | WEB-05 |
| Password security | Hashed passwords, lockout after 5 failures, 8 h sessions | M | WEB-06 |
| Backend permissions | Every endpoint checks the role; nothing readable without login | M | WEB-21 |
| Atomic acknowledgement | First operator to acknowledge wins | M | WEB-23 |
| Rate limiting | Per user, and per IP for login | S | NFR-03 |
| Secrets outside code | MQTT and SMTP credentials in an environment file | M | NFR-08 |

## 9. Kit simulator and testing

| Feature | What it does | Priority | Requirements |
|---|---|---|---|
| Replay mode | Replays a real past weather event at any speed | M | TST-01 |
| Scenario mode | Generates storms, rain bursts, heat build-up | M | TST-02 |
| Fault mode | Stuck values, spikes, duplicates, clock skew, malformed messages, disconnects | M | TST-03 |
| Multi-kit mode | Several kits with realistic differences | S | TST-04 |
| Automated tests | Config, QC, alerts, concurrency, permissions, end-to-end | M | TST-10 – TST-16 |
| Back-tests | Lead-time report on past extreme events per site | M | TST-15 |

## 10. Running the system

| Feature | What it does | Priority | Requirements |
|---|---|---|---|
| Local run, no Docker | Locally installed services, setup guide, one start script | M | NFR-05 |
| UTC storage, local display | Stored in UTC, shown in the site timezone | M | NFR-06 |
| Configuration only | New kits and sites need no code changes | M | NFR-07 |

## Not included

| Item | Status |
|---|---|
| Sensor kit hardware and firmware | Built separately (D18) |
| Deployment, Docker | Out of scope (D14) |
| Public page, viewer accounts, kiosk/TV | Out of scope (D12, D16) |
| Cyclone prediction | Out of scope (D2) |
| SMS and Telegram alerts | Future enhancements (F1, F2) |
