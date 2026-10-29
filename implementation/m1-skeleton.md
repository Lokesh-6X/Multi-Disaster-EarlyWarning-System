# M1 Skeleton (first demo)

**Goal:** requirements 08 §8.5 phase 1: a simulated reading appears on the dashboard within seconds.
**Done when:** `start.ps1 -Seed config/example-site.yaml -Simulator normal` shows live readings for KIT-01 on `http://localhost:8000`, and killing the simulator shows the kit **Offline** within seconds.

---

- [ ] **M1.1 Config resolver**
  - Do: `ews.common.config.resolve(key, kit)` with the order kit → site → onboarding → region default → default and its `source`; cache, reload hook.
  - Check: TST-10 resolution tests, including a `hypothesis` property test (most specific allowed level wins).
  - Ref: [design/04 §4.2](../design/04-configuration.md) · Needs: M0.11

- [ ] **M1.2 Config validator and versioned saves**
  - Do: the 7 validation steps with all problems reported together; cross-key rules checked on the effective values of **every** affected kit; save = insert version *n + 1* (unique key gives the conflict).
  - Check: TST-10 cases: `timezone` on a kit → `OVERRIDE_NOT_ALLOWED`; a site save that breaks a kit → `THRESHOLD_ORDER`; two saves on the same base version → one conflict.
  - Ref: [design/04 §4.4](../design/04-configuration.md), [design/03 §3.5.2](../design/03-database-schema.md) · Needs: M1.1

- [ ] **M1.3 YAML import and `-Seed`**
  - Do: import of site, kits and recipients (atomic, same validator, dry run); `config/example-site.yaml` (ABC College, KIT-01) and `config/demo-site.yaml` (`site_id: demo`); `start.ps1 -Seed <file>` imports when no site exists.
  - Check: valid file → site + kit + recipients stored; one invalid kit → nothing stored.
  - Ref: [design/04 §4.6](../design/04-configuration.md) · Needs: M1.2

- [ ] **M1.4 Shared feature and label code (`ews.ml`)**
  - Do: `ews.ml.features` (heat index NOAA, end-labelled hourly series, rolling statistics) and `ews.ml.labels` (gust, rain 24 h per IMD rain day, rain burst with wet-hour p99 and 20 mm/h floor, heatwave with normal and region rules), `normals` (15-day smoothing). Pure functions, no database.
  - Check: golden-value tests (heat index table within 0.3 °C; labels on small hand-made series). The ML track imports this module from T2a on.
  - Ref: [design/06 §6.4–6.6](../design/06-ml-training.md), [design/05 §5.5](../design/05-data-pipeline.md) · Needs: M0.7

- [ ] **M1.5 Users and preferences tables**
  - Do: migration for `user_session`, `user_token`, `user_alert_preference` (+ hazard, type), `audit_entry`, `audit_change`; default preferences created with every user.
  - Check: creating a user creates its default preference rows.
  - Ref: [design/03 §3.11](../design/03-database-schema.md) · Needs: M0.11

- [ ] **M1.6 Reading tables**
  - Do: migration for `kit_firmware`, `reading_raw`, `reading_clean` (`kit_config_version_id`, `site_config_version_id`), `reading_derived`, `reading_qc_flag`, `kit_status_event`, `rejected_message`; hypertables; `kit_outage` view.
  - Check: `alembic upgrade head` then `downgrade -1` and `upgrade` again work on `ews_test`.
  - Ref: [design/03 §3.6](../design/03-database-schema.md), DD123 · Needs: M0.11

- [ ] **M1.7 Simulator: one kit, normal mode**
  - Do: `simulator/kit.py` (MQTT, last will `offline` retained, `online` on connect, seq, uptime, rssi); `contract.schema.json`; `normal` and `replay` sources at 1×; every message checked against the schema; the D39 guard (scenarios and faults only with `clock.mode: demo`).
  - Check: `python -m simulator run --replay …` publishes valid messages; `--scenario squall` with real clock is refused.
  - Ref: [design/11 §11.1–11.2, §11.7](../design/11-simulator.md), DD125 · Needs: M0.4

- [ ] **M1.8 Ingest: topic, contract, duplicates**
  - Do: subscribe QoS 1 with persistent session; topic checks; strict payload validation (exactly the contract fields, types, ranges, 4 KB, timestamp window); duplicates (identical dropped, conflicting rejected); `rejected_message` + `message.rejected`.
  - Check: TST-11 contract cases, one test per `reject_reason`.
  - Ref: [design/05 §5.2](../design/05-data-pipeline.md), DD42, DD43 · Needs: M1.6, M1.3

- [ ] **M1.9 Ingest: calibrate, store, kit status**
  - Do: calibration and conversion (tips → mm, sea-level pressure); one transaction raw + clean (+ firmware change); kit status from the status topic, `reading_resumed`, 30 s no-data timer; `site.locked_at`; NOTIFY `reading.ingested`, `kit.status_changed`.
  - Check: golden values for sea-level pressure at three elevations; integration test with Mosquitto: publish → rows stored → NOTIFY received; kill the publisher → `offline` event at once.
  - Ref: [design/05 §5.3, §5.6](../design/05-data-pipeline.md) · Needs: M1.8

- [ ] **M1.10 API: setup, login, live**
  - Do: FastAPI app at `/api/v1`; problem+json errors; `/setup/status`, `/setup`, `/auth/login`, `/auth/logout`, `/auth/me` (Argon2id, cookie session, CSRF); `GET /site`, `GET /live`, `GET /kits`; serve the built frontend.
  - Check: API tests: setup works once, then `409`; `/live` without a session → `401`; with a session → the latest reading.
  - Ref: [design/02 §2.2–2.3, §2.6.1, §2.6.4](../design/02-api.md) · Needs: M1.5, M1.9

- [ ] **M1.11 API: WebSocket**
  - Do: `/api/v1/ws`: cookie + `Origin` (`APP_BASE_URL`, `DEV_ORIGINS`) check; `hello`, `ping` every 20 s (machine time); forward `reading.new` and `kit.status` from NOTIFY.
  - Check: API test: handshake without a session refused; a published reading arrives as `reading.new`.
  - Ref: [design/02 §2.7](../design/02-api.md), DD122 · Needs: M1.10

- [ ] **M1.12 Frontend: shell, login, live tiles**
  - Do: React Router with login and dashboard routes; shell with clock and connection pill; live tiles for each kit from `/live` + `reading.new`; freshness label on server time; reconnect with backoff and reload.
  - Check: **M1 done-when** above; Scenario 1 timing: publish → tile updated ≤ 5 s (aim ≈ 1 s).
  - Ref: [design/10 §10.3, §10.4.1](../design/10-ui.md), [design/13 §13.3.8](../design/13-frontend-performance.md) · Needs: M1.11
