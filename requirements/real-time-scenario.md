# Real-Time Scenarios

Step-by-step examples of how the system behaves in real situations. They show how the requirements work together and can be used as demo scripts and test cases (they can all be produced with the kit simulator, [08 §8.2](08-non-functional-and-testing.md)).

**Example setup used below** (values are illustrative):

| Item | Value |
|---|---|
| Site | "ABC College", coastal, timezone Asia/Kolkata (times below are IST) |
| Kit | KIT-01, zone "Main Block Rooftop" |
| Wind levels | Yellow 39, Orange 50, Red 62 km/h (gust) |
| Alert cut-offs | Watch 30–60 %, Warning > 60 %, downgrade below 45 % |
| Alert behaviour | Live wind minimum duration 10 min, clear-down 30 min, notification cooldown 1 h |
| Recipients | Site mailing list + 2 operators + 1 admin |

---

## Scenario 1 — A normal minute (one reading's journey)

| Time | What happens | Requirements |
|---|---|---|
| 09:31:00 | KIT-01 publishes a reading to `sites/abc/kits/KIT-01/readings` | HW-07 |
| 09:31:00.2 | Ingestion receives it, checks it against the contract, stores the raw values with the kit and server timestamps | DP-01, DP-03, DP-12 |
| 09:31:00.3 | Calibration and conversion (3 rain tips → 0.84 mm; pressure → sea level) | DP-04, DP-05 |
| 09:31:00.4 | Quality checks pass: valid | DP-20 – DP-23 |
| 09:31:00.5 | Derived features updated (pressure tendency, rain totals, heat index) | DP-06 |
| 09:31:01 | Server pushes the reading over WebSocket; every open dashboard updates | WEB-24, NFR-01 (< 5 s) |
| 09:45:00 | Forecast worker runs: new 72 h forecast stored; Forecast page refreshes | AL-07, AL-12 |

---

## Scenario 2 — Thunderstorm squall (high wind)

| Time | What happens | Alert state | Requirements |
|---|---|---|---|
| 11:00 | Forecast run: P(gust ≥ 50 km/h, 14:00–18:00) = 35 % | 🟠 **Watch** created | AL-01 |
| 11:00 | Email to site list: `[ORANGE WATCH] High wind – Main Block Rooftop – 14:00–18:00 IST` with advice text; operators get the detailed version | | WEB-40, WEB-43 |
| 11:15 – 12:15 | Runs show 38 %, 41 %, 44 % | Watch continues; trend shown "35 % → 44 %" | AL-13 |
| 12:30 | Run shows 72 % | 🟠 Upgraded to **Warning** on one run | AL-09 |
| 12:30 | Email: "Upgraded: High wind Warning…" | | AL-08 |
| 12:40 | Operator Priya acknowledges. Operator Ravi clicks a second later and sees "Already acknowledged by Priya at 12:40" | | WEB-23 |
| 14:10 | Live data: pressure jumps +2 hPa in 10 min, temperature drops 4 °C, humidity rises | Squall rule flags squall precursors | §6.1 |
| 14:18 | The 1-minute mean wind jumps from 10 to 42 km/h (gusts to 55 km/h) and the mean stays ≥ 40 km/h for a full minute (D31) | 🟠 **Live** high-wind alert, triggered by the squall rule (immediate). It **takes over** the forecast Warning, which closes with "Now happening — see Live alert" (D29) | AL-02 |
| 14:18 | Email: `[ORANGE LIVE] High wind (squall) – Main Block Rooftop – now`, noting that it replaces the Warning | | WEB-40, AL-08 |
| 14:18 – 14:28 | The median gust of the last 10 minutes stays ≥ 62 km/h | | AL-04 |
| 14:28 | | 🔴 Live alert **upgraded to Red** | AL-04, AL-17 |
| 14:28 | Email: `[RED LIVE] High wind – Main Block Rooftop – now` | | WEB-40 |
| 14:45 | Gusts fall below 39 km/h | Clear-down timer starts (30 min) | AL-05 |
| 15:15 | Still calm | Live alert **cleared**; email "Cleared" | AL-05, AL-08 |
| 15:15 onwards | Forecast runs stay below the Watch cut-off | No new forecast alert | AL-10 |

Notes: no repeated email for the same alert within 1 hour (AL-06), **except escalations** (higher colour or more certain type, e.g. the 14:28 Red upgrade), which are always sent at once. Alerts are never removed without a message (AL-08).

---

## Scenario 3 — Heatwave over several days (rolling forecast)

Local normal maximum for these dates: 33.5 °C. Coastal rule: max ≥ 37 °C and ≥ 4.5 °C above normal.

| Day | Forecast for Friday | Alert | Requirements |
|---|---|---|---|
| Mon | 36 °C (no heatwave) | None | §6.1 |
| Tue, 09:00 run | 38.5 °C, P = 35 % (3 days ahead) | Not issued yet: far events need 2 consecutive runs | AL-11 |
| Tue, 09:15 run | P = 37 % again | 🟠 **Watch** created (heatwave = Orange); email sent | AL-11, WEB-40 |
| Wed | P = 75 % | 🟠 Upgraded to **Warning** (same colour, more certain) | AL-09 |
| Thu | P = 85 % | Warning continues; trend "35 % → 75 % → 85 %" | AL-13 |
| Fri, 00:00 run | Friday is now "today": forecast for the rest of the day, plus the maximum measured so far; P = 88 % | Warning for Friday continues (D30) | §6.1 |
| Fri, 14:00 | Measured 39.2 °C (+5.7 °C above normal) | 🟠 **Live** heatwave alert; heat index shown with heat-stress advice. It takes over the forecast Warning for Friday (D29). (A severe heatwave, > 6.4 °C above normal, would be 🔴 Red) | AL-01, §6.1 |
| Fri night | Temperature falls in the evening | Live alert **stays open** overnight: a heatwave is a daily condition (D35) | AL-05 |
| Sat | Max only 34 °C; runs show no heatwave for the coming days | At the end of Saturday, the first whole day without heatwave conditions, the Live alert is cleared with a message; no new forecast alert | AL-05, AL-08 |

