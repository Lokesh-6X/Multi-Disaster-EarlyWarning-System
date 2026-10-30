# 4. Configuration

## 4.1 Layers

```
System defaults  → the rulebook shipped with the software (IMD, Beaufort, QC limits)
   ↓ overridden by
Site config      → location-specific values for the monitored region
   ↓ overridden by
Kit config       → per-device values
```

Each setting is resolved individually: **kit → site → system default**; the most specific level that defines it wins.

## 4.2 Requirements

| ID | Requirement | Priority |
|---|---|---|
| CFG-01 | Settings shall resolve per key in the order kit → site → system default. | M |
| CFG-02 | Each setting shall declare which levels may override it; disallowed overrides shall be rejected on save with a clear error (e.g. "`timezone` cannot be set on KIT-02"). | M |
| CFG-03 | Configuration shall be validated on save: unique `kit_id`, threshold ordering (Yellow < Orange < Red), valid coordinates, kit inside the site area, required fields present. | M |
| CFG-04 | Every config record shall have a version number; saves based on an outdated version shall be rejected (optimistic locking). | M |
| CFG-05 | Config changes shall take effect from the next forecast run and be written to the audit log. | M |
| CFG-06 | The system shall show the **effective (resolved) value** of each setting for each kit and where it came from (kit / site / default). | S |
| CFG-07 | Adding a new site shall trigger the onboarding process (§4.5). | M |

## 4.3 What each level holds

**System defaults**
- Hazard thresholds (IMD heatwave rules, IMD rainfall categories, Beaufort wind levels, squall rule)
- Alert behaviour: minimum duration, clear-down delay, notification cooldown, Watch/Warning probabilities, upgrade/downgrade rules
- Forecast horizons (1, 3, 6, 24, 72 h), forecast refresh interval (15 min)
- Data processing: sampling, gust definition, QC ranges, spike limits, offline timeout
- Climate normals: baseline 1991–2020, data source, 15-day smoothing window
- Units, default timezone (Asia/Kolkata), notification channels

**Site config**
- Name, latitude, longitude, elevation, timezone
- `region_type`: `plains` | `coastal` | `hilly` (changes heatwave rules)
- Site combination rule per hazard (worst-kit, median, majority, two-kit agreement)
- Notification contacts, alert email recipient lists (address, hazards, minimum level)
- Optional overrides of any default threshold

**Kit config**
- `kit_id`, zone name, latitude, longitude
- Elevation, mount height (things the kit cannot measure itself)
- Exposure type: rooftop / open ground / between buildings / under trees (used for interpretation, not to alter readings)
- Calibration offsets (temperature, humidity, pressure) from the side-by-side calibration
- Enabled/disabled sensors (e.g. broken rain gauge)
- Sampling interval, rain gauge mm-per-tip
- Local-risk overrides (see §4.6)

**Rule:** configure what the kit cannot measure. Never configure a correction for real local conditions (e.g. "this spot is cooler") — that is data.

## 4.4 Override scope

| Setting | Default | Site | Kit |
|---|---|---|---|
| Timezone | ✅ | ✅ | ❌ |
| Region type | — | ✅ | ❌ |
| Climate normals period | ✅ | ✅ | ❌ |
| Notification contacts | ✅ | ✅ | ❌ |
| Elevation | ✅ | ✅ | ✅ |
| Calibration offsets | 0 (no correction) | ❌ | ✅ |
| Alert thresholds | ✅ | ✅ | ✅ |
| Enabled sensors | ✅ | ❌ | ✅ |
| Sampling interval | ✅ | ✅ | ✅ |

## 4.5 Site onboarding (automatic)

When a site is configured:

1. Read coordinates, elevation, region type.
2. Download 20–30 years of hourly history for the coordinates (Open-Meteo Historical / ERA5).
3. Compute local normals: daily normal max temperature (1991–2020, 15-day smoothing), rainfall percentiles (the rain-burst threshold uses wet hours only, never below 20 mm/h, D32) and gust percentiles. After 4–8 weeks of kit data, a normal offset per kit is added to the normal maximum (D33).
4. Generate hazard labels from history using the thresholds.
5. Find the 10 most extreme past heat, rain and wind events for back-testing.
6. Run the global model on the site (no retraining needed); optionally fine-tune.
7. Produce a validation report, shown on the model-reports page: "would the system have warned before these events?"

## 4.6 Local risk

Same weather, different danger: **Risk = Hazard × Exposure × Vulnerability**. The kit measures the hazard; local-risk settings describe exposure and vulnerability for a zone (sports ground, construction area, low-lying parking, tin roofs, old trees). They may:

- lower alert thresholds for that kit,
- attach zone-specific advice text ("Stop outdoor games and move indoors"),
- route alerts to specific contacts (e.g. sports department).

They never change measurements. Optional with a single kit.

## 4.7 Example

In the final key names ([design/04 §4.6](../design/04-configuration.md); elevation is the sensor's height above sea level):

```yaml
site:
  site_id: abc
  site_name: "ABC College"
  lat: 13.08
  lon: 80.27
  elevation_m: 6
  timezone: Asia/Kolkata
  region_type: coastal
  wind_red_kmh: 58                 # site override of a default threshold

kits:
  - kit_id: KIT-01
    kit_zone: "Main Block Rooftop"
    lat: 13.081
    lon: 80.271
    elevation_m: 30
    mount_height_m: 3
    exposure: rooftop
    cal_temp_offset_c: -0.5        # from side-by-side calibration
  - kit_id: KIT-02
    kit_zone: "Sports Ground"
    lat: 13.079
    lon: 80.269
    exposure: open_ground
    wind_yellow_kmh: 28            # local risk: lower thresholds (yellow < orange < red) …
    wind_orange_kmh: 35
    wind_red_kmh: 45
    advice_high_wind: "Stop outdoor games and move everyone indoors."   # … and zone advice

recipients:
  - email: sports@abc.edu          # local-risk routing to specific contacts
    label: "Sports department"
    hazards: [high_wind]
    zones: [KIT-02]
```
