# Site Weather-Hazard Early-Warning System — Analysis

A critical review of the finished [requirements](../requirements/README.md) and [design](../design/README.md), done **before any code is written**. The aim is to catch logic errors, contradictions and risks while they are still cheap to fix (a sentence in a document), not after they are built into code and tests.

Started and completed 2026-10-30. All findings have been applied to requirements and design (decisions D30–D36 and DD99–DD113); [06-action-list.md](06-action-list.md) shows where each one went.

## Documents

| # | File | Covers |
|---|---|---|
| 1 | [01-alert-logic.md](01-alert-logic.md) | Alert and forecast logic traced step by step through the scenarios: where the rules give the wrong result |
| 2 | [02-data-and-models.md](02-data-and-models.md) | Whether the data and models can deliver what the alerts assume: thresholds, normals, baselines, data availability, compute |
| 3 | [03-consistency.md](03-consistency.md) | Places where two documents say different things, and wrong numbers |
| 4 | [04-demo-and-operations.md](04-demo-and-operations.md) | Demo mode, installation, broker, network access, start-up order |
| 5 | [05-scope-and-plan.md](05-scope-and-plan.md) | Size of the system, critical path, week-1 checks, what to simplify if time runs short |
| 6 | [06-action-list.md](06-action-list.md) | Every finding with its fix, the documents to change, and the decisions the owner must make |
| 7 | [07-second-review.md](07-second-review.md) | Second full pass after the fixes: demo-time timers, Open-Meteo limits, alert window display, rule interactions (AN-32 – AN-40) |
| 8 | [08-third-review.md](08-third-review.md) | Third pass: interactions of the newest rules (AN-41 – AN-43) |
| 9 | [09-implementation-plan.md](09-implementation-plan.md) | **Implementation plan**: milestones M0–M9, ML track T1–T8, tasks, tests and "done when" |
| 10 | [10-fourth-review.md](10-fourth-review.md) | Fourth pass: the implementation plan checked against the design (AN-44 – AN-48) |

## How findings are written

Each finding has an ID **AN-nn** so it can be referred to in the documents, decisions and tests, like the requirement IDs.

| Severity | Meaning |
|---|---|
| **High** | The system would give a wrong or unsafe alert, or the demo would not work, if built as designed |
| **Medium** | Wrong or confusing behaviour in some situations, or a risk that could cost days |
| **Low** | Wording, a wrong number in a document, or a small inefficiency |

Every finding says **where** it is, **what happens** (usually with a short traced example), **why it matters** and **a suggested fix**.

## Summary

31 findings: 8 High, 13 Medium, 10 Low. The architecture (five processes, PostgreSQL hand-off, one writer of alert state, outbox) holds up well; no finding needs it changed. The problems sit in a few rules at the edges of time windows, in how rain and heat thresholds meet real kit data, and in demo mode.

The High findings:

| ID | Finding | Document |
|---|---|---|
| AN-01 | The heatwave forecast never covers **today**, so Friday's Warning is silently moved to Saturday, or cancelled, at midnight, and Scenario 3 cannot happen | [01](01-alert-logic.md) |
| AN-02 | The 24 h rain probability for the current rain day ignores the rain that has **already fallen** | [01](01-alert-logic.md) |
| AN-03 | The squall rule's "sustained for 1 minute" is met by a **single 3-second gust**, so one gust can raise an Orange Live alert and email everyone | [01](01-alert-logic.md) |
| AN-11 | The "99th-percentile hourly rain" threshold is probably only a few mm/h, so ordinary showers would raise "waterlogging likely" alerts | [02](02-data-and-models.md) |
| AN-12 | Heatwave "above normal" compares a kit (often a rooftop) with a 28 km reanalysis grid normal, so the departure is biased | [02](02-data-and-models.md) |
| AN-25 | In demo mode, TimescaleDB retention and compression run on the **real** clock and can delete or compress the 2024 demo data during a demo | [04](04-demo-and-operations.md) |
| AN-26 | A freshly reset demo has no forecasts for hours: onboarding must finish and 7 days of history are needed, and Open-Meteo is switched off in demo mode | [04](04-demo-and-operations.md) |
| AN-28 | Mosquitto keeps at most 1 000 queued messages by default, so readings are silently lost while `ingest` is down for longer than that | [04](04-demo-and-operations.md) |

Four findings needed a decision by the owner (AN-07, AN-11, AN-12, AN-27); the answers are at the top of [06](06-action-list.md).

## Status

| Step | State |
|---|---|
| Review of requirements and design | Done (this folder) |
| Owner decisions on AN-07, AN-11, AN-12, AN-27 | Done 2026-10-30 (D32–D35) |
| Apply fixes to requirements/design (new D/DD numbers) | Done 2026-10-30 (D30–D36, DD99–DD113) |
| Week-1 checks (TimescaleDB on Windows, forecast archive coverage, Darts TFT trial, broker test) | Open, at the start of implementation, see [05 §5.3](05-scope-and-plan.md) |
| Second review (AN-32 – AN-40: 1 High, 4 Medium, 4 Low) | Done and applied 2026-10-30 (D37–D38, DD117–DD123), see [07](07-second-review.md) |
| Third review (AN-41 – AN-43: 2 Medium, 1 Low) | Done and applied 2026-10-30 (D39, DD124–DD125), see [08](08-third-review.md) |
| Implementation plan | Written 2026-10-30, see [09](09-implementation-plan.md); working checklists in [implementation/](../implementation/README.md); starts with M0 and the week-1 checks |
| Fourth review (AN-44 – AN-48: 3 Medium, 2 Low, all in the plan) | Done and applied 2026-10-30 (plan reordered, DD126), see [10](10-fourth-review.md) |
