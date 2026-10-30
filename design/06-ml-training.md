# 6. ML Training

How the forecasting models are built offline: training locations, data download, preparation, features, labels, time splits, the TFT and its baselines, event classifiers and calibration, model selection per hazard, evaluation, fine-tuning per site, and how model files are versioned and handed to the `worker`. Requirements: [05](../requirements/05-forecasting-model.md) (ML-01 – ML-10), D7 – D9, D20, D28. Runtime use of the models: [07](07-forecast-worker.md).

Decisions referenced: DD48–DD55 in [decisions.md](decisions.md).

## 6.1 Pipeline

```
 1 download        ERA5 history 1991–2025 (24 locations)  +  archived Open-Meteo forecasts 2022–2025
 2 prepare         hourly, UTC, end-labelled, units, gaps → Parquet
 3 normals+labels  per-location normals (1991–2020), percentiles, hazard event labels
 4 baselines       persistence, climatology, Open-Meteo, LightGBM quantile, Chronos-Bolt
 5 TFT-base        stage 1: calendar-only future inputs        (train 2008–19, val 2020–21, test 2022–25)
 6 TFT-NWP         stage 2: + Open-Meteo forecast inputs       (train 2022–23, val 2024,    test 2025)
 7 event models    LightGBM classifiers per event (base + NWP variants)
 8 calibrate       isotonic calibration of every probability source on validation
 9 select          per variable and per event, on validation only
10 evaluate        test sets once; held-out locations; back-tests; explainability
11 export          model folders + registry.json → copied to models/ → worker loads them
```

| Item | Choice |
|---|---|
| Environment | Kaggle Notebooks GPU for the TFT (requirements 05 §5.5, D40); LightGBM, Chronos-Bolt and evaluation also run on a CPU laptop |
| Library (DD48) | **Darts**: `TFTModel` (multivariate target, static / past / future covariates, quantile regression, `TFTExplainer`), `LightGBMModel`, `NaiveSeasonal`/persistence, back-testing helpers. `lightgbm` directly for the event classifiers; `chronos-forecasting` for Chronos-Bolt |
| Code | Notebooks in `ml/notebooks/` call functions in `ml/src/`; shared feature and label code is imported from `backend/ews/ml/` so training and live inference compute identical inputs ([01 §1.6](01-architecture.md), DD10) |
| Reproducibility | Fixed seeds; pinned versions in `ml/requirements.txt` (same Darts / PyTorch / LightGBM minor versions as the backend); every dataset file listed with its SHA-256 in `ml/data/manifest.json` |

## 6.2 Training locations (DD49)

24 locations, 8 per region type, chosen to cover the three hazards' main regimes. **3 are held out** (never used for training) to test that the global model works at an unseen location without retraining (ML-05). Coordinates are approximate city centres; the ERA5 grid cell (0.25°, ≈ 28 km) nearest to them is used, and the elevation is taken from the Open-Meteo response.

