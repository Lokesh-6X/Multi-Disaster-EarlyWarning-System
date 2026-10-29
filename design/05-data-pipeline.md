# 5. Data Pipeline

What `ingest` does with every MQTT message, the exact contract validation, calibration and conversion formulas, the QC algorithms, derived features, resampling, kit status handling, and the Open-Meteo fetches done by `worker`. Requirements: [03](../requirements/03-data-pipeline.md) (DP-01 – DP-26), contract [02 §2.4](../requirements/02-hardware.md). Tables: [03 §3.6](03-database-schema.md). Settings: [04 §4.3.3](04-configuration.md).

Decisions referenced: DD42–DD47 in [decisions.md](decisions.md).

## 5.1 Message pipeline

```
MQTT message (topic, payload, received_at = server UTC clock at receipt)
  │
  1 parse topic ──── status topic? ─────────────────────────────► §5.6 kit status
  │
  2 decode + validate contract (§5.2) ────── fail ─► rejected_message + NOTIFY message.rejected
  │
  3 kit known and enabled? ──────────────── no ───► rejected_message
  │
  4 duplicate check (§5.2.4) ────────────── identical ─► drop (counted)
  │                                          different ─► rejected_message "conflicting_duplicate"
  5 calibrate + convert (§5.3)
  │
  6 QC checks (§5.4) → flags; faulty → NULL; BME280 → DHT11 fallback
  │
  7 derived features (§5.5), recompute later rows if the reading is late (≤ 3 h)
  │
  8 one transaction: kit_firmware (if changed), reading_raw, reading_clean,
  │                  reading_derived (+ recomputed rows), reading_qc_flag, kit_status_event (if resumed)
  │
  9 NOTIFY reading.ingested (+ kit.qc_flag, kit.status_changed when applicable)
```

| Property | Rule |
|---|---|
| Ordering | Messages of one kit are processed **one at a time, in arrival order** (one async queue per kit); different kits run in parallel |
| Atomicity | Steps 4–8 commit together or not at all; a crash never leaves a raw row without its clean row |
| Budget | ≤ 50 ms per message from receipt to commit (NFR-01 needs ≈ 300 ms, [01 §1.4.1](01-architecture.md)) |
| Replay speed | At 60× replay (TST-01) messages of a kit are committed in batches every 100 ms (one transaction per batch), keeping order |
| Rolling windows | Each kit keeps the last 25 h of clean values in memory for QC and features; on start-up the window is rebuilt from `reading_clean` (DD13) |

## 5.2 Contract validation (DP-12, DD42)

### 5.2.1 Topic

| Check | Reject reason |
|---|---|
| Matches `sites/{site_id}/kits/{kit_id}/readings` or `…/status` | `bad_topic` |
| `{site_id}` = the installation's `site.site_id` (D26) | `wrong_site` |
| `{kit_id}` is a configured kit | `unknown_kit` |
| The kit has `kit_enabled = true` | `kit_disabled` |

### 5.2.2 Reading payload (strict)

The payload must be a UTF-8 JSON object of at most 4 KB with **exactly** these fields; any other field rejects the message (`unknown_field`), so contract drift is noticed immediately.

| Field | Type | Required | Format rules (plausibility is QC, §5.4) |
|---|---|---|---|
| `kit_id` | string | ✅ | Equals the topic's `{kit_id}` (`kit_id_mismatch`) |
| `ts` | string | ✅ | ISO 8601 UTC with `Z`, e.g. `2026-11-02T09:31:00Z`; fractional seconds allowed |
| `seq` | integer | ✅ | ≥ 0 |
| `fw` | string | ✅ | 1–32 characters |
| `bme_temp_c`, `bme_rh_pct`, `bme_pressure_hpa` | number | ✅ | Finite (no NaN/Infinity) |
| `dht_temp_c`, `dht_rh_pct` | number or null | optional | Finite |
| `wind_avg_kmh`, `wind_gust_kmh` | number | ✅ | ≥ 0 |
| `wind_dir_deg` | number or null | optional | 0 ≤ value < 360 |
| `rain_tips` | integer | ✅ | ≥ 0 |
| `rssi_dbm` | integer or null | optional | −130 to 0 |
| `uptime_s` | integer or null | optional | ≥ 0 |

