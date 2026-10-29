# M3 Configuration API and onboarding

**Goal:** a site can be created, onboarded and configured over the API; thresholds resolve correctly for every kit; Open-Meteo data flows in.
**Done when:** `start.ps1 -Seed config/example-site.yaml` creates the site, onboarding finishes in a few minutes, and `/config/effective?kit_id=KIT-01` shows the right value and source for every key.

---

- [ ] **M3.1 Config: computed defaults and warnings**
  - Do: onboarding-computed defaults (`rain_intensity_1h_mm` = max(floor, wet-hour p99)) with source `onboarding`; validation warnings (elevation, offsets, kit threshold above site, radius).
  - Check: TST-10: before onboarding → fallback 30 with source `default`; after → computed value with source `onboarding`.
  - Ref: [design/04 §4.2, §4.4](../design/04-configuration.md), DD104 · Needs: M1.2

- [ ] **M3.2 Config API**
  - Do: endpoints of design/02 §2.6.8 (schema, site, kits, recipients, effective, validate, import, export, history), `base_version` → `409 CONFIG_VERSION_CONFLICT`, audit entries with `reason`.
  - Check: API tests; Scenario 8 (two admins on version 7).
  - Ref: [design/02 §2.6.8](../design/02-api.md) · Needs: M3.1

- [ ] **M3.3 Config reload everywhere**
  - Do: `config.changed` NOTIFY on every save; `ingest`, `worker`, `alerts`, `api` reload; startup validation against `defaults.yaml` with a `/system/status` warning.
  - Check: change `rain_mm_per_tip` → the next reading uses it; its clean row records the new version.
  - Ref: [design/01 §1.3.3](../design/01-architecture.md), [design/04 §4.5](../design/04-configuration.md) · Needs: M3.2

- [ ] **M3.4 Worker process and Open-Meteo forecast fetch**
  - Do: `worker` with the scheduler on weather time; hourly fetch at :05 with `past_days=7`, retries, `external_forecast*`; `/external-forecast/latest`; turn on the external QC check (M2.2). Fetch off in demo mode.
  - Check: one fetch stored with 5 variables × ~264 hours; failure keeps the previous fetch and shows its age.
  - Ref: [design/05 §5.8.1](../design/05-data-pipeline.md), [design/07 §7.9](../design/07-forecast-worker.md) · Needs: M0.9, M3.3

- [ ] **M3.5 Onboarding: paced history download**
  - Do: `onboarding.requested` → job; yearly ERA5 requests 10 s apart, `Retry-After` on `429`, yearly commits and resume; tables `onboarding_job`, `onboarding_step`, `history_dataset`, `history_hourly`.
  - Check: integration test with a fake server returning `429` → waits, resumes, completes; restart mid-download resumes at the next year.
  - Ref: [design/05 §5.8.2](../design/05-data-pipeline.md), [design/03 §3.8](../design/03-database-schema.md), DD118 · Needs: M3.4

- [ ] **M3.6 Onboarding: normals, thresholds, events**
  - Do: using `ews.ml` (M1.4): daily normal maximum (1991–2020, 15-day smoothing), percentiles incl. wet-hour rain burst, labels, top-10 events per hazard; progress over `onboarding.progress`; `/onboarding` and `/onboarding/rerun`. Back-tests come in M9.2.
  - Check: on a fixture history: normals for 366 days, 10 events per event type, step states correct.
  - Ref: [design/03 §3.8](../design/03-database-schema.md), [design/02 §2.6.9](../design/02-api.md) · Needs: M3.5, M1.4

- [ ] **M3.7 Normal-offset job**
  - Do: daily at 01:15 site time: per kit with ≥ 28 complete days, ERA5 daily maxima for those days, median of (kit − ERA5) into `normal_offset`.
  - Check: fixture with a kit 1.5 °C warmer → offset ≈ 1.5; with 20 days → no offset.
  - Ref: [design/07 §7.9](../design/07-forecast-worker.md), DD105 · Needs: M3.5

- [ ] **M3.8 First-run wizard**
  - Do: `/setup` wizard: admin → site (form or YAML) → kits → recipients → onboarding progress; dashboard usable during onboarding.
  - Check: **M3 done-when** above, done through the wizard instead of `-Seed`.
  - Ref: [design/10 §10.6](../design/10-ui.md) · Needs: M3.6