| # | Location | Region | Lat | Lon | ≈ Elev. (m) | Why |
|---|---|---|---|---|---|---|
| 1 | Delhi | plains | 28.61 | 77.21 | 216 | Severe pre-monsoon heatwaves, dust-storm squalls |
| 2 | Jaipur | plains | 26.91 | 75.79 | 431 | Arid heat, dry squalls |
| 3 | Lucknow | plains | 26.85 | 80.95 | 123 | Indo-Gangetic heat and humid heat stress |
| 4 | Patna | plains | 25.59 | 85.14 | 53 | Humid heat, monsoon rain, nor'westers |
| 5 | Nagpur | plains | 21.15 | 79.09 | 310 | Central India extreme heat |
| 6 | Ahmedabad | plains | 23.02 | 72.57 | 53 | Western heat, heavy monsoon spells |
| 7 | Hyderabad | plains | 17.39 | 78.49 | 505 | Deccan plateau, urban flash floods |
| 8 | Raipur *(held out)* | plains | 21.25 | 81.63 | 298 | Unseen plains test |
| 9 | Chennai | coastal | 13.08 | 80.27 | 6 | NE monsoon rain, coastal heat, cyclone-edge winds |
| 10 | Mumbai | coastal | 19.08 | 72.88 | 14 | Extreme monsoon rainfall |
| 11 | Visakhapatnam | coastal | 17.69 | 83.22 | 45 | Bay of Bengal cyclone-coast winds |
| 12 | Puri | coastal | 19.81 | 85.83 | 10 | Odisha cyclone coast, coastal heatwaves |
| 13 | Kochi | coastal | 9.93 | 76.27 | 1 | SW monsoon onset rain |
| 14 | Mangaluru | coastal | 12.91 | 74.86 | 22 | Heavy Western-Ghats coastal rain |
| 15 | Dwarka | coastal | 22.24 | 68.97 | 10 | Arid coast, Arabian Sea winds |
| 16 | Machilipatnam *(held out)* | coastal | 16.19 | 81.14 | 3 | Unseen coastal test (heat + cyclone coast) |
| 17 | Shimla | hilly | 31.10 | 77.17 | 2200 | Western Himalaya |
| 18 | Dehradun | hilly | 30.32 | 78.03 | 640 | Cloudbursts, foothill heat |
| 19 | Darjeeling | hilly | 27.04 | 88.26 | 2045 | Eastern Himalaya monsoon |
| 20 | Gangtok | hilly | 27.33 | 88.61 | 1650 | Eastern Himalaya, landslide-season rain |
| 21 | Shillong | hilly | 25.58 | 91.89 | 1500 | NE hills, pre-monsoon storms |
| 22 | Sohra (Cherrapunji) | hilly | 25.30 | 91.70 | 1300 | World-class extreme rainfall |
| 23 | Ooty | hilly | 11.41 | 76.70 | 2240 | Nilgiris, southern hills |
| 24 | Mahabaleshwar *(held out)* | hilly | 17.92 | 73.66 | 1350 | Unseen hilly test (extreme orographic rain) |

The list may be edited during data preparation if a location's data fails the checks in §6.4; any change is recorded in `ml/data/manifest.json` and the model card.

## 6.3 Data download

| Data | Source | Period | Used for |
|---|---|---|---|
| Hourly history | Open-Meteo Archive API, `models=era5` (consistent ERA5 everywhere; ERA5-Land has no gusts) | 1991-01-01 – 2025-12-31 | Normals (1991–2020), labels, training inputs and targets (2008+) |
| Archived forecasts, lead-correct | Open-Meteo Previous Runs API (`…_previous_day1` … `day3` variables) | from its first available date (about 2024; confirmed in a week-1 check and recorded per variable in `ml/data/manifest.json`; if coverage is short, stage-2 validation and test move to the covered period, DD113) – 2025-12-31 | TFT-NWP future inputs and the Open-Meteo baseline with the correct lead time |
| Archived forecasts, stitched | Open-Meteo Historical Forecast API (`models=best_match`, same as the live fetch, [05 §5.8.1](05-data-pipeline.md)) | 2022-01-01 – until Previous Runs data starts | TFT-NWP training inputs where lead-correct data does not exist |

Variables (all hourly, `timezone=GMT`, `wind_speed_unit=kmh`): `temperature_2m`, `relative_humidity_2m`, `wind_speed_10m`, `wind_gusts_10m`, `precipitation`, `pressure_msl`.

- One request per location per year (history) or per location per quarter (forecasts); about 1 000 requests in total. The free API **weights** requests (a year of six variables counts as roughly 25 or more calls), so this is about 20 000+ weighted calls: the download script paces requests, honours `Retry-After` on `429`, resumes from the files already written and is planned over **several days** (DD118). Each file is written once and checksummed.
- **Stitched vs lead-correct (honest limitation):** the Historical Forecast API joins the first hours of successive model runs, so it is more accurate than a real 48 h-ahead forecast. It is used only for TFT-NWP *training* (2022–2023 and any period before Previous Runs data starts). Validation (2024) and test (2025) use lead-correct inputs wherever they exist, so the reported scores are not flattered. The report states this.
- Onboarding uses the same history source (`models=era5`) and period start (`normals_start_year`), so normals at a site match the training data ([05 §5.8.2](05-data-pipeline.md)).