Reject reasons: `not_json`, `too_large`, `missing_field`, `unknown_field`, `wrong_type`, `invalid_value`, `kit_id_mismatch`.

### 5.2.3 Timestamp window

| Condition | Result |
|---|---|
| `ts` more than 7 days before `received_at`, or more than 1 day after | Reject `ts_out_of_window` (typically a kit that lost NTP, e.g. a 1970 clock) |
| Otherwise | Accepted; clock offset and lateness are derived from `received_at − ts` (§5.4.7) |

### 5.2.4 Duplicates (DP-02, DD43)

`reading_raw` has the key `(kit_no, ts)`; the insert uses `ON CONFLICT DO NOTHING`.

| Second message with the same key | Result |
|---|---|
| All fields identical (a QoS 1 resend) | Dropped silently; counted on the kit-health page |
| Any field different | First reading kept (DP-03: raw is never overwritten); the second is stored in `rejected_message` as `conflicting_duplicate` with both `seq` values in the detail. Usually a kit clock or firmware bug |

### 5.2.5 Rejected messages

`rejected_message` stores `reason_code` (the codes above), a readable detail, the topic and the first 2 KB of the payload ([03 §3.6.3](03-database-schema.md)). Each rejection sends `message.rejected` for the kit-health page. Nothing else is stored for a rejected message.

## 5.3 Calibration and conversion (DP-03 – DP-05)

All inputs from the kit's **resolved** configuration at the time of the reading; the config version used is stored on the clean row.

| Clean value | Formula |
|---|---|
| `temp_c` | `bme_temp_c + cal_temp_offset_c` (`temp_sensor = bme280`) |
| `rh_pct` | `bme_rh_pct + cal_rh_offset_pct`; values in (100, 103] are set to 100 (BME280 saturation near fog/rain); above 103 is left for the range check |
| Station pressure *p* | `bme_pressure_hpa + cal_pressure_offset_hpa` (not stored) |
| `pressure_msl_hpa` | Barometric reduction (DP-05): *p₀ = p · (1 − 0.0065·h / (T + 0.0065·h + 273.15))^−5.257*, where *h* = `elevation_m` of the sensor and *T* = `temp_c` (25 °C if temperature is missing) |
| `wind_avg_kmh`, `wind_gust_kmh`, `wind_dir_deg` | Unchanged; `wind_dir_deg` NULL if the vane is disabled |
| `rain_mm` | `rain_tips × rain_mm_per_tip` (DP-04) |

- `elevation_m` means **the sensor's height above sea level** (ground elevation plus mounting, e.g. the rooftop in [04 §4.7](../requirements/04-configuration.md)); `mount_height_m` is height above ground, used only to interpret wind ([04 §4.3](04-configuration.md)).
- A disabled sensor (`sensor_*_enabled = false`) gives NULL clean values and no QC flags for its measurements.
- Rule from the requirements: calibration corrects the instrument, never real local conditions.

## 5.4 Quality checks (DP-20 – DP-26)

### 5.4.1 Outcome per measurement

Checks run **per measurement**, in this order, on the calibrated values. Each failure adds a `reading_qc_flag` row ([03 §3.6.1](03-database-schema.md)). The measurement's status is its worst flag:

| Status | Stored clean value | Used by live alerts, aggregates, forecast |
|---|---|---|
| valid | value | yes |
| suspicious | value | yes, shown with a flag |
| faulty | NULL | no (raw value kept in `reading_raw`) |

A faulty value is excluded from all later checks of the same reading.

### 5.4.2 Range (DP-20) → faulty

