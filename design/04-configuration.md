# 4. Configuration

Every setting the system uses: its key, type, default, the levels allowed to set it, validation, when a change takes effect, how values are resolved, and how a whole site is imported or exported as YAML. Requirements: [04](../requirements/04-configuration.md) (CFG-01 – CFG-07). Storage: [03 §3.5](03-database-schema.md). API: [02 §2.6.8](02-api.md).

Decisions referenced: DD37–DD41 in [decisions.md](decisions.md).

## 4.1 Principles

| Principle | Rule |
|---|---|
| Three levels (CFG-01) | **Default** (shipped in `config/defaults.yaml`) → **Site** → **Kit**; each key resolves on its own; the most specific level that sets it wins |
| Allowed levels (CFG-02) | Every key declares which levels may set it; a save at any other level is rejected (`OVERRIDE_NOT_ALLOWED`) |
| Configure what the kit cannot measure | Never a correction for real local conditions ([04 §4.3](../requirements/04-configuration.md)) |
| Flat keys with prefixes (DD37) | `snake_case`, unit in the name: `wind_orange_kmh`, `alert_warning_on_prob`, `qc_temp_max_c`. Prefix = group |
| Scalars | A value is a number, integer, string or boolean. The only exception is `report_horizons_h` (a list of integers, default-only) |
| Sets of records | Alert recipient lists are tables, not keys ([03 §3.5.3](03-database-schema.md)) |
| Defaults change with software | `defaults.yaml` is versioned in git, not in the database; stored records keep the values actually applied ([03 §3.2](03-database-schema.md), N4) |

## 4.2 Resolution algorithm (DD38)

Two extra kinds of default fill the "Default" level:

