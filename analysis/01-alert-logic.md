# 1. Alert and Forecast Logic

The alert rules of [design/07](../design/07-forecast-worker.md) and [design/08](../design/08-alert-engine.md) traced through the real-time scenarios, minute by minute and run by run. Most rules work; the problems below appear at the **edges of time windows** (midnight, the end of the rain day) and in **who gets told** when an alert changes.

Summary:

| ID | Finding | Severity |
|---|---|---|
| AN-01 | Heatwave forecast never covers today | High |
| AN-02 | Rain-day probability ignores rain that has already fallen | High |
| AN-03 | Squall "sustained 1 minute" is met by one 3-second gust | High |
| AN-04 | Alert window moves without telling anyone | Medium |
| AN-05 | An alert that ends while suppressed ends silently | Medium |
| AN-06 | People who were told about an alert may not be told it ended | Medium |
| AN-07 | A multi-day heatwave restarts its alerts every day | Medium |
| AN-08 | Take-over closes forecast alerts for a later day | Medium |
| AN-09 | Live 24 h rain alert stays on for up to a day after the rain stops | Low |
| AN-10 | A cancellation can be held back for up to an hour | Low |

---

## AN-01 Heatwave forecast never covers today — High

**Where:** heatwave probability windows are local days **D1–D3** (tomorrow to 3 days ahead) in [06 §6.6](../design/06-ml-training.md), [07 §7.5](../design/07-forecast-worker.md), [08 §8.2](../design/08-alert-engine.md) and DD55. The requirement says "forecast 1–3 days ahead" ([requirements 06 §6.1](../requirements/06-hazards-and-alerts.md)).