| Measurement | Rule |
|---|---|
| `temp_c` | `qc_temp_min_c` ≤ value ≤ `qc_temp_max_c` (−10 to 55) |
| `rh_pct` | 0 ≤ value ≤ 100 (after the saturation rule) |
| `pressure_hpa` (sea level) | `qc_pressure_min_hpa` ≤ value ≤ `qc_pressure_max_hpa` (850–1100) |
| `wind_avg_kmh`, `wind_gust_kmh` | ≤ `qc_wind_max_kmh` (200); and gust ≥ average (otherwise both faulty) |
| `rain_mm` | ≤ `qc_rain_max_mm_per_min` × interval in minutes (default 5 mm/min ≈ 300 mm/h) |

### 5.4.3 Spike (DP-21) → faulty, with re-anchoring

Compare with the previous **valid or suspicious** value of the same measurement, if it is at most 2 × `sampling_interval_s` old:

```
if |value − previous| > qc_spike_<measurement>:
    if the next qc_spike_confirm_readings (default 3) readings all stay within
       qc_spike_<measurement> of this value → accept it as a real level change:
       the flag on the first reading is changed to "suspicious" and the window re-anchors
    else → faulty
```

Applies to temperature (5 °C), humidity (20 %), pressure (3 hPa) per interval. Wind and rain are not spike-checked (gusts and bursts are genuinely spiky; the squall rule depends on them). Because confirmation needs later readings, a spike is first stored as **faulty** (clean value NULL) and may be confirmed up to 3 minutes later: the flag becomes suspicious, the clean value is restored and the derived features from that reading on are recomputed (as for late readings, §5.5.3).

### 5.4.4 Stuck (DP-22) → suspicious

The **raw BME280 value** is identical (same reported value) for at least `qc_stuck_<measurement>_min` consecutive minutes with ≥ 80 % of expected readings present:

| Measurement | Window | Exception |
|---|---|---|
| Temperature | 120 min | — |
| Humidity | 180 min | Not checked while ≥ 99 % (saturated air during rain or fog is genuinely constant) |
| Pressure | 120 min | — |

From the threshold onwards, each further identical reading is flagged until the value changes. DHT11 is not stuck-checked (1 °C / 1 % resolution makes long runs normal). Wind and rain are not checked (calm and dry are normal).

### 5.4.5 Fallback to DHT11 (DD44)

When the BME280 temperature or humidity is **faulty** (range or spike) and the matching DHT11 value is present, its sensor is enabled, and it passes range and spike checks of its own:

- clean `temp_c` (or `rh_pct`) = DHT11 value, `temp_sensor = dht11`;
- the flag for that measurement is written as **suspicious** (detail: "BME280 value 61.2 faulty (range); DHT11 used"), because DHT11 is less accurate (±2 °C, ±5 %).

Pressure has no backup and stays NULL when faulty. MSL pressure then uses the DHT11 temperature.

### 5.4.6 Cross-sensor (DP-23) → suspicious

If both BME280 and DHT11 temperatures are present and |difference| > `qc_cross_sensor_temp_c` (4 °C): `temp_c` gets a `cross_sensor` flag (suspicious). The software cannot know which sensor is wrong, so the value is kept and flagged; persistent disagreement opens a maintenance notice (§5.4.9).

### 5.4.7 Clock and lateness (DP-01, DP-08)

Neither is a flag: both follow from `received_at − ts` in `reading_raw`, so they are computed, not stored (normalization, [03 §3.2](03-database-schema.md)).

| Derived quantity | Definition | Used for |
|---|---|---|
| Clock offset | Median of `received_at − ts` over the kit's last 10 **in-order** messages (`ts` newer than the previous one) | Kit health; maintenance notice when \|offset\| > `qc_clock_skew_max_s` |
| Late reading | `ts` older than the kit's newest stored `ts` (out of order) | Late-data handling (§5.5.3) |
| Very late | `received_at − ts` > `late_window_min` (180 min) | Not used for derived features or live alerts |

### 5.4.8 Neighbour and external checks (DP-24, DP-25) → suspicious

