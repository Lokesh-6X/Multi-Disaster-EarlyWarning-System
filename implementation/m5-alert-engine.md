# M5 Alert engine

**Goal:** requirements 08 §8.5 phase 5: a simulated storm triggers exactly the right alerts. The largest and most important milestone.
**Done when:** every transition-table row of design/08 is a passing test, Scenarios 2, 3, 4 and 7 pass (fake-clock integration tests, plus demo-clock end-to-end versions marked `slow`), and killing `alerts` mid-stream produces no duplicate change or email.

Work **test-first**: for each task, first turn the design table into test rows, then write the code until they pass.

---

- [ ] **M5.1 Test harness and alert tables**
  - Do: migration for `hazard_event` (seeded), `alert`, `alert_change`, `alert_run_probability`, `alert_acknowledgement`, `alert_note`, `alert_command`, `alert_suppression`, `live_condition`, `forecast_condition`, markers, `email_message`, `email_attempt`; a table-driven test helper (state + inputs → expected change) on the fake clock.
  - Check: one sample row test passes end to end through the helper.
  - Ref: [design/03 §3.9–3.10, §3.12](../design/03-database-schema.md), DD94 · Needs: M2.5

- [ ] **M5.2 Live path: gust and rain**
  - Do: per-reading evaluation; gust = 10-minute median with 80 % coverage; rain intensity (rolling 1 h vs rain-burst threshold); rain 24 h (rolling); create / upgrade / clear-down / downgrade / clear; late readings never open alerts; offline = unknown, cleared after 60 min.
  - Check: TST-12 live rows: isolated gusts ignored; one lull does not reset; clear-down timer; no-data clear.
  - Ref: [design/08 §8.6.1, §8.6.3–8.6.4](../design/08-alert-engine.md), DD64 · Needs: M5.1

- [ ] **M5.3 Live path: heatwave**
  - Do: 30-minute median vs normal + offset and region rules; level held for the day and night, decided at the end of the local day (D35); "no data" decided at the end of the day (DD120); "normal not yet calibrated" flag.
  - Check: evening cool-down keeps the alert; a cool day clears it at midnight; a 2-hour night outage keeps it; a whole day without data clears it.
  - Ref: [design/08 §8.6.1, §8.6.3–8.6.4](../design/08-alert-engine.md), DD106, DD120 · Needs: M5.2

- [ ] **M5.4 Squall rule**
  - Do: baseline and rise on `wind_avg_kmh`; mean ≥ 40 km/h for a whole minute → open or upgrade the gust Live alert to `squall_level` immediately, `trigger = squall`; precursors flag in `/live`.
  - Check: Scenario 2 onset → Orange Live; `single_gust.yaml` pattern → no alert.
  - Ref: [design/08 §8.6.2](../design/08-alert-engine.md), DD100 · Needs: M5.2

- [ ] **M5.5 Forecast path: target state and transitions**
  - Do: on `forecast.run_completed`: episodes, `qualifies(L)` with hysteresis, target level and type, create / upgrade on one run / downgrade or cancel after 3 lower runs / clear when the window has passed / stale forecast; `alert_run_probability`.
  - Check: TST-12 rows: 0.62 → Warning, 0.50 stays, 0.44 lower; exactly 3 lower runs; Orange 72 % + Red 35 % → Red Watch.
  - Ref: [design/08 §8.5.1–8.5.3](../design/08-alert-engine.md), DD63 · Needs: M5.1

- [ ] **M5.6 Forecast path: far events, whole-hour windows, `updated`**
  - Do: far-event agreement (2 runs beyond 48 h); displayed window rounded to whole hours; `updated` when the rounded start moves > 3 h or to another day.
  - Check: Scenario 3 Tue 09:00 not issued, 09:15 issued; 15-minute drift → no email; 14:00 → 20:00 → `updated`.
  - Ref: [design/08 §8.5.1, §8.5.3](../design/08-alert-engine.md), DD101, DD119 · Needs: M5.5

- [ ] **M5.7 Take-over and the Live-heatwave block**
  - Do: Live opening at the same or higher colour takes over the forecast alert whose window includes now (or starts within 6 h); hold rules; no same-or-lower forecast heatwave alert while a Live heatwave is open.
  - Check: Scenario 2 14:18 take-over; tomorrow's alert not taken over; Orange forecast blocked during Orange Live heatwave, Red allowed.
  - Ref: [design/08 §8.7, §8.5.3](../design/08-alert-engine.md), DD103, DD114 · Needs: M5.3, M5.6

- [ ] **M5.8 Multi-kit combination**
  - Do: per-kit evaluation with own thresholds, then `median` (lower middle) and `worst`; site-scope alerts for heat and rain, per-zone for wind with site status = worst zone. (`majority`, `two_kit_agreement` later.)
  - Check: TST-12 combination rows with 1, 2 and 3 kits.
  - Ref: [design/08 §8.8](../design/08-alert-engine.md), DD66 · Needs: M5.7

- [ ] **M5.9 Commands: suppress, manual alerts**
  - Do: `alert_command` processing in order with row locks; suppress (reason, expiry ≤ 24 h), unsuppress, expiry on the tick, colour-rise override; manual raise / clear; API waits 3 s then `202`; `alert.command_result`.
  - Check: Scenario 7; two suppress commands at once → one rejected.
  - Ref: [design/08 §8.9–8.10](../design/08-alert-engine.md), [design/02 §2.5](../design/02-api.md) · Needs: M5.5

- [ ] **M5.10 Notification decisions**
  - Do: per emailing change, addressees from recipient lists and user preferences (users first, `ON CONFLICT DO NOTHING`); sticky audience; end always sent (also while suppressed); escalations immediate, others within cooldown delayed and superseded; outbox rows in the same transaction; `email.queued`.
  - Check: TST-12 cooldown and sticky-audience rows; a downgrade below a recipient's minimum still reaches them.
  - Ref: [design/08 §8.11](../design/08-alert-engine.md), [design/09 §9.5](../design/09-notifications.md), DD68, DD102 · Needs: M5.9

- [ ] **M5.11 Threshold changes, restart, idempotence**
  - Do: `threshold_changed` on affected open alerts; catch-up from markers at start-up; reprocessing produces no duplicate changes or emails.
  - Check: kill `alerts` during a scenario, restart → identical final state, no duplicate rows.
  - Ref: [design/08 §8.12–8.13](../design/08-alert-engine.md) · Needs: M5.10

- [ ] **M5.12 Alerts API and scenario tests**
  - Do: endpoints of design/02 §2.6.7 (list, detail with trend and history, acknowledge with DD36, notes, advice, commands); WebSocket `alert.*`; Scenarios 2, 3, 4, 7 as fake-clock integration tests and demo-clock end-to-end tests (`slow`).
  - Check: **M5 done-when** above; ten parallel acknowledgements → one winner (TST-13).
  - Ref: [design/02 §2.6.7](../design/02-api.md), [design/12 §12.4](../design/12-testing.md) · Needs: M5.11