With several kits, the site heatwave status uses the **median** of the kits (AL-14).

---

## Scenario 4 — Sudden heavy rain burst

Site rain-burst threshold (from onboarding: 99th percentile of wet hours, never below 20 mm/h, D32): 28 mm/h.

| Time | What happens | Alert | Requirements |
|---|---|---|---|
| 06:00 | LightGBM: P(heavy rain on the current rain day, ending 08:30 tomorrow) = 55 % | 🟡 **Watch** (heavy rainfall = Yellow) | §5.1, AL-01 |
| 16:00 – 17:00 | Rain gauge sends 100 tips in one hour → 28 mm | 🟠 **Live** hourly-intensity alert ("waterlogging likely"; Orange by default) | §6.1 |
| 16:00 – 17:00 | Email to site list with advice to avoid low-lying areas | | WEB-40 |
| 06:00 → next 06:00 | 24 h total reaches 70 mm | 🟡 **Live** heavy rainfall (64.5–115.5 mm); very heavy would be 🟠, extremely heavy 🔴 | §6.1 |

With several kits, the site rain status uses the **worst kit** after quality checks (AL-14).

---

## Scenario 5 — Kit goes offline

| Time | What happens | Requirements |
|---|---|---|
| 10:02 | KIT-01 loses power | |
| 10:02 | Broker publishes the kit's last will `offline` to `sites/abc/kits/KIT-01/status` | HW-12 |
| 10:02 | Server marks KIT-01 offline, stores the event in outage history, pushes it to dashboards | DP-09, DP-13, WEB-24 |
| 10:02 | Dashboard shows "Offline" and the time of the last reading; operators get a maintenance notice | §7.2, DP-26 |
| 10:02 – 10:40 | No readings arrive; they are lost (no offline buffering). Live alerts cannot fire for this kit while it is offline | HW-09 |
| 10:40 | Power returns; kit publishes `online` and resumes readings | HW-12 |
| 10:40 | Kit marked online; outage 10:02–10:40 recorded on the kit health page | DP-13 |

If the broker itself fails (no last will possible), the 5-minute no-data timeout marks the kit offline (DP-09).

---

## Scenario 6 — Faulty sensor

| Time | What happens | Requirements |
|---|---|---|
| 13:00 | BME280 reads 41 °C, DHT11 reads 34 °C (difference 7 °C) | DP-23 |
| 13:00 | Kit flagged; readings marked **suspicious** | §3.3 |
| 13:05 | BME280 temperature jumps 6 °C in one minute → that value marked **faulty** and excluded; the DHT11 value is used instead, marked suspicious (less accurate backup) | DP-21, DP-23 |
| 13:05 | Kit health page shows the flags; operators get a maintenance notice | DP-26 |
| — | Faulty readings do not trigger Live alerts or feed the forecast | §3.3 |

---

## Scenario 7 — Operator suppresses an alert

| Time | What happens | Requirements |
|---|---|---|
| 15:00 | 🟡 Yellow wind Watch active for the site | |
| 15:05 | Operator suppresses it: reason "Known construction crane test, safe", expiry 17:00 | AL-15 |
| 15:05 | Action written to the audit log | WEB-25 |
| 15:40 | New run raises the level to 🔴 Red | |
| 15:40 | Suppression is **overridden** automatically; Red alert issued and emailed | AL-15 |

---

## Scenario 8 — Admin changes a threshold

| Time | What happens | Requirements |
|---|---|---|
| 10:00 | Admin A and Admin B both open KIT-01 config (version 7) | |
| 10:03 | Admin A sets `wind_orange_kmh` to 45 and saves → version 8 | CFG-03, CFG-04 |
| 10:04 | Admin B saves a change based on version 7 → rejected: "Someone else changed this config. Reload." | WEB-22 |
| 10:03 | Change written to the audit log; dashboards notified of the config change | WEB-25, WEB-24 |
| 10:15 | Next forecast run uses the new threshold; the change is noted in alert history | CFG-05, AL-16 |

---

## Scenario 9 — Demo with the simulator

| Step | What happens | Requirements |
|---|---|---|
| 1 | Start all services with the start script in demo mode; the demo database is restored from a prepared snapshot (onboarding done, 7 days of history), so forecasts run from the first minute | NFR-05 |
| 2 | Simulator in **replay mode** replays a real past heatwave at 60× speed | TST-01 |
| 3 | Dashboard shows readings arriving live; forecasts and alerts follow | NFR-01 |
| 4 | Switch to **scenario mode**: 4 hPa pressure drop, then a squall (pressure jump, temperature drop, mean wind 42 km/h with 55 km/h gusts) | TST-02 |
| 5 | Squall Live alert fires; email appears in the Mailpit inbox | WEB-46, TST-14 |
| 6 | Switch to **fault mode**: disconnect the simulated kit | TST-03 |
| 7 | Kit shown offline within seconds via last will | HW-12, DP-09 |
| 8 | Open the model-reports page: back-test results for the site's top past events | TST-15, D23 |
