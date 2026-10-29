# M2 Data pipeline complete

**Goal:** every DP- requirement works and is visible on the kit-health page.
**Done when:** every simulator fault overlay produces the expected flag, notice or rejection on the kit-health page, and Scenarios 5 and 6 pass as end-to-end tests on the demo clock.

---

- [ ] **M2.1 QC: range, spike, stuck**
  - Do: per-measurement checks in order; faulty → NULL clean value; spike re-anchoring after 3 readings (stored faulty first, restored later with recomputation); stuck on raw BME280 values (humidity ≥ 99 % exempt).
  - Check: TST-11 QC tables from design/05 §5.4.2–5.4.4.
  - Ref: [design/05 §5.4](../design/05-data-pipeline.md), DD47 · Needs: M1.9

- [ ] **M2.2 QC: cross-sensor, DHT11 fallback, neighbour, external**
  - Do: cross-sensor flag; DHT11 fallback marked suspicious (`temp_sensor = dht11`); neighbour check only with ≥ 3 kits; external check against the latest Open-Meteo value (skipped until M3.4 provides fetches).
  - Check: fallback test; neighbour check with 2 kits does not run, with 3 it flags the outlier.
  - Ref: [design/05 §5.4.5–5.4.8](../design/05-data-pipeline.md), DD44 · Needs: M2.1

- [ ] **M2.3 Derived features and late readings**
  - Do: features of design/05 §5.5.1 from the in-memory 25 h window (rebuilt from the database at start-up), 80 % coverage rule; late readings ≤ 3 h recompute later rows in the same transaction.
  - Check: feature golden tests; a 30-minute-late reading updates later `rain_1h_mm` values.
  - Ref: [design/05 §5.5](../design/05-data-pipeline.md), DD45 · Needs: M2.1

- [ ] **M2.4 Aggregates and series views**
  - Do: `reading_15m`, `reading_1h` continuous aggregates (final column list), refresh policies; views `series_15m`, `series_1h` (end-labelled, coverage → NULL); compression and retention policies **except** in the demo database.
  - Check: 10:00–11:00 labelled 11:00; an hour with 40 readings → NULL; demo database has no retention/compression jobs.
  - Ref: [design/03 §3.6.2, §3.14](../design/03-database-schema.md), [design/05 §5.7](../design/05-data-pipeline.md), DD107 · Needs: M2.3

- [ ] **M2.5 Maintenance notices (first part of `alerts`)**
  - Do: `alerts` process listening to `kit.qc_flag` and `kit.status_changed`; open/close notices of design/05 §5.4.9 (`maintenance_notice`); WebSocket `kit.maintenance_notice` (emails come in M6).
  - Check: stuck sensor → one open notice; value changes → closed.
  - Ref: [design/05 §5.4.9](../design/05-data-pipeline.md) · Needs: M2.2

- [ ] **M2.6 Kit-health API**
  - Do: `/kits/{id}/readings` (rows + `format=columnar`, range limits), `/health`, `/status-history`, `/qc-flags`, `/rejected-messages`, `/system/status`; WebSocket `kit.qc_flag`, `kit.message_rejected`.
  - Check: API tests incl. `RANGE_TOO_LARGE`; columnar = same values as rows.
  - Ref: [design/02 §2.6.4–2.6.5](../design/02-api.md), DD31 · Needs: M2.4, M2.5

- [ ] **M2.7 Demo mode**
  - Do: `start.ps1 -Demo` uses `DEMO_DATABASE_URL`, refuses a non-demo database (and the reverse); `ingest` relays `sim/clock` as `clock.tick`; every process uses weather time from it; "DEMO TIME" in `/system/status`; `-Reset` recreates `ews_demo` and imports `config/demo-site.yaml` (snapshot restore comes in M9).
  - Check: demo run at 60×: readings arrive with demo timestamps; a process started with the wrong database refuses to start.
  - Ref: [design/11 §11.3–11.3.1](../design/11-simulator.md), DD95, DD117 · Needs: M2.4, M1.3

- [ ] **M2.8 Simulator: scenarios and faults**
  - Do: scenario engine (`set`, `ramp`, `step`, `hold`, `noise`) with the built-in files of design/11 §11.4.3 (incl. `single_gust.yaml`); fault overlays of §11.5; interactive console; demo clock publishing.
  - Check: `python -m simulator validate`; each fault produces the expected wire effect (simulator self-tests).
  - Ref: [design/11 §11.4–11.6, §11.8](../design/11-simulator.md) · Needs: M2.7

- [ ] **M2.9 Kit-health page and Scenarios 5, 6**
  - Do: `/kits/:kitId` page of design/10 §10.4.4; end-to-end tests for Scenario 5 (offline, last will and silent variant) and Scenario 6 (faulty sensor).
  - Check: **M2 done-when** above.
  - Ref: [design/10 §10.4.4](../design/10-ui.md), [design/12 §12.4](../design/12-testing.md) · Needs: M2.6, M2.8
