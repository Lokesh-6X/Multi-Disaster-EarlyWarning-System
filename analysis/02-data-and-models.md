# 2. Data and Models

Whether the data sources and models can deliver what the alert rules assume. The training design ([design/06](../design/06-ml-training.md)) is careful about leakage, splits and calibration. The risks are mostly where **reanalysis data (ERA5, a 28 km grid, hourly)** meets **a real kit (one point, one minute, often on a rooftop)**.

Summary:

| ID | Finding | Severity |
|---|---|---|
| AN-11 | The 99th-percentile hourly rain threshold is probably far too low | High |
| AN-12 | Heatwave departure compares a kit with a grid normal | High |
| AN-13 | "Beats the baselines" is not a realistic pass mark for every horizon | Medium |
| AN-14 | Lead-correct forecast archives may cover less than the splits need | Medium |
| AN-15 | Free Colab may not finish the TFT training plan in one go | Medium |
| AN-16 | Nobody knows yet how many alerts a normal week produces | Medium |
| AN-17 | IMD declares a heatwave over two days; the design uses one | Low |

---

## AN-11 The 99th-percentile hourly rain threshold is probably far too low — High (owner decision)

**Where:** requirement 06 §6.1 ("rain above the site's 99th-percentile hourly rainfall"); `rain_intensity_1h_mm` computed at onboarding ([04 §4.3.6](../design/04-configuration.md)); training label "max hourly rain ≥ the location's p99" ([06 §6.6](../design/06-ml-training.md)). Scenario 4 assumes **28 mm/h**.

**The problem, in two parts:**

1. **Percentile of what?** At most Indian sites more than 85 % of hours are dry. The 99th percentile of **all** hours is therefore the rain of roughly the 88 wettest hours of an average year, which in reanalysis is likely only **a few mm/h** (to be confirmed on the data), not 28 mm/h.
2. **Grid vs point.** ERA5 spreads a downpour over a 28 km cell, so its hourly peaks are much lower than a rain gauge measures ([06 §6.14](../design/06-ml-training.md) already says so). The threshold comes from the smoothed grid; the Live check compares it with the kit's **point** measurement.

**What happens if built as designed:** an ordinary shower of 6 mm/h at the kit raises 🟠 **Orange Live "Heavy rain burst – waterlogging likely"** and emails the whole site. By definition about 1 % of all hours exceed the threshold, so the event is not rare enough to deserve an Orange alert, and the training labels are not "hazard" labels either.

**Options:**

| Option | Threshold |
|---|---|
| A (suggested) | 99th percentile of **wet hours** (≥ 0.1 mm), with a **floor** (e.g. ≥ 20 mm/h, set after looking at the numbers) |
| B | A fixed intensity (e.g. 30 mm/h, the current fallback), site-overridable, no percentile |
| C | Keep the percentile but compute it from the kit's own data once a season exists |

Whatever is chosen, **check the numbers first**: notebook `03_normals_labels` should print the all-hours and wet-hours p99 for the 24 training locations before the rule is fixed. Requirement 06 §6.1, the real-time scenario and DD38 change with the decision.

---

## AN-12 Heatwave departure compares a kit with a grid normal — High (owner decision)

**Where:** "normal" = daily normal maximum from ERA5 1991–2020 for the site's grid cell ([05 §5.8.2](../design/05-data-pipeline.md), [04 §4.5](../requirements/04-configuration.md)); the Live heatwave compares the **kit's** temperature with it ([08 §8.6.1](../design/08-alert-engine.md)).

**The problem:** IMD compares a station with **its own** 30-year normal. Here the kit and the normal come from different "instruments":

| Source of difference | Typical effect |
|---|---|
| Rooftop or between buildings, even with a radiation shield (exposure) | Kit warmer by day than open-ground 2 m air |
| Coastal site: the ERA5 cell is partly sea | Grid normal maximum lower than inland reality → departure **inflated** |
| Hilly site: the cell's mean height differs from the kit's | Departure off by the lapse rate (≈ 0.65 °C per 100 m) |

The coastal rule fires at **+4.5 °C**. A systematic bias of 1.5–2 °C, which is common between a point and a grid cell, moves a site from "never" to "often", or the reverse. The model forecasts (trained on ERA5) and the kit-based Live alerts will also disagree.

**Note on the rule "never configure a correction for real local conditions":** a rooftop being hot **is** real (it should not be calibrated away). But here the issue is comparing **two different references**, not correcting the kit. A correction of the **normal**, not of the readings, is consistent with that rule.

**Options:**

| Option | Effect |
|---|---|
| A (suggested) | After 4–8 weeks (ML-06 timing), compute a **normal offset** = median of (kit daily max − ERA5/Open-Meteo daily max) over the overlap, and add it to the normals as a computed default (DD38 already supports computed defaults). Until then use the plain normal and mark heatwave alerts "uncalibrated normal" |
| B | Use the plain grid normal and state the bias as a known limitation in the report |
| C | Base the heatwave on the absolute thresholds only (≥ 45 / ≥ 47 °C) until the offset exists |

---

## AN-13 "Beats the baselines" is not a realistic pass mark for every horizon — Medium

**Where:** build order phase 3, "Done when: test results beat baselines" ([requirements 08 §8.5](../requirements/08-non-functional-and-testing.md)).

