# M4 Forecast worker (with test models)

**Goal:** requirements 08 §8.5 phase 4: the forecast page shows 72 h charts, using the tiny test model set until the ML track delivers.
**Done when:** a run every 15 minutes appears on the forecast page with P10–P90 bands and a probability table, and 100 runs with 5 kits take ≤ 60 s each (p95).

---

- [ ] **M4.1 Model registry**
  - Do: read `models/registry.json`; check SHA-256 and the feature contract against `ews.ml.features`; active and fallback model per variable and event; mirror into `model_version`; `python -m ews.worker models reload`.
  - Check: a model with a wrong feature list is refused, the fallback is used, `/system/status` shows a warning.
  - Ref: [design/06 §6.11](../design/06-ml-training.md), [design/07 §7.6](../design/07-forecast-worker.md) · Needs: M1.4

- [ ] **M4.2 Tiny test model set**
  - Do: `models/test/` with a very small TFT and classifiers trained in minutes on fixture data, the real feature contract and a registry.
  - Check: loads through M4.1; used by every test and by default until T8.
  - Ref: [design/12 §12.2](../design/12-testing.md) · Needs: M4.1

- [ ] **M4.3 Inference child process**
  - Do: persistent child process loaded once, inputs over a pipe, hard timeout `forecast_timeout_s` in machine time, restart on crash.
  - Check: a model that sleeps 400 s → run `failed`, child restarted, next slot works.
  - Ref: [design/07 §7.2](../design/07-forecast-worker.md), DD60, DD117 · Needs: M4.2

- [ ] **M4.4 Rolling hours and gaps**
  - Do: 168 rolling hours per kit from `series_15m`; Open-Meteo interpolated to the rolling hours; gaps ≤ 3 h interpolated; longer gaps / new kits filled with bias-corrected pseudo-observations (`degraded`); no data 24 h or nothing to fill with → `skipped` with a reason.
  - Check: TST-11 rolling-hour tests; DD57 tests (4 h outage → degraded; 25 h → skipped).
  - Ref: [design/07 §7.3–7.4](../design/07-forecast-worker.md) · Needs: M4.3, M3.4

- [ ] **M4.5 Probabilities**
  - Do: per event, level and window; probabilities from quantiles (piecewise CDF with tails) and from classifiers (DD59 rules, not for D0, not for heatwave with a normal offset); **D0 windows** with measured rain and highest 30-minute median temperature; calibration maps.
  - Check: D0 tests (80 mm measured → P = 1; one hot minute does not count); local-risk threshold → `tft` source.
  - Ref: [design/07 §7.5](../design/07-forecast-worker.md), [design/06 §6.8.4](../design/06-ml-training.md), DD99, DD115, DD121, DD124 · Needs: M4.4

- [ ] **M4.6 Run storage and schedule**
  - Do: forecast tables (integer hypertables, or plain tables first); `COPY` in one transaction; run at issue time + 120 s, one at a time, missed runs skipped; `forecast_run_kit` with reasons; `forecast.run_completed`.
  - Check: a run stores ≈ 360 values + ≈ 67 probabilities per kit; a slot missed by more than 5 min is skipped and logged.
  - Ref: [design/07 §7.1, §7.7](../design/07-forecast-worker.md), [design/03 §3.7](../design/03-database-schema.md) · Needs: M4.5

- [ ] **M4.7 Forecast API**
  - Do: `/forecast/latest`, `/forecast/runs`, `/forecast/runs/{id}` and `/probabilities` with ETag and immutable caching; `latest_run_id` in `/site` and `/live`; WebSocket `forecast.run_completed`.
  - Check: second request for a run → `304`; response shapes as in design/02.
  - Ref: [design/02 §2.6.6](../design/02-api.md), DD30 · Needs: M4.6

- [ ] **M4.8 Forecast page**
  - Do: forecast charts (P10–P90 band, P50, observed overlay, Open-Meteo line, thresholds), probability table outlined at the cut-offs, previous/next run, degraded/skipped banners.
  - Check: **M4 done-when** above; NFR-02 timing check.
  - Ref: [design/10 §10.4.2](../design/10-ui.md), DD81 · Needs: M4.7
