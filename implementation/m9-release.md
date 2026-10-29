# M9 Real models, reports, demo and hardening

**Goal:** requirements 08 §8.5 phase 9: demo ready.
**Done when:** Scenario 9 runs from `start.ps1 -Demo -Reset` without errors, `test.ps1 -Slow` and all other suites pass, and the setup guide has been followed once on a clean machine.

---

- [ ] **M9.1 Real models in the backend**
  - Do: copy the exported model folders (ML T8) into `models/`; update `registry.json`; `models reload`; run for a day; compare with the test model set.
  - Check: runs complete with the real models within the NFR-02 budget; `forecast_run_model` records the real versions.
  - Ref: [design/06 §6.11](../design/06-ml-training.md), [design/07 §7.8](../design/07-forecast-worker.md) · Needs: M4.6, ML T8

- [ ] **M9.2 Back-tests during onboarding**
  - Do: onboarding step `backtest`: for the top-10 events, run the models over the days before each event (in small batches between forecast runs) and store first Watch/Warning times; step `report`.
  - Check: TST-15 back-test job on a fixture history; lead times computed exactly on a synthetic series.
  - Ref: [design/03 §3.8](../design/03-database-schema.md), [design/07 §7.9](../design/07-forecast-worker.md) · Needs: M9.1, M3.6

- [ ] **M9.3 Model-reports page**
  - Do: `/reports/*` endpoints; page with accuracy by horizon, hazard skill (with "not enough events to train"), back-tests, explainability, live verification (nightly `verification_daily` job).
  - Check: page loads with the real metrics; live verification fills after a day.
  - Ref: [design/02 §2.6.12](../design/02-api.md), [design/10 §10.4.7](../design/10-ui.md) · Needs: M9.2

- [ ] **M9.4 Demo snapshot**
  - Do: `scripts/build-demo-snapshot.ps1` (import demo site, onboarding, ≥ 7 simulated days of replay, a few runs, `pg_dump` + `demo-snapshot.json`); `-Demo -Reset` restores it, runs migrations, warns when old; `simulator/demo.yaml` for Scenario 9.
  - Check: DD108/DD116 test: after `-Reset` the first run completes with all kits `ok` and the simulator continues from `sim_time`.
  - Ref: [design/11 §11.3.1, §11.8](../design/11-simulator.md) · Needs: M8.6, M9.1

- [ ] **M9.5 Alert-volume dry run**
  - Do: batch harness in `backend/tests/harness/` (ingest functions + alert engine + fake clock + replay generator as a library); live path over a full real year, forecast path over one wet and one hot month; table of alerts and emails per week, hazard and level. **Ask the owner for the target numbers**, then tune defaults in `defaults.yaml` if needed.
  - Check: counts within the agreed targets; table saved for the report.
  - Ref: [design/12 §12.2, §12.6](../design/12-testing.md), DD112, DD126 · Needs: M5.12

- [ ] **M9.6 Non-functional checks**
  - Do: the checks of design/12 §12.6 (NFR-01 latency p95 ≤ 1 s, NFR-02, NFR-03, NFR-04, NFR-06 around midnight and 03:00 UTC, NFR-07, NFR-08 secret scan).
  - Check: every row passes; results saved.
  - Ref: [design/12 §12.6](../design/12-testing.md) · Needs: M9.4

- [ ] **M9.7 Backup and restore**
  - Do: `backup.ps1` (+ `-Install` task), `restore.ps1` with pre/post-restore and confirmations; one practice restore into `ews_restore_check`.
  - Check: restored database starts and shows the same alerts and readings.
  - Ref: [design/14 §14.3](../design/14-operations.md), DD97, DD98 · Needs: M0.12

- [ ] **M9.8 Clean-machine install**
  - Do: follow `docs/setup-guide.md` on a machine (or fresh Windows user) without the tools; fix the guide where it is wrong.
  - Check: `check-setup.ps1` all OK and `start.ps1 -Seed …` works first time.
  - Ref: [design/14 §14.1](../design/14-operations.md), NFR-05 · Needs: M9.6

- [ ] **M9.9 Report material (and the map if time allows)**
  - Do: architecture and data-flow figures from design/01; results vs pass marks (DD111); known limitations (design/06 §6.14, MQTT without TLS, one-day heatwave, rain-burst forecasts, India-only scope); optional map page (could).
  - Check: every requirement group in design/12 §12.8 has evidence (test or result) listed.
  - Ref: [design/06 §6.9, §6.14](../design/06-ml-training.md), [design/12 §12.8](../design/12-testing.md) · Needs: M9.3, M9.5
