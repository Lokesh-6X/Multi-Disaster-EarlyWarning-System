# 8. Third Review

A third pass after the second round of fixes (D37–D38, DD117–DD123), aimed at the rules added in the last two rounds and how they meet the older ones. It found three issues, all fixed the same day (2026-10-30). After this pass no further design issues are known; what remains are the week-1 checks on a real machine ([05 §5.3](05-scope-and-plan.md)), which the implementation plan ([09](09-implementation-plan.md)) schedules first.

| ID | Finding | Severity | Fixed by |
|---|---|---|---|
| AN-41 | "Measured maximum today" uses a different measure from the Live heatwave | Medium | DD124 |
| AN-42 | Simulator scenarios in real mode can email fake hazards to real people | Medium | D39, DD125 |
| AN-43 | Invite and password-reset links only work on the server machine | Low | D34 wording |

---

## AN-41 "Measured maximum today" uses a different measure from the Live heatwave — Medium

**Where:** the D0 heatwave probability is 1 when "the measured maximum today already meets the rule" ([07 §7.5](../design/07-forecast-worker.md), DD99). The Live heatwave uses the **30-minute median** temperature ([08 §8.6.1](../design/08-alert-engine.md)), so that one warm minute does not count.

**What happens:** the measured maximum comes from the 15-minute series (`temp_max_c`, the highest single minute). One hot minute at 13:02 (a sunlit gust of warm air, a passing vehicle exhaust near a rooftop kit) makes the D0 probability 1 → the forecast alert is **upgraded to Warning** and emailed as an escalation, while the Live rule, correctly, does not fire. Two parts of the same system disagree about whether today's heat has happened.

**Fix (DD124):** "measured maximum today" means the **highest 30-minute median temperature** of the local day, the same measure as the Live heatwave. The 24 h rain D0 is unaffected (a sum has no such problem).

---

## AN-42 Simulator scenarios in real mode can email fake hazards to real people — Medium

**Where:** `start.ps1 -Simulator <scenario>` starts the simulator against the **normal** installation ([01 §1.7.4](../design/01-architecture.md), [11 §11.8](../design/11-simulator.md)); demo data is separated only in demo mode (DD95).

**What happens:** after the real kit is installed and real recipient lists are configured, someone runs `start.ps1 -Simulator squall` to show the squall. The scenario's readings go into the real database for the real site, raise a real Orange Live alert and **email the site's mailing list** about a squall that never happened. It also pollutes real readings, model reports and the normal offset (D33).

**Fix (D39, DD125):**

| Mode | Allowed in the real installation |
|---|---|
| Scenario and fault modes | **No**. Only in demo mode (`-Demo`, separate database, `[DEMO]` emails). The simulator refuses `--scenario` and faults unless its clock is `demo`; `start.ps1` refuses `-Simulator <scenario>` without `-Demo` |
| Replay / normal mode as a stand-in kit (before the hardware exists, build-order phase 1) | Yes, but only while `SMTP_HOST` is local (Mailpit), so no email can reach real people; `start.ps1` refuses otherwise |

---

## AN-43 Invite and password-reset links only work on the server machine — Low

**Where:** D34 (dashboard only on the server machine); invite and reset links are emailed to the user ([02 §2.2.3](../design/02-api.md), WEB-02, WEB-03).

**What happens:** a new operator opens the invite email on their phone or own PC; the link points to `http://localhost:8000/invite/…` and fails. Not a defect (D34 is deliberate), but nobody would expect it.

**Fix:** say it where people meet it: the invite and reset emails say "Open this link on the control PC", the admin's Users page shows the same hint next to the invite link, and requirements 07 §7.1 mentions account links together with alert links.

---

## Checked again and sound

| Topic | Result |
|---|---|
| D30 rain D0 (measured + forecast) vs Live 24 h rain and take-over | Same rain feeds both; the Live alert takes over the forecast alert (window includes now) |
| DD114 + DD103 over a multi-day heatwave | The forecast episode always contains today while heat continues, so it is taken over; no second alert |
| DD117 two clocks vs every timer in 04 §4.3.7 | Every alert timer is weather time; every health/network timer is machine time |
| DD118 pacing vs onboarding progress and demo snapshot build | Onboarding ≈ 6 min, done once per snapshot |
| DD119 whole-hour windows vs DD101 "window moved" | Uses the rounded window; no email for 15-minute drift |
| DD120 heatwave "no data" vs offline maintenance notice | Notice still opens at once (DP-26); only the alert is kept |
| Requirement IDs, decision numbers, links across all documents | All defined and resolving |
