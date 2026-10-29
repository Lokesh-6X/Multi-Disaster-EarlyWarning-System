# ML track (Kaggle, in parallel)

Runs beside the backend milestones. Notebooks live in `ml/notebooks/`, reusable code in `ml/src/`, and shared feature and label code is **imported from `backend/ews/ml/`** (built in M1.4), never copied.

**Done when:** T8 exports model folders that load in the `worker` (M4.1 feature contract check) and the pass marks of [design/06 §6.9](../design/06-ml-training.md) are met (or the report explains which baseline won and why).

Save a checkpoint to `/kaggle/working` every epoch for every TFT run, and run long trainings as committed versions ("Save & Run All") so their output is kept (DD128).

---

- [ ] **T1a Download ERA5 history (24 locations, 1991–2025)**
  - Do: `01_download`: Open-Meteo Archive with `models=era5`, one request per location per year, paced by weighted calls (M0.5 result), resume from existing files, SHA-256 in `ml/data/manifest.json`. Plan several days.
  - Check: 24 × 35 files present and checksummed.
  - Ref: [design/06 §6.2–6.3](../design/06-ml-training.md), DD118 · Needs: M0.5

- [ ] **T1b Download archived forecasts (2022–2025)**
  - Do: Previous Runs (lead-correct) from its real start date per variable, Historical Forecast (stitched) for the earlier part; same pacing.
  - Check: manifest records start dates; any gap noted.
  - Ref: [design/06 §6.3](../design/06-ml-training.md) · Needs: M0.5

- [ ] **T2a Prepare data**
  - Do: `02_prepare`: hourly UTC end-labelled Parquet, units, range checks (drop/replace a location with > 1 % failing hours), global scaler on stage-1 training data, `log1p` rain.
  - Check: one Parquet per location and source; `scaler.json`.
  - Ref: [design/06 §6.4](../design/06-ml-training.md) · Needs: T1a, M1.4

- [ ] **T2b Normals, percentiles, labels (incl. week-1 check 6)**
  - Do: `03_normals_labels` with `ews.ml.labels`: normals, wet-hour p99 (with 20 mm/h floor) and all-hours p99 printed for every location; labels per event and window; positive-window counts.
  - Check: results table filled (also into [m0-foundations.md](m0-foundations.md) week-1 result 6); events with < 30 positives listed (no classifier for them).
  - Ref: [design/06 §6.6](../design/06-ml-training.md), DD104 · Needs: T2a

- [ ] **T3 Baselines**
  - Do: `04_baselines`: persistence, climatology, Open-Meteo (lead-correct), LightGBM quantile, Chronos-Bolt zero-shot; metrics on validation and test.
  - Check: metrics files per baseline; Chronos-Bolt result usable for the report (no live shadow needed).
  - Ref: [design/06 §6.8.1](../design/06-ml-training.md) · Needs: T2b, T1b

- [ ] **T4 TFT-base**
  - Do: `05_tft_base`: hyperparameter search on a subset (6 locations, 4 years), then the chosen configuration on all data, early stopping on validation pinball loss.
  - Check: beats persistence and climatology at all horizons on validation.
  - Ref: [design/06 §6.8.2](../design/06-ml-training.md), DD113 · Needs: T2b

- [ ] **T5 TFT-NWP**
  - Do: `06_tft_nwp`: start from TFT-base, add Open-Meteo future inputs, learning rate 3e-4.
  - Check: not worse than Open-Meteo on validation at any horizon.
  - Ref: [design/06 §6.8.2](../design/06-ml-training.md) · Needs: T4, T1b

- [ ] **T6 Event classifiers**
  - Do: `07_event_classifiers`: LightGBM per event and level with ≥ 30 positive windows, base and NWP variants, `scale_pos_weight`.
  - Check: one model per qualifying event; feature importance saved.
  - Ref: [design/06 §6.8.3](../design/06-ml-training.md) · Needs: T2b

- [ ] **T7 Calibrate and select**
  - Do: `08_calibrate_select`: isotonic (Platt when < 50 positives) on validation; select per event by Brier then PR-AUC; per variable by pinball loss; `selection.json` with fallbacks.
  - Check: calibrated outputs monotonic and in [0, 1]; every event has an active model and a fallback.
  - Ref: [design/06 §6.8.5](../design/06-ml-training.md), DD52 · Needs: T5, T6, T3

- [ ] **T8 Evaluate once and export**
  - Do: `09_evaluate` (test sets once, held-out locations, lead times, back-tests, TFT importance and SHAP, plots) and `10_export` (model folders, `config.json`, `metrics.json`, `importance.json`, `MODEL_CARD.md`, `registry.json` entries).
  - Check: the exported registry loads in `worker` (M4.1) without contract errors; pass marks written into the model card.
  - Ref: [design/06 §6.9, §6.11](../design/06-ml-training.md), DD111 · Needs: T7, M4.1