| Check | When it runs | Rule |
|---|---|---|
| Neighbour | At least `qc_neighbour_min_kits` (3) kits have a valid value within ±1 min | \|value − median of the **other** kits\| > spread → `neighbour` flag. Measurements: `temp_c`, `pressure_hpa` (sea level; the best fault detector). Spread = `qc_neighbour_<m>` until 7 days of multi-kit data exist; then 3 × the median absolute deviation of the kit's differences over the last 14 days, recomputed nightly by `worker` into `qc_neighbour_spread` |
| External | The latest Open-Meteo fetch is < 6 h old | Forecast value linearly interpolated to the reading's minute; \|clean − external\| > `qc_external_temp_c` (6 °C) or > `qc_external_pressure_hpa` (4 hPa) → `external` flag |

With one or two kits the neighbour check does not run: with two kits it would be impossible to tell which one is wrong.

### 5.4.9 Maintenance notices (DP-26)

`ingest` emits `kit.qc_flag` for every new flag; `alerts` opens and closes notices ([01 §1.2](01-architecture.md), table `maintenance_notice`):

| Notice `kind` | Opens when | Closes when |
|---|---|---|
| `stuck_sensor` | Any stuck flag | Value changes |
| `cross_sensor` | Cross-sensor flags on ≥ 80 % of readings for 30 min | Agreement for 30 min |
| `faulty_readings` | ≥ 5 faulty measurements in 60 min | None in 60 min |
| `clock_skew` | \|clock offset\| > `qc_clock_skew_max_s` | Offset back within the limit |
| `offline` | Kit goes offline (§5.6) | Kit online |
| `rejected_messages` | ≥ 5 rejected messages in 60 min | None in 60 min |

At most one open notice per kit and kind; operators are emailed when a notice opens if `notify_maintenance` is on ([09](09-notifications.md)).

## 5.5 Derived features (DP-06)

### 5.5.1 Definitions

Computed for every accepted reading from the in-memory window of clean values (faulty = missing). A windowed feature is NULL when fewer than `qc_coverage_min_pct` (80 %) of the expected readings in its window are present, so gaps never look like calm or dry weather.

