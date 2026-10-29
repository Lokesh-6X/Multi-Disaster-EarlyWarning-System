# 8. Non-Functional Requirements, Testing and Tech Stack

## 8.1 Non-functional

| ID | Requirement | Priority |
|---|---|---|
| NFR-01 | A new reading appears on open dashboards within 5 seconds of arrival at the server. | M |
| NFR-02 | A forecast run (all kits, all horizons) completes on CPU in well under the 15-minute refresh interval. | M |
| NFR-03 | Endpoints are rate-limited per user, and login is rate-limited per IP; heavy views (72 h forecast) are cached per forecast run. | S |
| NFR-04 | Clients reconnect automatically after network loss and show data staleness. | M |
| NFR-05 | The system runs on a local machine with locally installed services (no Docker, no containers). A setup guide lists the installs (Python, Node.js, PostgreSQL + TimescaleDB, Mosquitto, Mailpit), and a start script starts all services. **Deployment is out of scope.** | M |
| NFR-06 | All timestamps stored in UTC; displayed in the site timezone. | M |
| NFR-07 | Adding a kit or a site **in India** requires configuration only, no code changes (D37). | M |
| NFR-08 | Secrets (MQTT credentials, SMTP credentials) are kept out of the repository (environment file). | M |

## 8.2 Kit simulator

A simulator that behaves like a real kit (same MQTT topics, message contract and `online`/`offline` status with MQTT last will, [02 §2.4](02-hardware.md)) is required so software and alerts can be built and demoed without waiting for hardware or real weather. Scenario and fault modes run only in demo mode, so simulated hazards never reach real recipients or real data (D39).

| ID | Requirement | Priority |
|---|---|---|
| TST-01 | **Replay mode**: replay historical weather (e.g. a real past heatwave) at configurable speed. | M |
| TST-02 | **Scenario mode**: synthetic events, e.g. pressure drop of 4 hPa followed by a squall (pressure jump, temperature drop, 55 km/h gust); heavy rain burst; multi-day heat build-up. | M |
| TST-03 | **Fault mode**: stuck values, spikes, duplicates, clock skew, malformed messages, dropped connection (broker publishes the last-will `offline`; readings during the outage are lost). | M |
| TST-04 | **Multi-kit mode**: simulate several kits with realistic spatial differences. | S |

## 8.3 Testing

| ID | Test | Priority |
|---|---|---|
| TST-10 | Unit tests for config resolution, validation and override scope. | M |
| TST-11 | Unit tests for QC checks, derived features, unit and pressure conversion, and MQTT contract validation. | M |
| TST-12 | Alert engine tests: create/upgrade/downgrade/cancel, hysteresis, minimum duration, clear-down, suppression and safety override. | M |
| TST-13 | Concurrency tests: simultaneous config saves (version conflict), simultaneous acknowledgements. | S |
| TST-14 | End-to-end: simulator → MQTT → ingestion → forecast → alert → dashboard and email (captured in Mailpit). | M |
| TST-15 | Model back-tests on historical extreme events per site with a lead-time report. | M |
| TST-16 | Permission tests: unauthenticated requests cannot read any data; operators cannot edit config, manage users or read the audit log; deactivated accounts are rejected. | M |

## 8.4 Recommended tech stack

| Part | Choice |
|---|---|
| Messaging | MQTT (Mosquitto, installed locally) |
| Backend | Python, FastAPI (REST + WebSocket) |
| Database | PostgreSQL + TimescaleDB (time series and relational in one DB) |
| Scheduling | A scheduling loop on the system clock inside `worker`, so jobs also follow the demo clock (D41; no Celery: it would need an extra message broker) |
| ML | Darts (TFT and baselines), LightGBM, Chronos-Bolt |
| Frontend | React (Vite), Apache ECharts (forecast ranges), Leaflet (map) |
| Notifications | Email via SMTP; Mailpit for local demo |
| Local run | Locally installed services + start script (no Docker) |

## 8.5 Build order

| Phase | Goal | Done when |
|---|---|---|
| 1 | Skeleton: simulator → MQTT → ingestion → DB → simple live chart | A simulated reading appears on screen within seconds |
| 2 | Connect the externally built kit (when available) | Real readings on the dashboard |
| 3 | Model training (parallel, Kaggle) | Pass marks of [design/06 §6.9](../design/06-ml-training.md) met: TFT-base beats persistence and climatology; TFT-NWP is not worse than Open-Meteo; selected event probabilities beat all baselines on Brier score |
| 4 | Forecast worker | Forecast page shows 72 h charts |
| 5 | Alert engine | Simulated storm triggers correct alerts |
| 6 | Dashboard pages | All "M" pages working |
| 7 | Notifications | Alert emails arrive for create/upgrade/cancel |
| 8 | Config editor, users, audit log | A kit can be added from the UI |
| 9 | Model reports page, map polish | Demo ready |

The detailed plan (milestones M0–M9 and the ML track, with tasks, tests and "done when") is [analysis/09-implementation-plan.md](../analysis/09-implementation-plan.md).

Two contracts come first: the **MQTT message contract** (final, [02 §2.4](02-hardware.md), shared with the hardware builders) and the **API endpoint list** (written: [design/02-api.md](../design/02-api.md), D22).
