# Site Weather-Hazard Early-Warning System — Design

Design documents for the system specified in [requirements/](../requirements/README.md). The requirements are the source of truth; where a design choice needed a requirement change, the requirements file was updated and the change recorded.

## Documents

| # | File | Contents | Status |
|---|---|---|---|
| 1 | [01-architecture.md](01-architecture.md) | Processes, communication, data flows, failure behaviour, repository structure, local start script | Written |
| 2 | [02-api.md](02-api.md) | REST endpoints, WebSocket events, error format, authentication | Written |
| 3 | [03-database-schema.md](03-database-schema.md) | Normalized schema (BCNF + documented denormalizations), hypertables, continuous aggregates, keys, indexes, compression, retention | Written |
| 4 | [04-configuration.md](04-configuration.md) | Config keys with type, default, allowed levels, validation; resolution algorithm; YAML import/export | Written |
| 5 | [05-data-pipeline.md](05-data-pipeline.md) | Ingestion steps, contract validation, QC, derived features, resampling, Open-Meteo fetch | Written |
| 6 | [06-ml-training.md](06-ml-training.md) | Training locations, data, features, labels, splits, models, calibration and selection, evaluation, versioning | Written |
| 7 | [07-forecast-worker.md](07-forecast-worker.md) | 15-minute run: rolling hours, gaps, inference, exceedance probabilities, storage, timing, other worker jobs | Written |
| 8 | [08-alert-engine.md](08-alert-engine.md) | Alert state machine, hysteresis, timers, squall rule, take-over, combination, suppression, commands, notification decisions | Written |
| 9 | [09-notifications.md](09-notifications.md) | Email kinds, subjects, templates, two audiences, outbox, retries, dedup, superseded emails, threading, channel interface | Written |
| 10 | [10-ui.md](10-ui.md) | Pages and routes, shell, wireframes, components, charts, real-time behaviour, first-run wizard, navigation by role | Written |
| 11 | [11-simulator.md](11-simulator.md) | Demo clock, replay, scenario DSL, faults, multi-kit spatial model, publishing, console and demo script | Written |
| 12 | [12-testing.md](12-testing.md) | Test levels, environment, suites per TST- requirement, scenario tests, decision tests, non-functional checks, traceability | Written |
| 13 | [13-frontend-performance.md](13-frontend-performance.md) | Browser data architecture, one socket per browser, immutable run caching, columnar series, frame-coalesced rendering, code splitting, freshness | Written |
| 14 | [14-operations.md](14-operations.md) | Setup steps and checks, connecting the real kit, logging format, backup and restore | Written |
| — | [decisions.md](decisions.md) | Design decisions DD1–DD126 with reasons | Written |

All design documents are written. Requirement changes made during design: D26 (one site per installation), D27 (alert colour = severity category), D28 (two-stage TFT), D29 (Live alert takes over forecast alert), plus updates in requirements 03, 05, 06, 07, 08 and the real-time scenarios.

The design review in [analysis/](../analysis/README.md) (findings AN-01 – AN-31) and the later reviews (AN-32 – AN-48) led to requirement decisions D30 – D39 and design decisions DD99 – DD126 (and, during implementation, D40 – D41 and DD127 – DD135), applied to these documents.

## Conventions

- The monitored region is always called a **site**; one installation monitors one site (D26).
- Requirement IDs (`DP-`, `AL-`, `WEB-`, …) and decision IDs (`D…` for requirements, `DD…` for design) are cited wherever a design choice implements or depends on them.
- All timestamps are UTC in storage and APIs and shown in the site timezone (NFR-06).
- Examples (JSON, SQL, tables, diagrams) illustrate the design; they are not application code.