| Feature | Definition |
|---|---|
| `heat_index_c` | NOAA heat index (Rothfusz regression with the standard low-humidity and high-humidity adjustments; Steadman's simple formula below 80 °F), computed in °F and converted; equals `temp_c` when `temp_c` < 26.7 °C. Same Python function used in training ([06](06-ml-training.md)) |
| `rain_rate_mmh` | Rain over the last 10 min × 6 (a single tip in one minute would read 16.8 mm/h, too noisy) |
| `rain_1h_mm`, `rain_3h_mm`, `rain_24h_mm` | Sum of `rain_mm` over (ts − window, ts] |
| `pressure_tendency_1h_hpa`, `…_3h_hpa` | `pressure_msl(ts)` − `pressure_msl` at ts − 1 h (or 3 h), using the nearest valid reading within ±5 min of that time |
| `gust_trend_15m_kmh`, `…_30m_kmh`, `…_60m_kmh` | Mean gust over the last *N* min − mean gust over the *N* min before that (positive = rising) |
| `temp_change_30m_c` | `temp_c(ts)` − `temp_c` at ts − 30 min (nearest within ±3 min) |

### 5.5.2 Squall inputs

The squall rule itself belongs to the alert engine ([08](08-alert-engine.md)); the pipeline provides its inputs: per-minute mean wind (`wind_avg_kmh`) and gust, the `squall_baseline_min` mean of `wind_avg_kmh` (D31), pressure rise and temperature drop over `squall_precursor_window_min`, humidity rise. These are read from `reading_clean` / `reading_derived` by `alerts`.

### 5.5.3 Late readings (DP-08, DD45)

| Lateness (`received_at − ts`) | Stored | Derived features | Aggregates | Live alerts |
|---|---|---|---|---|
| In order | ✅ | computed | refreshed by policy | evaluated |
| Out of order, ≤ 180 min | ✅ | computed for the reading **and recomputed for every later reading of that kit up to now**, in the same transaction | the 15 m / 1 h refresh window (3 h / 26 h) folds it in | passed to the engine, which ignores readings older than its live window ([08](08-alert-engine.md)) |
| > 180 min | ✅ (raw, clean, flags) | not computed | folded into `reading_1h` if within 26 h | not used |

Kits do not resend after an outage (HW-09), so late readings are rare (network delay only); recomputing at most 180 rows per kit is cheap.

## 5.6 Kit status (DP-09, DP-13, HW-12)

| Input | Action (only if the kit's current status differs) |
|---|---|
| Status topic payload `online` | Insert `kit_status_event(online, status_topic)` at `received_at` |
| Status topic payload `offline` (last will or kit) | Insert `offline, status_topic` |
| Any other payload | Reject `bad_status_payload` |
| A reading from a kit currently `offline` | Insert `online, reading_resumed` before storing the reading |
| Timer every 30 s: kit `online` and no message for `kit_offline_timeout_s` (5 min) | Insert `offline, no_data_timeout` (backup when the broker itself failed) |

- Status messages are retained, so `ingest` receives them again after every reconnect; comparing with the current status prevents duplicate events.
- A configured kit that has never sent anything shows "never connected" (no events yet).
- The first accepted message from any kit sets `site.locked_at`; from then on `site_id` is immutable ([03 §3.5.1](03-database-schema.md)).
- Every change sends `kit.status_changed`.

## 5.7 Resampling (DP-07)

Continuous aggregates `reading_15m` and `reading_1h` ([03 §3.6.2](03-database-schema.md)), final column set:

| Column | Aggregate |
|---|---|
| `temp_c`, `rh_pct`, `pressure_msl_hpa`, `wind_avg_kmh` | mean |
| `temp_max_c`, `temp_min_c` | max, min (daily maximum for heatwave) |
| `wind_gust_kmh` | max |
| `rain_mm` | sum |
| `wind_dir_sin`, `wind_dir_cos` | mean of sin/cos (circular mean = `atan2`, computed when read) |
| `n_readings`, `n_temp_valid`, `n_wind_valid`, `n_rain_valid` | counts for coverage |

Two views (not stored) are what consumers read:

| View | Adds |
|---|---|
| `series_15m`, `series_1h` | **End-labelled time**: `ts_end = bucket + width`. Open-Meteo and ERA5 label hourly sums and gust maxima by the end of the hour (the value at 11:00 is 10:00–11:00), so the kit series uses the same convention as training data (DD46) |
| Coverage rule | Each value is NULL when its count is below 80 % of expected readings (e.g. < 48 readings in an hour at 60 s), so the model sees gaps as missing, not as zero rain |

The forecast run does not use the clock-hour `series_1h`: it builds **rolling hours ending at each issue time** from four `series_15m` buckets ([07 §7.3](07-forecast-worker.md)). `series_1h` serves charts, fine-tuning and reports.

Daily maximum temperature for heatwave rules is the maximum of `temp_max_c` over the site's local calendar day (timezone from config), with the same 80 % coverage rule.

## 5.8 Open-Meteo (DP-10, onboarding)

### 5.8.1 Forecast fetch (`worker`, every `external_fetch_interval_min` = 60 min, at minute 05)

```
GET https://api.open-meteo.com/v1/forecast
    ?latitude={site lat}&longitude={site lon}
    &hourly=temperature_2m,relative_humidity_2m,wind_gusts_10m,precipitation,pressure_msl
    &wind_speed_unit=kmh&timezone=GMT&forecast_days=4&past_days=7
```

`past_days=7` also returns the recent past, which the forecast run uses as pseudo-observations for kit gaps and new kits ([07 §7.4](07-forecast-worker.md)).

| Rule | Detail |
|---|---|
| Mapping | `temperature_2m → temp_c`, `relative_humidity_2m → rh_pct`, `wind_gusts_10m → wind_gust_kmh`, `precipitation → rain_mm`, `pressure_msl → pressure_msl_hpa` |
| Storage | One `external_forecast` row (fetched_at, lat, lon, `provider_model = 'best_match'`) and its values; `issued_at` NULL (the API does not report the model run time) |
| Failures | Timeout 20 s; 3 attempts with 10 s / 30 s / 90 s backoff; on failure the previous fetch stays in use and the kit-health/system status shows its age |
| Staleness | QC external check uses fetches < 6 h old; how the forecast run handles an old or missing fetch is defined in [07](07-forecast-worker.md) |
| Variables for the model | If [06](06-ml-training.md) needs more known-future inputs (e.g. wind speed), they are added here and to the `forecast_variable` enum |

### 5.8.2 Historical download (onboarding, [04 §4.5](../requirements/04-configuration.md))

```
GET https://archive-api.open-meteo.com/v1/archive
    ?latitude=…&longitude=…&start_date=YYYY-01-01&end_date=YYYY-12-31
    &hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,wind_gusts_10m,precipitation,pressure_msl
    &wind_speed_unit=kmh&timezone=GMT
```

- `&models=era5` is added so the site's history matches the training data ([06 §6.3](06-ml-training.md)). The period runs from `normals_start_year` (1991) to the last complete year (≈ 35 years, covering the normals period and the 20–30 years required).
- One request per year, **10 s apart** (DD118): the free API counts a long or many-variable request as several calls (one year of six variables ≈ 25 or more), with limits per minute, hour and day; check the current terms. On `429` the worker waits for `Retry-After` and continues. Each year is committed separately, so a failed or paused download resumes where it stopped. Onboarding therefore downloads for about 6 minutes, shown in the progress view.
- **Rain-burst threshold (D32, DD104):** the `rain_intensity_percentile` (99th) of **wet hours** only (≥ `rain_wet_hour_min_mm`, 0.1 mm), raised to at least `rain_intensity_floor_mm` (20 mm/h). The percentile of all hours would be only a few mm/h because most hours are dry, and reanalysis smooths bursts.
- **Normal offset (D33, DD105):** later, a daily `worker` job downloads the ERA5 daily maxima of recent days (same API, about 5 days latency) to compare them with each kit's daily maxima ([07 §7.9](07-forecast-worker.md)).
- Stored in `history_hourly` under a new `history_dataset` ([03 §3.8](03-database-schema.md)).
- Open-Meteo's free API is for non-commercial use, which fits a student project; the report should cite it (and ERA5 / Copernicus as its source).
- Reanalysis is hourly and smoothed and underestimates short gusts and bursts (requirements 05 §5.5); this is stated in the report.

## 5.9 Throughput and size

| Situation | Load | Fits |
|---|---|---|
| 1 kit, normal | 1 message/min | trivially |
| 5 kits, replay 60× | 5 messages/s (1 per kit per real second; 10/s at 120×) | batched commits every 100 ms (§5.1), with a large margin |
| Database growth | ≈ 3 rows per reading + rare flags | [03 §3.14](03-database-schema.md) |

## 5.10 Requirement coverage

| Requirement | Section |
|---|---|
| DP-01 | §5.1 (`received_at`), §5.4.7 |
| DP-02 | §5.2.4 |
| DP-03 | §5.3, raw never overwritten (§5.2.4) |
| DP-04, DP-05 | §5.3 |
| DP-06 | §5.5 |
| DP-07 | §5.7 |
| DP-08 | §5.5.3, aggregate refresh window |
| DP-09, DP-13, HW-12 | §5.6 |
| DP-10 | §5.8.1 |
| DP-11 | `kit_no` on every row |
| DP-12 | §5.2 |
| DP-20 – DP-25 | §5.4.2 – §5.4.8 |
| DP-26 | §5.4.9 |
| HW-05, HW-06, HW-09, HW-11 | Tips converted in the server; UTC timestamps checked; no resend assumed; wind direction optional |