**What happens** (Scenario 3, Orange Warning for Friday, Thursday's run gave Friday 85 %, Saturday 70 %):

| Time (IST) | Run's windows | What the engine does |
|---|---|---|
| Thu 23:45 | Fri, Sat, Sun | Warning for Friday continues |
| Fri 00:00 | **Sat, Sun, Mon** (Friday is now "today" = D0, not forecast) | The alert's episode becomes the earliest qualifying window: Saturday 70 %. Target is "equal" (Orange Warning), so the window is **silently changed from Friday to Saturday** ([08 §8.5.3](../design/08-alert-engine.md), "update probability and window silently") |
| Fri 14:00 | — | Live heatwave opens and **takes over** the forecast alert, which is now about Saturday |
| Fri 14:15 | Sat, Sun, Mon | No open forecast alert; Saturday starts in ≈ 10 h, more than the 6 h take-over hold, so a **new** Saturday Warning is created: new emails, new acknowledgement |

If Saturday had *not* qualified, the three runs after midnight would count as "lower" and the Friday Warning would be **cancelled at about 00:45 on Friday** with "Cancelled: no longer expected", on the very day of the heatwave.

**Why it matters:** the most important day of a heatwave is the one that has already started. Scenario 3 (Watch → Warning → Live takes over the Warning) cannot happen as designed.

**Suggested fix:**

1. Add a **D0** window: "the rest of today", from the issue time to the end of the local day.
2. Its probability uses the **maximum already measured today** together with the forecast for the remaining hours: if the measured maximum already meets the rule, the probability is 1.
3. Requirement 06 §6.1: "forecast 1–3 days ahead" → "today and the next 3 days". DD55 revised. Classifiers are trained for D1–D3 only, so D0 uses the TFT-derived probability (as DD59 already does for other non-trained cases).

---

## AN-02 Rain-day probability ignores rain that has already fallen — High

**Where:** 24 h rain probability per IMD rain day (03:00 UTC to 03:00 UTC), days D0–D2 ([06 §6.6](../design/06-ml-training.md)); the sum is built from the **forecast hours of the window only** ([06 §6.8.4](../design/06-ml-training.md)). No document adds the rain measured since the rain day began.

**What happens:** heavy rain since morning; by 01:00 UTC the kit has measured 80 mm in the current rain day.

| Run (UTC) | Forecast hours left in D0 | P(D0 ≥ 64.5 mm) as designed | Correct |
|---|---|---|---|
| 18:00 | 9 | depends on the next 9 hours only | ≈ 1 (80 mm already fell) |
| 02:00 | 1 | ≈ 0 | 1 |

As the rain day runs out, the forecast probability falls towards zero, so the forecast Yellow Warning is downgraded and then **cancelled ("no longer expected") while the heavy rain day is happening**. The Live rain alert (rolling 24 h) may be open at the same time, so people receive "Cancelled" and "Live" for the same rain.

**Suggested fix:** for D0, P(measured so far + forecast for the remaining hours ≥ threshold). If the measured amount already meets the level, P = 1. Same rule as AN-01: "already happened" counts. Document in 06 §6.8.4 and 07 §7.5.

---

## AN-03 Squall "sustained 1 minute" is met by one 3-second gust — High

**Where:** squall rule in [08 §8.6.2](../design/08-alert-engine.md): "the last readings covering ≥ `squall_sustain_s` (60 s) all have gust ≥ 40 km/h".

**What happens:** a kit sends **one message per minute** (HW-07), and that message's gust is the **highest 3-second average** in the minute (HW-04). One message already "covers 60 s", so the rule is met by **a single 3-second gust**. Example: calm baseline 8 km/h, one gust of 42 km/h → rise 34 ≥ 30, gust ≥ 40, "sustained" → 🟠 **Orange Live** alert at once, emails to every recipient list and operator, without any minimum duration (squalls skip AL-04).

**Why it matters:** the squall rule is the one path that deliberately bypasses the false-alarm protection, so it must not trigger on a single gust. The IMD/WMO squall definition is about the **mean wind** ("a sudden increase of the mean wind speed by at least 3 Beaufort stages, rising to force 6 or more and lasting at least one minute"), which the kit also sends as `wind_avg_kmh` (the 1-minute mean).

**Suggested fix:**

| Part of the rule | Use |
|---|---|
| Sudden rise ≥ `squall_rise_kmh` over the baseline | `wind_avg_kmh` (or gust, both are defensible) |
| Reaching ≥ `squall_min_gust_kmh` and lasting ≥ 1 minute | **`wind_avg_kmh`** of the minute ≥ the threshold (a 1-minute mean ≥ 40 km/h is genuinely sustained) |

Rename `squall_min_gust_kmh` → `squall_min_wind_kmh`. Also update the simulator's `squall.yaml` ([11 §11.4.2](../design/11-simulator.md)): its onset step has `wind_avg_kmh: 35`, which would not trigger the corrected rule; use ≥ 40.

---

## AN-04 Alert window moves without telling anyone — Medium

**Where:** [08 §8.5.3](../design/08-alert-engine.md): when the target is "equal", "update probability and window silently".

**What happens:** an Orange Watch is emailed for "14:00–18:00". Later runs move the episode to 20:00–23:00 at the same level. The alert's window changes, but no email is sent, so recipients still prepare for the afternoon. AN-01 is an extreme case of the same rule (Friday → Saturday).

**Suggested fix:** a new change kind `updated` (not an escalation: no new acknowledgement, cooldown applies) when the window **start** moves by more than a set amount (e.g. `alert_window_shift_notify_h` = 3 h) or moves to another day. Small shifts stay silent. Subject: `[ORANGE WATCH] Updated: High wind – … – 20:00–23:00 IST`.

---

## AN-05 An alert that ends while suppressed ends silently — Medium

**Where:** [08 §8.9](../design/08-alert-engine.md): a suppressed alert sends no emails; "closing the alert ends the suppression (`alert_closed`)" with no email; [08 §8.11](../design/08-alert-engine.md): "suppressed alerts queue nothing".

**What happens:** Scenario 7 variant. 15:00 a Yellow Watch is emailed. 15:05 an operator suppresses it until 17:00. 16:00 the forecast no longer expects wind and the Watch is **cancelled** while suppressed. Nobody is emailed. Recipients were told about a Watch and are never told it ended.

**Why it matters:** AL-08 says alerts are never removed silently.

**Suggested fix:** suppression silences **updates**, not the **end**. A `cancelled` or `cleared` change is always emailed to everyone who received an earlier email about that alert.

---

## AN-06 People who were told about an alert may not be told it ended — Medium

**Where:** addressee selection is done **per change** ([08 §8.11](../design/08-alert-engine.md)): recipient `min_level`, operator `min_level` and alert `types` are checked against each change.

**What happens:**

| Change | Level | Recipient with `min_level = orange` |
|---|---|---|
| created | 🟠 Orange Warning | emailed |
| downgraded | 🟡 Yellow Warning | not emailed (yellow < orange) |
| cancelled | 🟡 | not emailed |

The recipient's last message says Orange Warning. The same happens to an operator whose preferences exclude `live`: they get the forecast Warning, the Warning is `taken_over` (no email by design), and the Live alert that replaces it is filtered out.

**Suggested fix:** a **sticky audience**: anyone emailed about an alert receives every later change of that alert, whatever their filters; the Live alert that takes over another alert is also sent to that alert's audience. Filters decide only who is told **first**.

---

## AN-07 A multi-day heatwave restarts its alerts every day — Medium (owner decision)

**Where:** live heatwave holds while the **30-minute median temperature** is above the rule; clear-down 120 min ([08 §8.6.1](../design/08-alert-engine.md), [04 §4.3.7](../design/04-configuration.md)).

**What happens** during a 3-day heatwave: every afternoon the Live alert opens (emails, acknowledgement); every evening, two hours after the temperature drops, it **clears** (emails "Cleared"). Each opening takes over the forecast alert, and the next run creates a new forecast alert for the next day (AN-08). Per day: created, taken over, re-created, cleared, i.e. about three emails per audience and two acknowledgements, for one continuing heatwave.

**Why it matters:** heatwave is a **daily** phenomenon (based on the daily maximum); an evening drop is not the end of a heatwave. Recipients would learn to ignore these emails.

**Options:**

| Option | Behaviour |
|---|---|
| A (suggested) | A live heatwave stays open until a local day ends **without** meeting the rule; it is cleared the next morning, not every evening |
| B | Keep the daily open/clear, but do not take over a forecast alert for a later day (AN-08) and send "Cleared for today" without asking for a new acknowledgement next day |

---

## AN-08 Take-over closes forecast alerts for a later day — Medium

**Where:** [08 §8.7](../design/08-alert-engine.md): when a Live alert opens, "the open forecast alert of the same (event, zone) with colour ≤ C" is closed. There is no check on **when** that forecast alert's window is.

**What happens:** there is one open forecast alert per (event, source, zone). If today's heat is measured while the open forecast alert is about **tomorrow**, the Live alert closes it ("Now happening — see Live alert"), which is wrong for tomorrow, and the next run re-creates it.

**Suggested fix:** take over only a forecast alert whose window **includes now** (or starts within `live_takeover_hold_h`). Forecast alerts for later episodes stay open.

---

## AN-09 Live 24 h rain alert stays on for up to a day after the rain stops — Low

**Where:** live `rain_24h` uses the **rolling** 24 h sum ([08 §8.6.1](../design/08-alert-engine.md)).

**What happens:** 70 mm fall between 06:00 and 10:00, then it is dry. The rolling sum stays ≥ 64.5 mm until about 06:00 the next day, so the Yellow Live alert "Heavy rainfall, happening now" stays open for about 20 hours of dry weather.

**Suggested fix:** acceptable if the email/UI wording says "64.5 mm or more in the last 24 h" rather than "happening now". Alternative: clear when the last hour has been dry for `cleardown_rain_min` **and** the IMD rain day has ended.

---

## AN-10 A cancellation can be held back for up to an hour — Low

**Where:** downgrades, cancels and clears within the 60-minute cooldown are delayed ([08 §8.11](../design/08-alert-engine.md), DD68).

**What happens:** a Warning is created at 12:30 and cancelled at 13:00; the "Cancelled" email waits until 13:30. People may stop outdoor work for half an hour longer than needed.

**Suggested fix:** accept and state it (safety errs on the cautious side), or exempt `cancelled` / `cleared` from the cooldown when the previous email was a Warning or Live alert.

---

## What was checked and works

| Rule | Traced with | Result |
|---|---|---|
| Upgrade fast, downgrade after 3 lower runs, hysteresis | Scenario 2 runs 11:00–12:30 ([08 §8.5.4](../design/08-alert-engine.md)) | Correct |
| Far-event agreement | Scenario 3 Tue 09:00 / 09:15 | Correct (episode ≈ 63 h ahead > 48 h) |
| Squall → Orange Live → Red after 10 min median → clear-down 30 min | Scenario 2 14:18–15:15 | Correct apart from AN-03 |
| Rolling hours make every run new (DD56) | 07 §7.3 | Sound; run-counting rules are meaningful |
| One open alert per (event, source, zone); first-click-wins acknowledgement | 03 §3.9 | Correct, race-free |
| Escalations bypass cooldown and suppression colour override | Scenario 7 | Correct |
| Offline kit = unknown, not calm | Scenario 5 | Correct |
| Live alerts independent of forecasts (AL-02) | 08 §8.6 | Correct |