- **Region defaults:** some keys have one default per `region_type` (`plains`, `coastal`, `hilly`); the site's region type picks the row (heatwave rules, [06 §6.1](../requirements/06-hazards-and-alerts.md)).
- **Computed defaults:** some keys default to a value computed by site onboarding (e.g. `rain_intensity_1h_mm` = the site's 99th-percentile hourly rain). Until onboarding has produced it, the key's static fallback is used.

```
resolve(key, kit = None):
    meta = key catalogue[key]
    if kit and meta.kit_allowed and key set in kit's current version:   return value, "kit"
    if meta.site_allowed and key set in site's current version:         return value, "site"
    if meta.computed_from and onboarding result available:              return result, "onboarding"
    if meta has region defaults:                                        return region_default[site.region_type], "default"
    return meta.default, "default"            # may be "none" only for keys required at a level
```

| Source value | Shown in `GET /config/effective` |
|---|---|
| `kit` | Set on this kit |
| `site` | Set on the site |
| `onboarding` | Computed from the site's history (with the onboarding job date) |
| `default` | From `defaults.yaml` (with `region_type` when a region default was used) |

The resolver lives in `ews.common.config` and is the only implementation; `api`, `ingest`, `worker` and `alerts` all use it, and each caches the resolved values until `config.changed` ([01 §1.3.3](01-architecture.md)).

## 4.3 Key catalogue

Columns: **D** = default, **S** = site, **K** = kit (✅ allowed, — not allowed). **Req** = level where a value is required.

### 4.3.1 Site identity

| Key | Type | Default | D | S | K | Req | Unit / rules |
|---|---|---|---|---|---|---|---|
| `site_name` | string | — | — | ✅ | — | S | 1–100 characters |
| `lat` | number | — | — | ✅ | ✅ | S, K | −90 to 90; °; a kit's value must be set and lie inside the site area |
| `lon` | number | — | — | ✅ | ✅ | S, K | −180 to 180; ° |
| `site_radius_km` | number | 2.0 | ✅ | ✅ | — | | 0.1–50; site area for "kit inside site" (CFG-03) |
| `elevation_m` | number | — | ✅ | ✅ | ✅ | S | −100 to 6000; m. Height of the **sensor** above sea level (ground + mounting); a kit without its own value uses the site's (DP-05, [05 §5.3](05-data-pipeline.md)) |
| `timezone` | string | `Asia/Kolkata` | ✅ | ✅ | — | | Valid IANA name |
| `region_type` | string | — | — | ✅ | — | S | `plains`, `coastal`, `hilly`; changes heatwave defaults, re-runs onboarding |

`site_id` is not a key: it is the immutable row in `site` ([03 §3.5.1](03-database-schema.md)).

### 4.3.2 Kit description and hardware

| Key | Type | Default | D | S | K | Req | Unit / rules |
|---|---|---|---|---|---|---|---|
| `kit_zone` | string | — | — | — | ✅ | K | 1–60 characters, unique among enabled kits |
| `kit_enabled` | boolean | `true` | ✅ | — | ✅ | | `false` retires the kit; its messages are rejected (`kit disabled`) |
| `mount_height_m` | number | 2.0 | ✅ | — | ✅ | | 0.5–30; m |
| `exposure` | string | — | — | — | ✅ | K | `rooftop`, `open_ground`, `between_buildings`, `under_trees` (interpretation only) |
| `cal_temp_offset_c` | number | 0 | ✅ | — | ✅ | | −5 to 5; °C. Default 0 = no correction (calibration is kit-only, [04 §4.4](../requirements/04-configuration.md)) |
| `cal_rh_offset_pct` | number | 0 | ✅ | — | ✅ | | −15 to 15; % |
| `cal_pressure_offset_hpa` | number | 0 | ✅ | — | ✅ | | −5 to 5; hPa |
| `sensor_bme280_enabled` | boolean | `true` | ✅ | — | ✅ | | Disabled sensors' fields are ignored |
| `sensor_dht11_enabled` | boolean | `true` | ✅ | — | ✅ | | |
| `sensor_anemometer_enabled` | boolean | `true` | ✅ | — | ✅ | | |
| `sensor_rain_gauge_enabled` | boolean | `true` | ✅ | — | ✅ | | e.g. broken gauge |
| `sensor_wind_vane_enabled` | boolean | `true` | ✅ | — | ✅ | | Used only if the kit sends `wind_dir_deg` (HW-11) |
| `sampling_interval_s` | integer | 60 | ✅ | ✅ | ✅ | | 30, 60, 120 or 300; expected message interval (HW-07) |
| `rain_mm_per_tip` | number | 0.28 | ✅ | — | ✅ | | 0.1–1.0; mm (DP-04) |

### 4.3.3 Ingestion and data quality

| Key | Type | Default | D | S | K | Unit / rules |
|---|---|---|---|---|---|---|
| `ingest_grace_period_s` | integer | 120 | ✅ | — | — | 0–900; s (DP-08) |
| `kit_offline_timeout_s` | integer | 300 | ✅ | ✅ | — | 60–3600; s; ≥ 2 × `sampling_interval_s` (DP-09) |
| `qc_clock_skew_max_s` | integer | 120 | ✅ | — | — | 5–3600; s (DP-01) |
| `qc_temp_min_c` / `qc_temp_max_c` | number | −10 / 55 | ✅ | ✅ | — | °C; min < max (DP-20) |
| `qc_rh_min_pct` / `qc_rh_max_pct` | number | 0 / 100 | ✅ | — | — | % |
| `qc_pressure_min_hpa` / `qc_pressure_max_hpa` | number | 850 / 1100 | ✅ | ✅ | — | hPa (sea-level) |
| `qc_wind_max_kmh` | number | 200 | ✅ | — | — | km/h |
| `qc_spike_temp_c` | number | 5 | ✅ | — | — | °C per reading interval (DP-21) |
| `qc_spike_rh_pct` | number | 20 | ✅ | — | — | % per interval |
| `qc_spike_pressure_hpa` | number | 3 | ✅ | — | — | hPa per interval; above the squall jump (1–3 hPa in minutes) |
| `qc_stuck_temp_min` | integer | 120 | ✅ | — | — | min with identical value → suspicious (DP-22) |
| `qc_stuck_rh_min` | integer | 180 | ✅ | — | — | min |
| `qc_stuck_pressure_min` | integer | 120 | ✅ | — | — | min (wind and rain are not stuck-checked: calm and dry are normal) |
| `qc_cross_sensor_temp_c` | number | 4 | ✅ | — | — | °C, BME280 vs DHT11 (DP-23) |
| `qc_neighbour_temp_c` | number | 3 | ✅ | ✅ | — | °C from the median of other kits; replaced by the learned spread when available (DP-24) |
| `qc_neighbour_pressure_hpa` | number | 1.0 | ✅ | ✅ | — | hPa (sea-level) |
| `qc_external_temp_c` | number | 6 | ✅ | ✅ | — | °C from the current Open-Meteo value (DP-25) |
| `qc_external_pressure_hpa` | number | 4 | ✅ | ✅ | — | hPa from the current Open-Meteo value |
| `qc_rain_max_mm_per_min` | number | 5 | ✅ | — | — | mm per minute (≈ 300 mm/h) before rain counts as faulty |
| `qc_spike_confirm_readings` | integer | 3 | ✅ | — | — | Readings at the new level that turn a spike into an accepted level change |
| `qc_neighbour_min_kits` | integer | 3 | ✅ | — | — | Kits needed before the neighbour check runs |
| `qc_coverage_min_pct` | integer | 80 | ✅ | — | — | % of expected readings needed for a windowed feature or aggregate value |
| `late_window_min` | integer | 180 | ✅ | — | — | Late readings up to this age trigger derived-feature recomputation ([05 §5.5.3](05-data-pipeline.md)) |

### 4.3.4 Climate normals and onboarding

| Key | Type | Default | D | S | K | Unit / rules |
|---|---|---|---|---|---|---|
| `normals_start_year` / `normals_end_year` | integer | 1991 / 2020 | ✅ | ✅ | — | start < end, ≥ 20 years apart |
| `normals_smoothing_days` | integer | 15 | ✅ | — | — | odd, 1–31 |
| `history_years` | integer | 30 | ✅ | ✅ | — | 20–40; minimum complete years required. The download itself covers `normals_start_year` to the last complete year ([05 §5.8.2](05-data-pipeline.md)) |
| `history_source` | string | `open_meteo_archive` | ✅ | — | — | `open_meteo_archive`, `era5` |
| `rain_intensity_percentile` | number | 99 | ✅ | ✅ | — | 90–99.9; percentile of **wet hours** only (D32, DD104) |
| `rain_wet_hour_min_mm` | number | 0.1 | ✅ | — | — | 0.1–1.0; mm; an hour with at least this much rain is "wet" |
| `rain_intensity_floor_mm` | number | 20 | ✅ | ✅ | — | 5–100; mm in 1 h; the computed rain-burst threshold is never lower |
| `heat_normal_offset_min_days` | integer | 28 | ✅ | — | — | 14–90; complete days of kit data before the normal offset is computed (D33, DD105) |
| `heat_normal_offset_enabled` | boolean | `true` | ✅ | ✅ | — | Add the kit's normal offset to the heatwave normal |
| `backtest_events_per_hazard` | integer | 10 | ✅ | — | — | 1–30 |

### 4.3.5 Forecast

| Key | Type | Default | D | S | K | Unit / rules |
|---|---|---|---|---|---|---|
| `forecast_interval_min` | integer | 15 | ✅ | — | — | 15 (fixed by AL-07; key exists for documentation) |
| `forecast_horizon_h` | integer | 72 | ✅ | — | — | 72 |
| `report_horizons_h` | integer list | `[1, 3, 6, 24, 72]` | ✅ | — | — | Horizons shown in reports |
| `external_fetch_interval_min` | integer | 60 | ✅ | — | — | 15–360 (DP-10) |
| `shadow_chronos_enabled` | boolean | `false` | ✅ | — | — | Run Chronos-Bolt alongside for comparison (phase 2) |
| `forecast_stale_after_runs` | integer | 4 | ✅ | — | — | Missed runs before the forecast counts as stale ([08](08-alert-engine.md)) |
| `forecast_start_offset_s` | integer | 120 | ✅ | — | — | s after the issue time; ≥ `ingest_grace_period_s` ([07 §7.1](07-forecast-worker.md)) |
| `forecast_timeout_s` | integer | 300 | ✅ | — | — | s; hard limit for one run |
| `nwp_max_age_h` | integer | 6 | ✅ | — | — | h; older Open-Meteo fetch → fallback (base) models ([07 §7.6](07-forecast-worker.md)) |
| `gap_interpolate_max_h` | integer | 3 | ✅ | — | — | h; longer gaps use Open-Meteo pseudo-observations ([07 §7.4](07-forecast-worker.md)) |
| `kit_skip_no_data_h` | integer | 24 | ✅ | — | — | h without valid data before a kit is skipped in a run |

### 4.3.6 Hazard thresholds (local-risk overrides at kit level, [04 §4.6](../requirements/04-configuration.md))

Colours follow requirement D27: the colour comes from the severity category; Watch/Warning/Live is certainty.

**High wind (gust, Beaufort)**

| Key | Type | Default | D | S | K | Unit / rules |
|---|---|---|---|---|---|---|
| `wind_yellow_kmh` | number | 39 | ✅ | ✅ | ✅ | km/h; yellow < orange < red |
| `wind_orange_kmh` | number | 50 | ✅ | ✅ | ✅ | km/h |
| `wind_red_kmh` | number | 62 | ✅ | ✅ | ✅ | km/h |
| `squall_rise_kmh` | number | 30 | ✅ | ✅ | ✅ | km/h rise of the 1-minute mean wind (`wind_avg_kmh`) over the baseline (D31, DD100) |
| `squall_min_wind_kmh` | number | 40 | ✅ | ✅ | ✅ | km/h 1-minute mean wind reached |
| `squall_sustain_s` | integer | 60 | ✅ | ✅ | — | s the 1-minute mean stays ≥ `squall_min_wind_kmh` |
| `squall_baseline_min` | integer | 10 | ✅ | — | — | min; baseline = mean of `wind_avg_kmh` over this window |
| `squall_level` | string | `orange` | ✅ | ✅ | ✅ | `yellow`, `orange`, `red` |
| `squall_precursor_pressure_hpa` | number | 1.0 | ✅ | ✅ | — | hPa rise within the precursor window |
| `squall_precursor_temp_drop_c` | number | 3 | ✅ | ✅ | — | °C drop within the window |
| `squall_precursor_rh_rise_pct` | number | 10 | ✅ | ✅ | — | % rise within the window |
| `squall_precursor_window_min` | integer | 15 | ✅ | — | — | min |

**Heavy rainfall**

| Key | Type | Default | D | S | K | Unit / rules |
|---|---|---|---|---|---|---|
| `rain_yellow_24h_mm` | number | 64.5 | ✅ | ✅ | ✅ | mm in 24 h ("heavy"); yellow < orange < red |
| `rain_orange_24h_mm` | number | 115.6 | ✅ | ✅ | ✅ | mm ("very heavy") |
| `rain_red_24h_mm` | number | 204.5 | ✅ | ✅ | ✅ | mm ("extremely heavy") |
| `rain_intensity_1h_mm` | number | computed; fallback 30 | ✅ | ✅ | ✅ | mm in 1 h; computed default = max(`rain_intensity_floor_mm`, wet-hour `rain_intensity_percentile` from onboarding) (D32, DD104) |
| `rain_intensity_level` | string | `orange` | ✅ | ✅ | ✅ | `yellow`, `orange`, `red` |

**Heatwave (region defaults)**

| Key | Type | Plains | Coastal | Hilly | D | S | K | Unit / rules |
|---|---|---|---|---|---|---|---|---|
| `heat_min_tmax_c` | number | 40 | 37 | 30 | ✅ | ✅ | ✅ | °C daily max needed before departure counts |
| `heat_departure_c` | number | 4.5 | 4.5 | 4.5 | ✅ | ✅ | ✅ | °C above normal → heatwave (🟠) |
| `heat_severe_departure_c` | number | 6.4 | 6.4 | 6.4 | ✅ | ✅ | ✅ | °C; *greater than* this → severe (🔴); > `heat_departure_c` |
| `heat_absolute_c` | number | 45 | 45 | 45 | ✅ | ✅ | ✅ | °C actual → heatwave regardless of normal |
| `heat_severe_absolute_c` | number | 47 | 47 | 47 | ✅ | ✅ | ✅ | °C; > `heat_absolute_c` |
| `heat_index_caution_c` | number | 32 | 32 | 32 | ✅ | ✅ | — | °C heat index for heat-stress advice (not an alert) |
| `heat_index_danger_c` | number | 41 | 41 | 41 | ✅ | ✅ | — | °C; > caution |

The plains/hilly upper bound (4.5–6.4) and the coastal "≥ 4.5" in [06 §6.1](../requirements/06-hazards-and-alerts.md) give the same result with these keys: departure in [4.5, 6.4] → heatwave, > 6.4 → severe.

### 4.3.7 Alert behaviour

| Key | Type | Default | D | S | K | Unit / rules |
|---|---|---|---|---|---|---|
| `alert_watch_on_prob` | number | 0.30 | ✅ | ✅ | — | 0–1; create Watch at or above (DD39: default + site only) |
| `alert_watch_off_prob` | number | 0.20 | ✅ | ✅ | — | Cancel Watch below; < `watch_on` |
| `alert_warning_on_prob` | number | 0.60 | ✅ | ✅ | — | Upgrade to Warning above; > `watch_on` |
| `alert_warning_off_prob` | number | 0.45 | ✅ | ✅ | — | Leave Warning below (AL-10); `watch_on` ≤ value < `warning_on` |
| `alert_downgrade_runs` | integer | 3 | ✅ | ✅ | — | 2–3 consecutive lower runs (AL-09) |
| `alert_far_event_h` | integer | 48 | ✅ | ✅ | — | h; events starting later need agreement (AL-11) |
| `alert_far_agreement_runs` | integer | 2 | ✅ | ✅ | — | 1–4 |
| `alert_window_shift_notify_h` | integer | 3 | ✅ | ✅ | — | 1–24; h; a window start moving more than this (or to another local day) sends an `updated` email (DD101) |
| `live_min_duration_wind_min` | integer | 10 | ✅ | ✅ | ✅ | min (AL-04); squalls use `squall_sustain_s` instead |
| `live_min_duration_heat_min` | integer | 30 | ✅ | ✅ | ✅ | min |
| `live_min_duration_rain_min` | integer | 0 | ✅ | ✅ | ✅ | min (accumulations are already sums) |
| `cleardown_wind_min` | integer | 30 | ✅ | ✅ | ✅ | min (AL-05) |
| `cleardown_rain_min` | integer | 60 | ✅ | ✅ | ✅ | min |
| `notify_cooldown_min` | integer | 60 | ✅ | ✅ | — | min between repeated emails for the same alert and recipient (AL-06); escalations are never delayed ([08 §8.11](08-alert-engine.md)) |
| `live_max_age_min` | integer | 15 | ✅ | — | — | min; older (late) readings cannot open or upgrade live alerts |
| `live_offline_hold_min` | integer | 60 | ✅ | ✅ | — | min without data before a per-zone live alert is cleared ("no data") |
| `live_takeover_hold_h` | integer | 6 | ✅ | ✅ | — | h; while a Live alert is open, no same-colour forecast alert for episodes starting sooner (D29). Heatwave: no same-or-lower-colour forecast alert at all while the Live heatwave is open (DD114) |
| `suppression_max_h` | integer | 24 | ✅ | ✅ | — | h (AL-15) |
| `combine_heatwave` | string | `median` | ✅ | ✅ | — | `median`, `worst`, `majority`, `two_kit_agreement` (AL-14) |
| `combine_heavy_rain` | string | `worst` | ✅ | ✅ | — | same values |
| `combine_high_wind` | string | `worst` | ✅ | ✅ | — | same values; wind also keeps per-zone alerts |
| `advice_heatwave` | string | generic text | ✅ | ✅ | ✅ | ≤ 500 characters; zone-specific advice at kit level (AL-17) |
| `advice_heavy_rain` | string | generic text | ✅ | ✅ | ✅ | |
| `advice_high_wind` | string | generic text | ✅ | ✅ | ✅ | e.g. "Stop outdoor games and move everyone indoors." |

There is no heatwave clear-down key: a Live heatwave is downgraded or cleared only at the end of a local day on which its level was not reached (D35, DD106).

### 4.3.8 Notifications

| Key | Type | Default | D | S | K | Unit / rules |
|---|---|---|---|---|---|---|
| `email_from_name` | string | `Site Weather Alerts` | ✅ | ✅ | — | Display name; the address is `SMTP_FROM` in `.env` |
| `email_max_attempts` | integer | 6 | ✅ | — | — | 1–20 (WEB-44) |
| `email_retry_base_s` | integer | 30 | ✅ | — | — | s; exponential backoff base |
| `email_skip_superseded` | boolean | `true` | ✅ | — | — | Skip unsent emails replaced by a newer change of the same alert |
| `notify_maintenance` | boolean | `true` | ✅ | ✅ | — | Send maintenance notices to operators (DP-26) |

Recipient lists: tables `recipient`, `recipient_hazard`, `recipient_zone` (D24, WEB-41). Personal preferences: `user_alert_preference` (WEB-08). SMTP host and credentials: `.env` (NFR-08).

### 4.3.9 Security, limits and retention (default only, DD40)

Operational settings for the installation; they can be changed only by editing `defaults.yaml` (or a local `config/overrides.yaml`, git-ignored) and restarting, never from the UI.

| Key | Type | Default | Unit / rules |
|---|---|---|---|
| `session_hours` | integer | 8 | h (WEB-06) |
| `login_lockout_attempts` / `login_lockout_min` | integer | 5 / 15 | (WEB-06) |
| `password_min_length` | integer | 10 | |
| `invite_valid_h` / `reset_valid_min` | integer | 48 / 60 | (WEB-02) |
| `rate_user_per_min` / `rate_login_per_ip_min` / `rate_reset_per_ip_h` | integer | 120 / 10 / 5 | (NFR-03) |
| `command_wait_s` | integer | 3 | ([02 §2.5](02-api.md)) |
| `retention_forecast_days` | integer | 400 | ([03 §3.14](03-database-schema.md)) |
| `retention_derived_days` | integer | 180 | |
| `retention_qc_flag_days` | integer | 365 | |
| `retention_rejected_days` | integer | 30 | |

## 4.4 Validation (CFG-02, CFG-03)

Every save (UI, API, YAML import) runs the same validator, in this order; all problems are reported together ([02 §2.3](02-api.md)):

| Step | Check | Error code |
|---|---|---|
| 1 | Key exists in the catalogue | `UNKNOWN_KEY` |
| 2 | Level allowed for the key | `OVERRIDE_NOT_ALLOWED` |
| 3 | Type and allowed values | `TYPE`, `OUT_OF_RANGE` |
| 4 | Required keys present at that level (site: `site_name`, `lat`, `lon`, `elevation_m`, `region_type`; kit: `kit_zone`, `lat`, `lon`, `exposure`) | `REQUIRED` |
| 5 | Coordinates valid; kit within `site_radius_km` of the site centre (great-circle distance) | `INVALID_COORDINATES`, `KIT_OUTSIDE_SITE` |
| 6 | Unique `kit_id` (table), unique `kit_zone` among enabled kits | `DUPLICATE_KIT_ID`, `DUPLICATE_ZONE` |
| 7 | **Cross-key rules on the effective values of every affected kit** (below) | `THRESHOLD_ORDER`, `RULE_VIOLATION` |

Step 7 is why a **site** save is validated against **every kit**: a site that sets `wind_yellow_kmh: 55` breaks a kit that has `wind_orange_kmh: 45`, even though the site record alone looks fine.

Cross-key rules:

| Group | Rule |
|---|---|
| Wind levels | `wind_yellow_kmh` < `wind_orange_kmh` < `wind_red_kmh` |
| Rain levels | `rain_yellow_24h_mm` < `rain_orange_24h_mm` < `rain_red_24h_mm` |
| Heat | `heat_departure_c` < `heat_severe_departure_c`; `heat_absolute_c` < `heat_severe_absolute_c`; `heat_index_caution_c` < `heat_index_danger_c` |
| Probabilities | `watch_off` < `watch_on` ≤ `warning_off` < `warning_on` |
| QC ranges | each `*_min` < `*_max` |
| Timing | `kit_offline_timeout_s` ≥ 2 × `sampling_interval_s` |
| Normals | `normals_end_year − normals_start_year` ≥ 19 |

**Warnings** (saved anyway, shown to the admin): kit elevation differs from the site by more than 200 m; calibration offset above half its range; a kit threshold *higher* than the site's (local risk normally lowers thresholds); `site_radius_km` change that leaves a kit near the edge.

At start-up every process validates the current configuration against the (possibly new) `defaults.yaml`. If it is invalid, the process logs the problem, keeps running with the last valid resolution, and `/system/status` shows a configuration warning to admins.

## 4.5 When a change takes effect (CFG-05, AL-16)

| Keys | Takes effect | Notes |
|---|---|---|
| Site identity, `elevation_m`, calibration, sensors, `rain_mm_per_tip`, QC | Next reading in `ingest` | Older clean rows keep the kit and site config versions they were made with (DD123) |
| `lat`, `lon`, `elevation_m` (site), `region_type`, `normals_*`, `history_*`, `rain_intensity_percentile`, `rain_wet_hour_min_mm`, `rain_intensity_floor_mm` | New onboarding run | Old normals remain until it completes ([01 §1.4.5](01-architecture.md)) |
| Hazard thresholds, alert behaviour, combination rules | Forecast path: next forecast run. Live path: next reading | `alerts` writes a `threshold_changed` change on every open alert whose effective threshold changed (AL-16) |
| Advice texts | Next email of each alert | Operator advice on an alert (`advice_override`) takes priority |
| Notifications | Next email | |
| Default-only keys (§4.3.9) | After restart | |

## 4.6 YAML import and export (DD41)

The format of [requirements 04 §4.7](../requirements/04-configuration.md), extended with recipients:

```yaml
site:
  site_id: abc
  site_name: "ABC College"
  lat: 13.08
  lon: 80.27
  elevation_m: 6
  timezone: Asia/Kolkata
  region_type: coastal
  wind_red_kmh: 58

kits:
  - kit_id: KIT-01
    kit_zone: "Main Block Rooftop"
    lat: 13.081
    lon: 80.271
    elevation_m: 30
    mount_height_m: 3
    exposure: rooftop
    cal_temp_offset_c: -0.5
  - kit_id: KIT-02
    kit_zone: "Sports Ground"
    lat: 13.079
    lon: 80.269
    exposure: open_ground
    wind_orange_kmh: 35
    wind_red_kmh: 45
    advice_high_wind: "Stop outdoor games and move everyone indoors."

recipients:
  - email: all@abc.edu
    label: "Site mailing list"
    min_level: yellow
    hazards: [heatwave, heavy_rain, high_wind]
  - email: sports@abc.edu
    label: "Sports department"
    min_level: yellow
    hazards: [high_wind]
    zones: [KIT-02]
```

| Rule | Detail |
|---|---|
| Endpoints | `POST /config/import` (admin, YAML body, `?dry_run=true` to validate only, `reason` required) and `GET /config/export` (`?effective=true` adds resolved values with sources) ([02 §2.6.8](02-api.md)) |
| Validation | Exactly the same validator as UI saves (§4.4), run on the whole file before anything is stored |
| Atomic | All or nothing in one transaction; each changed scope gets a new version; unchanged scopes are not touched |
| Missing kits | Kits not in the file are left unchanged (never deleted; retire with `kit_enabled: false`) |
| Recipients | Matched by e-mail; listed ones are created or updated, unlisted ones are left unchanged unless `replace_recipients: true` |
| First run | If no site exists, import creates it (`site_id` from the file) and starts onboarding; `start.ps1 -Seed config/example-site.yaml` calls the same import for the demo |
| Audit | One audit entry per changed scope, with the import's `reason` |
| Secrets | The file never contains credentials (MQTT and SMTP stay in `.env`) |

## 4.7 `defaults.yaml` shape

```yaml
wind_orange_kmh:
  type: number
  default: 50
  levels: [default, site, kit]
  unit: km/h
  rules: { min: 10, max: 200, order: wind_levels }
  description: Gust at or above which the level is Orange (Beaufort 7).

heat_min_tmax_c:
  type: number
  region_defaults: { plains: 40, coastal: 37, hilly: 30 }
  levels: [default, site, kit]
  unit: °C
  rules: { min: 20, max: 50 }
  description: Daily maximum needed before the departure from normal counts.

rain_intensity_1h_mm:
  type: number
  default: 30
  computed_from: onboarding.rain_1h_wet_percentile   # max(floor, wet-hour percentile), DD104
  levels: [default, site, kit]
  unit: mm
  rules: { min: 5, max: 200 }
  description: Hourly rain that raises the intensity alert.
```

`start.ps1` loads this file into `config_key` and `config_key_region_default` ([03 §3.5.2](03-database-schema.md)) right after the migrations and before any process starts (`python -m ews.common.config sync`, DD110), so every process sees the current catalogue, the API can serve `GET /config/schema` and foreign keys reject unknown keys. A key removed from the file is marked `deprecated`, never deleted, because older config versions still reference it.

## 4.8 Requirement coverage

| Requirement | Where |
|---|---|
| CFG-01 | §4.2 |
| CFG-02 | Allowed-level columns in §4.3, step 2 of §4.4 |
| CFG-03 | §4.4 |
| CFG-04 | Versioned saves ([03 §3.5.2](03-database-schema.md)), import per scope |
| CFG-05, AL-16 | §4.5 |
| CFG-06 | §4.2 sources, `GET /config/effective` |
| CFG-07 | Onboarding triggers in §4.5 and §4.6 |
| 04 §4.4 override scope | §4.3 (timezone S, region type S, normals S, elevation S/K, calibration K, thresholds S/K, sensors K, sampling S/K) |
| 04 §4.6 local risk | Kit-level thresholds and advice (§4.3.6–4.3.7), `recipient_zone` |
| AL-14 | `combine_*` keys |
| D27 | §4.3.6 colour keys |
| NFR-07, NFR-08 | Configuration only; secrets in `.env` |
