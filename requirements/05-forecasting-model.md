# 5. Forecasting Model

## 5.1 Model choice

**Main model: Temporal Fusion Transformer (TFT).**

| Need | Why TFT |
|---|---|
| Several targets (temperature, humidity, gust, rain, pressure) | Multi-target forecasting |
| Horizons 1–72 h | Multi-horizon output in one pass |
| Probability of exceeding thresholds | Quantile outputs (e.g. P10, P50, P90) |
| Configurable sites/kits | Static inputs (lat, lon, elevation, region type, exposure, mount height) |
| Time of day, date, external forecast | Known-future inputs |
| Multiple kits later | Trains on many series at once |
| Explainability for the report | Variable-importance and attention outputs |

**Supporting models**

| Model | Role |
|---|---|
| LightGBM classifier | Probability of heavy rain (rain is zero-inflated; a dedicated classifier handles it better) |
| Rules on live data | Squall detection: pressure jump + temperature drop + wind rise |

**Baselines (for comparison in the report)**

| Model | Purpose |
|---|---|
| Persistence | Minimum bar |
| Open-Meteo forecast, unchanged | Must the system beat a free public forecast? |
| LightGBM (lag/rolling features, quantile) | Strong classic baseline |
| Chronos-Bolt (zero-shot) | Modern pretrained model, no training |

The final model per hazard is chosen from test results; if LightGBM wins for a hazard, it is used for that hazard.

## 5.2 Inputs

| Type | Examples |
|---|---|
| Static | lat, lon, elevation, region type, exposure, mount height, local normals |
| Observed past | Kit readings and derived features: pressure tendency, rain totals, gust trends, heat index, temperature change |
| Known future | Hour of day, day of year, month; Open-Meteo forecast of temperature, humidity, gust, precipitation, pressure (stage-2 model only; archived forecasts exist only from about 2022, see D28) |

## 5.3 Outputs

Quantile forecasts (at least P10, P50, P90) for temperature, humidity, wind gust, rainfall and pressure at hourly steps up to 72 h. Exceedance probabilities (e.g. P(gust > 45 km/h in next 2 h)) are derived from the quantiles or from calibrated LightGBM classifiers (heavy rain, and other events where they do better); the source is chosen per event on validation data ([design/06 §6.8.5](../design/06-ml-training.md)).

## 5.4 Requirements

| ID | Requirement | Priority |
|---|---|---|
| ML-01 | Pre-train a **global** TFT on hourly history (≈15 years) from 20–30 Indian locations covering plains, coastal and hilly regions. | M |
| ML-02 | Split by time, never randomly. Stage 1 (TFT-base, calendar-only future inputs): train 2008–2019, validate 2020–2021, test 2022–2025. Stage 2 (TFT-NWP, fine-tuned with archived Open-Meteo forecasts as future inputs): train 2022–2023, validate 2024, test 2025 (D28). | M |
| ML-03 | Train and evaluate all baselines on the same splits; models that use or are the Open-Meteo forecast (TFT-NWP, Open-Meteo baseline) are compared with the others on the 2025 test year. | M |
| ML-04 | Handle class imbalance for hazard classifiers (class weights / `scale_pos_weight`). | M |
| ML-05 | The global model shall run on a newly configured site without retraining. | M |
| ML-06 | After 4–8 weeks of kit data, fine-tune on the kit's data and compare before/after. | S |
| ML-07 | Add a 15-minute short-range model (0–6 h) once enough kit data exists (history is hourly only). | C |
| ML-08 | Inference every 15 minutes on CPU within the refresh interval. | M |
| ML-09 | Models shall be versioned; every stored forecast records the model version that produced it. | M |
| ML-10 | Report variable importance (TFT) / SHAP (LightGBM) for explainability (shown on the model-reports page, [07](07-web-application.md)). | S |

## 5.5 Training data

- Source: Open-Meteo Historical API or ERA5 — hourly temperature, humidity, wind speed, wind gusts (`wind_gusts_10m`), precipitation, surface/sea-level pressure.
- Archived forecasts for the known-future inputs and the Open-Meteo baseline: Open-Meteo Historical Forecast API (available from about 2022). Using reanalysis values as a stand-in forecast is not allowed: it leaks the future into training.
- Labels are generated automatically by applying the hazard thresholds ([06](06-hazards-and-alerts.md)) to history; no separate disaster database is needed.
- Known limitation: reanalysis is hourly and smoothed, so it underestimates short gusts and rain bursts. Kit data (1-minute) corrects this during fine-tuning. State this in the report.
- Training environment: Kaggle Notebooks GPU (D40).

## 5.6 Training phases

| Phase | When | What |
|---|---|---|
| 1 | Before the kit exists | Global TFT + baselines on historical data |
| 2 | Kit goes live | Global TFT runs on live data; Chronos-Bolt runs alongside for comparison |
| 3 | After 4–8 weeks | Fine-tune on kit data; optional 15-min short-range model |

## 5.7 Evaluation

| Output | Metrics |
|---|---|
| Continuous forecasts | MAE, RMSE per variable **per horizon**; compare with persistence and Open-Meteo |
| Quantiles | Coverage (does P10–P90 contain ~80 % of observations?), pinball loss |
| Hazard alerts | Recall, precision, false-alarm rate, F1, PR-AUC |
| Lead time | Hours between first alert and event onset |
| Back-tests | Per-site top-10 historical events: was a Watch/Warning issued, and how early? |

Libraries: Darts (TFT, baselines), `lightgbm`, `chronos-forecasting` ([design DD48](../design/decisions.md)).