**The problem:** beyond a few hours, weather is predicted by physics-based weather models; a TFT that sees only past local data and the calendar (**TFT-base**) will very likely **lose to Open-Meteo at 24–72 h**, which is a full numerical weather model. That is expected, not a failure. The design already handles it (TFT-NWP gets the Open-Meteo forecast as input; the best model is selected per output, DD52), but the pass mark should not set the project up to "fail" its own criterion.

**Suggested pass marks** (to replace the single phrase):

| Model | Should beat |
|---|---|
| TFT-base | Persistence and climatology at all horizons; Open-Meteo at 1–3 h |
| TFT-NWP | Open-Meteo on at least the short horizons and on probability **calibration** (Brier score); not worse at 24–72 h |
| Event probabilities (selected per event) | All baselines on Brier score and PR-AUC |

If a baseline wins for an output, it is used for that output (requirements 05 §5.1); the report then explains why. That is a valid result.

---

## AN-14 Lead-correct forecast archives may cover less than the splits need — Medium

**Where:** lead-correct archived forecasts come from the Open-Meteo Previous Runs API, "from about 2024; confirmed at download" ([06 §6.3](../design/06-ml-training.md)); stage-2 validation is 2024 and the all-model comparison is 2025 ([06 §6.7](../design/06-ml-training.md)).

**The risk:** if the archive starts part-way through 2024, or some variables (e.g. gusts) start later, the 2024 validation year is partly stitched (too optimistic), and the 2025 comparison year may be the only clean data. The design says "wherever they exist", but the splits, the model selection and the report all depend on the actual start date.

**Suggested action:** make the download of one location's Previous Runs data a **week-1 check** ([05 §5.3](05-scope-and-plan.md)) and write the real start date per variable into `ml/data/manifest.json`. If coverage is short, move stage-2 validation to the covered part of 2024–2025 and say so.

---

## AN-15 Free Colab may not finish the TFT training plan in one go — Medium

**Where:** [06 §6.13](../design/06-ml-training.md): TFT-base ≈ 3–6 h on a T4, plus a search over hidden 32/64/128 × dropout 0.1/0.2 = 6 configurations, plus TFT-NWP.

**The risk:** 6 configurations × 3–6 h is 18–36 GPU hours. Free Colab sessions disconnect and GPU time is rationed, so a run can be lost near the end.

**Suggested action:**

- Save a checkpoint to Google Drive **every epoch** and make training resumable (Darts `save_checkpoints` / `load_from_checkpoint`).
- Tune on a **subset** (e.g. 6 locations, 4 years), then train the chosen configuration once on everything.
- First trial run on CPU with 2 locations and 1 epoch, end to end through export and `worker` loading, so the whole chain is proven before the long run.

---

## AN-16 Nobody knows yet how many alerts a normal week produces — Medium

**Where:** across [04 §4.3.6–4.3.7](../design/04-configuration.md) and [08](../design/08-alert-engine.md).

**The problem:** each rule was checked for "does it fire in the scenario", not for "how often does it fire in ordinary weather". Several thresholds were designed on reanalysis but are applied to kit data:

| Rule | Why it may fire often |
|---|---|
| Wind Yellow ≥ 39 km/h **gust** | Beaufort levels are defined for the **mean** wind; a 3-second gust of 39 km/h comes with a mean of only ≈ 25 km/h, common on a rooftop on a monsoon afternoon |
| Rain intensity (AN-11) | Threshold from smoothed grid data |
| Heatwave (AN-12) | Biased normal |
| TFT probabilities on kit data | Trained on ERA5; kit history fed to the encoder looks different (gustier, peakier) until fine-tuning ([06 §6.14](../design/06-ml-training.md)) |

**Suggested action:** an **alert-volume dry run** once the alert engine exists: replay a whole real year for the demo location through `ingest` and `alerts` with the simulator at high speed (the replay generator already produces minute data from ERA5, [11 §11.4.1](../design/11-simulator.md)), and count alerts and emails per week per hazard and level. Agree a target with the owner (for example "Yellow wind at most a few times a month") and adjust defaults before the demo. Report the counts; they are good evidence of false-alarm control.

---

## AN-17 IMD declares a heatwave over two days; the design uses one — Low

**Where:** heatwave label and Live rule use a single local day ([06 §6.6](../design/06-ml-training.md), [08 §8.6.1](../design/08-alert-engine.md)).

**The point:** IMD declares a heatwave when the criteria hold at two stations of a subdivision on two consecutive days. A one-site system cannot use the "two stations" part, and a one-day rule is a reasonable adaptation for an early-warning system. It should be **stated in the report** as a deliberate difference from the IMD definition, so it is not read as a mistake.

---

## What was checked and holds

| Topic | Result |
|---|---|
| Time-based splits, 7-day gaps, test used once, selection on validation (DD52) | Correct and leakage-free |
| No reanalysis used as a stand-in forecast (D28) | Correct |
| Global standardisation, no per-site fitting (DD50) | Supports ML-05 |
| 3 held-out locations | Direct evidence for ML-05 |
| Sample count (21 × 12 years × 2 920 issue times ≈ 740 000) | Arithmetic correct |
| CPU inference budget (10–20 s for 5 kits) | Plausible for a 5–10 MB TFT |
| Classifier only at its trained threshold, TFT for local-risk thresholds (DD59) | Sound |
| Summing hourly quantiles for 24 h rain | Over-wide, but it is only a raw score that is calibrated afterwards; acceptable |