## 6.4 Preparation

| Step | Rule |
|---|---|
| Time | UTC, hourly, **end-labelled** like the kit series (DD46) |
| Units | °C, %, hPa, km/h, mm — same names as the kit series (`temp_c`, `rh_pct`, `pressure_msl_hpa`, `wind_avg_kmh`, `wind_gust_kmh`, `rain_mm`) |
| Gaps | ERA5 is complete; any missing hour is left missing (never filled with 0). Forecast archives: a missing issue is skipped as a training sample |
| Checks | Physical ranges as in QC ([05 §5.4.2](05-data-pipeline.md)); a location with > 1 % failing hours is dropped and replaced |
| Storage | Parquet per location and source in `ml/data/processed/`, uploaded as a private Kaggle Dataset for training (DD128) |
| Transforms (DD50) | **Global** standardisation per variable (fitted on stage-1 training data of all training locations, never per location, so a new site needs no fitting); `rain_mm` as `log1p` before standardisation |

## 6.5 Features

Features are built by `ews.ml.features` from **hourly** series, in training (ERA5) and live (kit `series_1h`, [05 §5.7](05-data-pipeline.md)) alike. The per-minute features of `reading_derived` are for live alerts and the dashboard, not for the model.

| Kind (Darts term) | Features |
|---|---|
| Targets (5 components) | `temp_c`, `rh_pct`, `wind_gust_kmh`, `rain_mm`, `pressure_msl_hpa` |
| Past covariates | `wind_avg_kmh`; pressure tendency 1 h / 3 h; rain 3 h / 24 h; gust trend 3 h; temperature change 3 h; heat index |
| Future covariates, stage 1 | Hour of day and day of year (sin/cos), month; **normal max temperature** for the target day (from the location's normals) |
| Future covariates, stage 2 | Stage 1 + Open-Meteo forecast of the five targets for each future hour (and `wind_speed_10m`) |
| Static covariates | `lat`, `lon`, `elevation_m`, `region_type` (one-hot), wet-hour p99 hourly rain, mean annual rain; `exposure` and `mount_height_m` (constant "reanalysis"/10 m in global training; informative only after fine-tuning with kit data, §6.10) |

| Window | Value |
|---|---|
| Encoder (input) length | 168 h (7 days) |
| Decoder (output) length | 72 h |
| Training sample stride | Every 3 h (an issue time every 3 h per location) |

## 6.6 Labels and probability windows

Labels come from applying the hazard thresholds ([06 §6.1](../requirements/06-hazards-and-alerts.md), [04 §4.3.6](04-configuration.md) defaults) to the hourly history; no disaster database is needed (requirements 05 §5.5). The **windows** below are part of each model's definition (stored in its `config.json`), because classifiers are trained for them; the `worker` and alert engine use the same windows ([07](07-forecast-worker.md), [08](08-alert-engine.md)).

| Event (`hazard_event`) | Label = 1 when, in the window | Windows from issue time *t₀* |
|---|---|---|
| `gust` yellow / orange / red | max `wind_gust_kmh` ≥ 39 / 50 / 62 | 3 h blocks over 0–24 h, 6 h blocks over 24–72 h |
| `rain_intensity` | max hourly rain ≥ the location's rain-burst threshold: max(20 mm/h, wet-hour p99) (D32, DD104) | 3 h blocks over 0–6 h (horizon 1–6 h, requirements 06) |
| `rain_24h` yellow / orange / red | 24 h rain ≥ 64.5 / 115.6 / 204.5 mm | Rain days ending 03:00 UTC (08:30 IST, the IMD rain day), days D0–D2 |
| `heatwave` orange (heatwave) / red (severe heatwave) | IMD rule for the location's region type on the daily maximum (local day) vs its normal | Days D1–D3 for training. At run time also **D0** (rest of today), from the TFT plus the measured maximum (D30, DD99, [07 §7.5](07-forecast-worker.md)) |
| Squall | — (a rule-based trigger of live `gust` alerts, D8, [08 §8.6.2](08-alert-engine.md)) | — |

- **Known bias:** ERA5 gusts and hourly rain are smoothed, so red gust and intensity events are rare in the labels. An event with fewer than 30 positive windows in its training period gets no classifier; it uses the TFT-derived probability (§6.8) and the model card says so.
- The same labelling code produces the **back-test events** during site onboarding ([03 §3.8](03-database-schema.md)).

**Rules of the shared code (DD133).** `ews.ml.features`, `ews.ml.labels` and `ews.ml.normals` are pure functions on pandas series with a UTC, end-labelled hourly index. They need nothing beyond numpy and pandas, so the Kaggle notebooks can import them without the backend's other packages.

| Topic | Rule |
|---|---|
| Thresholds | Passed as arguments; the defaults are those of `config/defaults.yaml` (a test keeps them equal). A site's own values come from the resolver ([04 §4.2](04-configuration.md)) |
| Window membership | A window (t₀ + a, t₀ + b] takes the hours whose **end** lies inside it; a calendar window likewise (rain day ending 03:00 UTC, local day of the site's time zone) |
| Missing hours | A label is **1** if any present value meets the threshold (a partial sum for 24 h rain); **0** only if at least 80 % of the window's hours are present (`qc_coverage_min_pct`); otherwise unknown (NaN). Rolling features follow 05 §5.5.1: NaN below 80 % coverage, sums over the present hours. A daily maximum needs 80 % of the day's hours |
| Day offsets | Rain `D0` = the rain day that contains t₀ (ends at the first 03:00 UTC **after** t₀), D1, D2 the next. Heat `D1`–`D3` = the local days after t₀'s local day; `D0` = t₀'s local day |
| Normals | Mean daily maximum per calendar day over `normals_start_year`–`normals_end_year`, on a leap-year calendar (day 1–366; 29 February = day 60, its own value), then a centred `normals_smoothing_days` (15) moving average that wraps from 31 December to 1 January. A date looks up its leap-year day number |
| Calendar features | Hour of day (fractional for rolling hours, [07 §7.3](07-forecast-worker.md)) and day of year in the **site's local time**, as sin/cos; month 1–12 |
| Percentiles | `numpy` linear interpolation; rain burst = max(`rain_intensity_floor_mm`, `rain_intensity_percentile` of hours ≥ `rain_wet_hour_min_mm`) |

## 6.7 Splits (ML-02, D28)

| Split | Stage 1 (TFT-base, base classifiers, LightGBM, persistence, climatology, Chronos-Bolt) | Stage 2 (TFT-NWP, NWP classifiers, Open-Meteo baseline) |
|---|---|---|
| Train | 2008–2019 | 2022–2023 (stage-2 models start from the stage-1 weights) |
| Validation | 2020–2021 | 2024 |
| Test | 2022–2025 | 2025 |
| Locations | 21 training locations; the 3 held-out locations appear only in the test reports | same |

- Validation is used for early stopping, hyperparameters, calibration and model selection. **Test is used once**, after everything is frozen.
- A 7-day gap separates splits (the encoder length) so no input window crosses a boundary.
- **All models are compared on 2025** (the only year where every model, including the Open-Meteo baseline, can be scored with lead-correct inputs); stage-1 models are additionally reported on 2022–2025 (ML-03).

## 6.8 Models

### 6.8.1 Baselines (ML-03, D9)

| Baseline | Continuous forecast | Event probability |
|---|---|---|
| Persistence | Last observed value for every lead time | 1 if the event condition holds now, else 0 |
| Climatology *(extra reference)* | Mean for the hour of day and day of year | Base rate of the event for that day of year and window |
| Open-Meteo | Forecast unchanged, lead-correct (2025) | 1 if the forecast crosses the threshold, else 0 (deterministic) |
| LightGBM quantile | Darts `LightGBMModel`, lags 1–168 h + covariates, quantiles P10/P50/P90, one model per report horizon (1, 3, 6, 24, 72 h) | Not applicable |
| Chronos-Bolt (zero-shot) | `chronos-bolt-small`, univariate per target, 512 h context, its native quantiles; no training | From its quantiles, as for the TFT |

### 6.8.2 TFT-base and TFT-NWP

| Setting | Value (tuned on validation within small ranges) |
|---|---|
| Model | Darts `TFTModel`, multivariate target (5 components) |
| Likelihood (DD51) | `QuantileRegression` with **9 quantiles**: 0.02, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.98 |
| Size | hidden 64, 1 LSTM layer, 4 attention heads, dropout 0.1 (search: hidden 32/64/128, dropout 0.1/0.2) |
| Optimisation | Adam, learning rate 1e-3 with reduce-on-plateau, batch 256, up to 30 epochs, early stopping (patience 5) on validation pinball loss |
| Stage 2 | Initialised from TFT-base; future covariates extended with Open-Meteo inputs; learning rate 3e-4, up to 15 epochs |
| Output used | All 9 quantiles at inference; **P10/P50/P90 stored** for charts ([03 §3.7.2](03-database-schema.md)); the full set is used to derive probabilities |
| Size on disk / CPU inference | ≈ 5–10 MB; well under 10 s per kit per run on a laptop CPU (ML-08, budget in [07](07-forecast-worker.md)) |
| Resumable training (DD113, DD128) | Checkpoint **every epoch** to `/kaggle/working` (Darts `save_checkpoints`, resume with `load_from_checkpoint`), because Kaggle sessions end (time limit, weekly GPU quota). Long runs are committed versions ("Save & Run All"), so they continue in the background and keep their output; a run is resumed by attaching the previous version's output as input. The hyperparameter search runs on a **subset** (6 locations, 4 years); only the chosen configuration is trained on all data. Before the first long run, a CPU trial (2 locations, 1 epoch) goes end to end through export and `worker` loading |

### 6.8.3 Event classifiers (D8, ML-04)

| Setting | Value |
|---|---|
| Model | `lightgbm` binary classifier, **one per event and level** (e.g. `gust_orange`), lead time of the window as a feature (one model for all windows of that event) |
| Features | Last 24 h of hourly targets and past covariates (lags and rolling stats), static covariates, calendar, normal max temperature; NWP variant adds the Open-Meteo forecast summarised over the window (max, mean, sum) |
| Variants | `base` (stage-1 splits) and `nwp` (stage-2 splits) |
| Imbalance | `scale_pos_weight` = negatives / positives in the training set (ML-04) |
| Heavy rain | `rain_24h` classifiers are the "LightGBM heavy-rain classifier" required by D8. At run time they serve rain days D1–D2; the current rain day D0 is computed from measured rain + the TFT forecast for its remaining hours (DD115) |

### 6.8.4 Probabilities from quantiles

For each future hour, the 9 quantiles define a piecewise-linear CDF; beyond P02 and P98 an exponential tail is fitted to the last two quantiles. From it:

| Event | Raw score from TFT (or Chronos-Bolt) |
|---|---|
| Gust in a window | max over the window's hours of P(gust ≥ threshold) |
| Rain intensity | max over the window's hours of P(rain ≥ rain-burst threshold) |
| 24 h rain | P(sum ≥ threshold), with quantiles of the sum approximated by summing hourly quantiles of the same level. For the current rain day D0, the rain **already measured** since 03:00 UTC is added to the sum; if it already meets the threshold, P = 1 (D30, DD99) |
| Heatwave | P(daily max ≥ normal + departure and ≥ minimum), using max over the day's hours. For today (D0), the daily max is max(measured so far as the highest 30-minute median, the Live measure, DD124; forecast for the remaining hours); if the measured maximum already meets the rule, P = 1 (D30, DD99) |

These raw scores are not exact probabilities (hours are not independent), so every source is **calibrated** (§6.8.5).

### 6.8.5 Calibration and selection per event (DD52)

```
for each event and level (gust_yellow … heatwave_red):
    candidates = { TFT-base, TFT-NWP, LGBM-base, LGBM-NWP }       (those that exist)
    fit isotonic calibration of each candidate on its validation split
        (Platt scaling when the validation split has < 50 positives)
    pick the candidate with the lowest Brier score on validation;
        ties (< 2 % apart) → higher PR-AUC
for each continuous variable:
    pick TFT-base or TFT-NWP by validation pinball loss (fallback: TFT-base when no forecast input)
write the result to models/<version>/selection.json
```

This implements "the final model per hazard is chosen from test results; if LightGBM wins for a hazard, it is used for that hazard" ([05 §5.1](../requirements/05-forecasting-model.md)), with the choice made on validation and only *reported* on test, so the test result is not used to tune anything. Each candidate keeps a **fallback**: an NWP model falls back to its base variant when no recent Open-Meteo fetch exists ([07](07-forecast-worker.md)).

## 6.9 Evaluation (05 §5.7, TST-15)

| Output | Metrics | Compared with |
|---|---|---|
| Continuous (P50) | MAE, RMSE per variable **per horizon** (1, 3, 6, 24, 72 h) | Persistence, climatology, Open-Meteo, LightGBM, Chronos-Bolt |
| Quantiles | Pinball loss; coverage of P10–P90 (target ≈ 80 %) and P02–P98 (≈ 96 %) | Chronos-Bolt, LightGBM |
| Event probabilities | Brier score, reliability diagram, PR-AUC; recall, precision, false-alarm rate, F1 at the Watch (0.30) and Warning (0.60) cut-offs | All baselines |
| Lead time | For each test event onset: hours between the first issue time with probability ≥ Watch cut-off (and ≥ Warning cut-off) for a window containing the onset, and the onset | Open-Meteo, persistence |
| Generalisation (ML-05) | All of the above on the 3 held-out locations, reported separately | Training locations |
| Back-tests per site | Top-10 events per hazard from onboarding history: Watch/Warning issued? how early? (same code as lead time) | — |

**Pass marks (DD111, requirements 08 §8.5 phase 3).** A calendar-only model is not expected to beat a numerical weather model far ahead, so the pass marks are per model:

| Model | Should beat |
|---|---|
| TFT-base | Persistence and climatology at all horizons; Open-Meteo at 1–3 h |
| TFT-NWP | Not worse than Open-Meteo at any horizon; better on the short horizons or on probability calibration (Brier score) |
| Selected event probabilities (DD52) | All baselines on Brier score and PR-AUC |

If a baseline wins for an output, it is used for that output (requirements 05 §5.1) and the report explains why.

Results are written as `metrics.json` in the model folder; on registration they are loaded into `model_metric` and shown on the model-reports page ([02 §2.6.12](02-api.md)).

**Explainability (ML-10):** `TFTExplainer` on 2 000 validation samples → mean variable-selection weights for static, encoder and decoder inputs → `importance.json`; LightGBM `TreeExplainer` → mean |SHAP| of the top 20 features per classifier → same file (`method = shap`). Loaded into `model_feature_importance`.

## 6.10 Fine-tuning per site (ML-06) and short-range model (ML-07)

| Item | Rule |
|---|---|
| When | ≥ 28 days of kit data with ≥ 80 % hourly coverage (4–8 weeks, phase 3 of requirements 05 §5.6) |
| Data | The kit's `series_1h` exported from the database, plus **our own stored Open-Meteo fetches** (`external_forecast`), which are lead-correct by construction; real `exposure` and `mount_height_m` as static covariates |
| How | Start from the selected TFT; learning rate 1e-4, up to 5 epochs; last 7 days held out (time split) |
| Where | Laptop CPU is enough (a few thousand samples); Kaggle optional |
| Compare | Before/after on the held-out 7 days: MAE per horizon and event Brier score; both shown on the model-reports page |
| Result | A new model version (e.g. `tft-site-abc-1.0.0`) registered and activated only if it is better on the held-out days |
| Event classifiers | Kept global (too few kit events in 4–8 weeks); recalibration on kit data is allowed once ≥ 20 positive windows exist |
| Heat normal offset (D33) | Computed automatically by `worker` once ≥ 28 complete days exist ([07 §7.9](07-forecast-worker.md), DD105); independent of fine-tuning |
| ML-07 (could) | A 15-minute TFT for 0–6 h trained only on kit data once ≥ 6 months exist; same registry mechanism. Not part of the first version |

## 6.11 Model files and versioning (ML-09, DD53)

```
models/
├── registry.json                       (committed)
├── tft-base-1.0.0/                     (files git-ignored; downloaded from the Kaggle run output)
│   ├── model.pt                        Darts checkpoint
│   ├── scaler.json                     global standardisation parameters
│   ├── calibration.json                isotonic/Platt maps per event
│   ├── config.json                     feature list and order, windows, quantiles, library versions
│   ├── metrics.json  importance.json
│   └── MODEL_CARD.md                   data, periods, locations, metrics, limitations
├── tft-nwp-1.0.0/
├── lgbm-events-base-1.0.0/   lgbm-events-nwp-1.0.0/
├── lgbm-quantile-baseline-1.0.0/
└── chronos-bolt-small/                 downloaded once for offline use
```

| Rule | Detail |
|---|---|
| Version names | `<name>-<major>.<minor>.<patch>`: **major** = inputs or features changed (incompatible), **minor** = retrained on the same feature set, **patch** = calibration or selection only |
| Feature contract | `config.json` lists the feature names in order; at load time the `worker` builds a sample with `ews.ml.features` and refuses to load a model whose list does not match (fail fast, logged, admin warning) |
| Integrity | `registry.json` stores the SHA-256 of every file; checked at load |
| Active models | `registry.json` names, per continuous variable and per event, the active model version and its fallback (from `selection.json`) |
| Registration | `worker` reads the registry at start-up and on `models.reload` (CLI command); new versions are inserted into `model_version`, metrics and importance into their tables ([03 §3.7.1](03-database-schema.md)) |
| Traceability | Every forecast run records which version produced each output (`forecast_run_model`) |

```json
{
  "active": {
    "variables": {
      "temp_c":           { "model": "tft-nwp-1.0.0",  "fallback": "tft-base-1.0.0" },
      "wind_gust_kmh":    { "model": "tft-nwp-1.0.0",  "fallback": "tft-base-1.0.0" }
    },
    "events": {
      "gust_orange":      { "model": "tft-nwp-1.0.0",          "fallback": "tft-base-1.0.0" },
      "rain_24h_yellow":  { "model": "lgbm-events-nwp-1.0.0",  "fallback": "lgbm-events-base-1.0.0" },
      "heatwave_orange":  { "model": "lgbm-events-nwp-1.0.0",  "fallback": "tft-base-1.0.0" }
    },
    "shadow": ["chronos-bolt-small"]
  },
  "models": [
    { "version": "tft-nwp-1.0.0", "kind": "tft", "path": "tft-nwp-1.0.0/",
      "trained_at": "2026-12-10T08:00:00Z", "sha256": { "model.pt": "9f2c…" },
      "libs": { "darts": "0.31.0", "torch": "2.4.1" } }
  ]
}
```

(Library versions above are illustrative; the real ones are pinned when training starts.)

## 6.12 Notebooks

| Notebook | Produces |
|---|---|
| `01_download` | Raw files + manifest |
| `02_prepare` | Processed Parquet, scaler |
| `03_normals_labels` | Normals, percentiles, event labels per location |
| `04_baselines` | Persistence, climatology, Open-Meteo, LightGBM quantile, Chronos-Bolt forecasts and metrics |
| `05_tft_base` | TFT-base |
| `06_tft_nwp` | TFT-NWP |
| `07_event_classifiers` | LightGBM event models (base, NWP) |
| `08_calibrate_select` | Calibration maps, `selection.json` |
| `09_evaluate` | Test metrics, held-out locations, lead times, explainability, plots for the report |
| `10_export` | Model folders, model cards, `registry.json` entries |

## 6.13 Compute estimate

| Step | Estimate |
|---|---|
| Downloads | ≈ 1 000 requests (≈ 20 000+ weighted calls), ≈ 2 GB Parquet, over several days (DD118) |
| TFT-base | ≈ 21 locations × 12 years × 2 920 issue times ≈ 740 000 samples; ≈ 10–20 min per epoch on a Kaggle T4 → 3–6 h for the final run; the 6-configuration search on the subset adds ≈ 4–6 h, split across sessions thanks to checkpoints |
| TFT-NWP | ≈ 120 000 samples, ≈ 1 h |
| LightGBM (all) | < 1 h on a laptop CPU |
| Chronos-Bolt test inference | ≈ 1–2 h on CPU (or minutes on GPU) |

## 6.14 Known limitations (for the report)

| Limitation | Effect | Mitigation |
|---|---|---|
| Reanalysis is hourly and smoothed (requirements 05 §5.5) | Underestimates gusts and rain bursts; few red labels | Kit data in fine-tuning; live alerts and squall rules as safety net (AL-02) |
| 0.25° grid vs a point site | Local effects (buildings, slopes) missing | Fine-tuning per kit; static covariates |
| Stitched archived forecasts in stage-2 training | NWP inputs look better in training than live | Validation/test use lead-correct inputs; reported |
| Only 2025 for comparisons with the Open-Meteo baseline | One year, seasonal coverage only once | Report per season; stage-1 results over 2022–2025 |
| Kit vs ERA5 bias (exposure, mount height) | Systematic offsets until fine-tuning; heatwave departure biased | ML-06; normal offset after 28 days (D33); QC external check monitors it |
| One site and one day for heatwaves | IMD declares a heatwave at two stations on two consecutive days | Deliberate adaptation for a single-site early warning; stated in the report |
| Free Kaggle GPU time (about 30 h per week, sessions of 9–12 h) | Long runs hit the session limit or the weekly quota | Per-epoch checkpoints, committed background runs, search on a subset (DD113, DD128) |
| Rain bursts ≥ 20 mm/h almost absent from ERA5 | The `rain_intensity` classifier usually cannot be trained and TFT probabilities above 20 mm/h stay tiny, so **forecast** rain-burst Watch/Warning alerts will rarely be raised; the **Live** rain-burst alert does the real work (AL-02) | Stated in the report and on the model-reports page ("not enough events to train"); measured again with kit data after fine-tuning. 24 h heavy rain is not affected |

## 6.15 Requirement coverage

| Requirement | Section |
|---|---|
| ML-01 | §6.2, §6.3, §6.8.2 |
| ML-02, D28 | §6.7 |
| ML-03 | §6.7, §6.8.1, §6.9 |
| ML-04 | §6.8.3 |
| ML-05 | Global scaling (§6.4), held-out locations (§6.2, §6.9) |
| ML-06 | §6.10 |
| ML-07 | §6.10 |
| ML-08 | §6.8.2 (CPU inference); budget in [07](07-forecast-worker.md) |
| ML-09 | §6.11 |
| ML-10 | §6.9 |
| D7, D8, D9 | §6.8 |
| D20 | §6.2 |
| TST-15 | §6.9 back-tests |
