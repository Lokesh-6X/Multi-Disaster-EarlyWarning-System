# Site Weather-Hazard Early-Warning System — Requirements

A location-configurable IoT early-warning system that forecasts **heatwaves**, **heavy rainfall** and **high-speed winds** for a small region called a **site** (e.g. a college, tech park or industrial area). Sensor kits send data to a server, a trained forecasting model predicts the next 72 hours, an alert engine turns forecasts into IMD-style alerts, and a real-time web dashboard shows everything.

## Documents

| # | File | Covers |
|---|---|---|
| 1 | [01-overview.md](01-overview.md) | Goals, scope, non-goals, glossary |
| 2 | [02-hardware.md](02-hardware.md) | Sensor kit interface: expected sensors, kit assumptions, MQTT contract (hardware itself out of scope) |
| 3 | [03-data-pipeline.md](03-data-pipeline.md) | Kit → MQTT → ingestion → database, data quality, multi-kit conflicts |
| 4 | [04-configuration.md](04-configuration.md) | System defaults → site → kit configuration layers |
| 5 | [05-forecasting-model.md](05-forecasting-model.md) | Model choice, training data, training phases, evaluation |
| 6 | [06-hazards-and-alerts.md](06-hazards-and-alerts.md) | Hazard thresholds, Watch/Warning/Live alerts, rolling forecasts |
| 7 | [07-web-application.md](07-web-application.md) | Operator/admin dashboard and panels, users, multi-user handling, email alerts |
| 8 | [08-non-functional-and-testing.md](08-non-functional-and-testing.md) | Performance, security, simulator, testing, tech stack |
| 9 | [09-decisions-and-open-questions.md](09-decisions-and-open-questions.md) | Decisions and future enhancements |
| — | [features.md](features.md) | Full feature list by area, with priorities and requirement IDs |
| — | [real-time-scenario.md](real-time-scenario.md) | Step-by-step real-time examples (squall, heatwave, rain burst, kit offline, faults, operator/admin actions, demo) |

The design that implements these requirements is in [design/](../design/README.md).

## Requirement IDs

Each requirement has an ID so it can be referenced in code, tests and the report:

| Prefix | Area |
|---|---|
| `HW-` | Kit interface assumptions (external hardware) |
| `DP-` | Data pipeline |
| `CFG-` | Configuration |
| `ML-` | Forecasting model |
| `AL-` | Hazards and alerts |
| `WEB-` | Web application |
| `NFR-` | Non-functional |
| `TST-` | Testing |

Priority: **M** = must have, **S** = should have, **C** = could have (if time permits).
