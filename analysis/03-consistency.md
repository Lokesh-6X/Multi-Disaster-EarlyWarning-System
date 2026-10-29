# 3. Consistency Between Documents

Places where two documents say different things, and numbers that are wrong. The earlier consistency check (links, decision numbers, requirement IDs, config keys) was clean; these are differences in **meaning**, found by reading the documents against each other.

| ID | Finding | Severity |
|---|---|---|
| AN-18 | Acknowledgement key described two ways | Low |
| AN-19 | API config example uses key names that do not exist | Medium |
| AN-20 | Replay message rates are 60× too high | Low |
| AN-21 | Very late readings: "aggregated" in DD45, not aggregated in 05 | Low |
| AN-22 | Forecast run IDs look like integers in one example and UUIDs in another | Low |
| AN-23 | Scenario 4 says "next 24 h", the design uses IMD rain days | Low |
| AN-24 | Run-ID chunks and retention assume 96 runs per day | Low |

---

## AN-18 Acknowledgement key described two ways — Low

| Document | Says |
|---|---|
| [design/01 §1.2](../design/01-architecture.md) (operator actions table) | `alert_acknowledgement`, "whose primary key is the **alert**" |
| [design/03 §3.9.3](../design/03-database-schema.md), DD27, DD36 | Primary key **(alert, escalation change)**: every escalation needs a new acknowledgement |

03 is the later, deliberate decision (DD36). **Fix:** 01 §1.2 → "keyed by the alert and its latest escalation; the first insert wins".

---

## AN-19 API config example uses key names that do not exist — Medium

[design/02 §2.6.8](../design/02-api.md), `PUT /config/kits/KIT-01` example:

| In the API example | Actual key ([design/04 §4.3](../design/04-configuration.md), DD37) |
|---|---|
| `"zone"` | `kit_zone` |
| `"calibration": { "temp_offset", "humidity_offset", "pressure_offset" }` (nested) | `cal_temp_offset_c`, `cal_rh_offset_pct`, `cal_pressure_offset_hpa` (flat) |
| "`enabled: false` retires a kit" | `kit_enabled: false` |

**Why Medium:** the frontend types are generated from the API schema (DD9), and the validator rejects unknown keys (`UNKNOWN_KEY`). Whoever builds the config editor from 02 would send keys the backend refuses. **Fix:** make the 02 example use the flat keys of 04, as the YAML example in 04 §4.6 already does.

---

## AN-20 Replay message rates are 60× too high — Low

At 60× speed a kit that sends one message per simulated minute sends **one message per real second**.

| Document | Says | Correct |
|---|---|---|
| [design/05 §5.9](../design/05-data-pipeline.md) | "5 kits, replay 60×: 300 messages/s" | 5 messages/s |
| [design/13 §13.1](../design/13-frontend-performance.md) | "up to 60 readings/s per kit" | 1 reading/s per kit (2/s at 120×) |
| [design/13 §13.3.5](../design/13-frontend-performance.md) | "60 replayed readings in one second" | — |

The designs built on these numbers (batched commits, frame-coalesced rendering) still work, with a large margin; only the numbers are wrong. Fix the text so the report does not quote them.

---

## AN-21 Very late readings: "aggregated" in DD45, not aggregated in 05 — Low

| Document | Says about readings more than 3 h late |
|---|---|
| DD45 | "stored and **aggregated** but not used for features or live alerts" |
| [design/05 §5.5.3](../design/05-data-pipeline.md) | "folded into `reading_1h` **if within 26 h**" |
| [design/03 §3.6.2](../design/03-database-schema.md) | Refresh windows: 15 min aggregate 3 h, hourly aggregate 26 h |

Readings between 26 h and 7 days late (still accepted by the timestamp window, DD42) are stored in `reading_clean` but **never** reach either aggregate, and readings 3–26 h late reach `reading_1h` but not `reading_15m`. **Fix:** either correct DD45 ("aggregated only within the refresh windows") or have `ingest` call `refresh_continuous_aggregate` for the affected buckets when such a reading arrives. Since kits do not resend after outages (HW-09), such readings are rare; correcting the text is enough.

---

## AN-22 Forecast run IDs look like integers in one example and UUIDs in another — Low

`forecast_run.id` is a `bigint` ([design/03 §3.7.2](../design/03-database-schema.md)). [design/02](../design/02-api.md) shows `"latest_run_id": "4817"` in `/live` but `"id": "f9…"` (UUID-style) in `/forecast/latest` and `/forecast/latest/probabilities`. IDs are opaque strings to clients, so nothing breaks, but the examples should agree (`"4817"`).

---

## AN-23 Scenario 4 says "next 24 h", the design uses IMD rain days — Low

[requirements/real-time-scenario.md](../requirements/real-time-scenario.md) Scenario 4: "LightGBM: P(heavy rain in **next 24 h**) = 55 %". The design forecasts heavy rain per **IMD rain day** (08:30 IST to 08:30 IST, D0–D2, DD55). **Fix:** "P(heavy rain on today's rain day, ending 08:30 tomorrow) = 55 %".

---

## AN-24 Run-ID chunks and retention assume 96 runs per day — Low

Forecast tables are partitioned by `run_id`, with "672 runs ≈ 7 days" per chunk and retention of 400 days ([design/03 §3.7.2, §3.14](../design/03-database-schema.md)). Run IDs are also used by **shadow** runs (Chronos-Bolt, 24 per day when enabled) and failed runs. With shadow runs on, 672 IDs are about 5.6 days and "400 days" becomes about 320 days.

**Fix:** state retention in run IDs with this caveat, or have the retention job compute the cut-off run ID from `issue_time` (look up the first run older than 400 days and drop chunks below it).

---

## Checked and consistent

| Topic | Result |
|---|---|
| Enum values in 03 §3.4 vs API enums in 02 §2.6.7 | Match |
| Every hypertable's primary key includes its partitioning column (TimescaleDB requirement) | Yes |
| No foreign key points **into** a hypertable | Correct (FKs only from hypertables to regular tables) |
| `UNIQUE NULLS NOT DISTINCT` needs PostgreSQL ≥ 15 | Fine with 16/17 |
| Config cross-key rules (04 §4.4) vs defaults | Defaults satisfy all rules (`0.20 < 0.30 ≤ 0.45 < 0.60`, 39 < 50 < 62, …) |
| Colour rules D27 across 04, 06, 08, 09 | Consistent |
| Process ownership of tables (01 §1.2 vs 03 §3.15) | Consistent |
