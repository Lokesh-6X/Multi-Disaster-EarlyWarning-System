# 3. Data Pipeline

## 3.1 Flow

```
Kit ──MQTT──► Broker ──► Ingestion service ──► Database (raw readings)
                              │
                              ├─ validation, dedup, calibration, unit conversion
                              └─ notify the backend API, which pushes the new reading to dashboards (WebSocket)

Scheduled jobs:
  • Resample raw → 15-min and hourly series
  • Fetch Open-Meteo forecast for the site (external inputs)
  • Forecast worker (see 05 / 06)
```

## 3.2 Ingestion requirements

| ID | Requirement | Priority |
|---|---|---|
| DP-01 | Every reading shall be stored with both the **kit timestamp** and the **server receive timestamp**. A large difference shall flag the kit's clock. | M |
| DP-02 | `(kit_id, kit timestamp)` shall be a unique key; duplicate messages shall be ignored. | M |
| DP-03 | Raw values shall be kept unchanged; calibrated and derived values shall be stored separately. | M |
| DP-04 | Rain tips shall be converted to mm in the server (tips × 0.28 mm, configurable per gauge). | M |
| DP-05 | Station pressure shall be converted to sea-level pressure using the kit's elevation from config. | M |
| DP-06 | Derived features shall be computed: pressure tendency (1 h, 3 h), rain totals (1 h, 3 h, 24 h), rain rate, heat index, gust trends (15/30/60 min), temperature change (30 min). | M |
| DP-07 | Data shall be resampled to 15-minute and hourly series for the model. | M |
| DP-08 | Messages delayed by the network shall be accepted; windows are processed after a grace period (default 2 min) and may be recomputed if a delayed message arrives. Kits do not resend readings after an outage (HW-09). | S |
| DP-09 | A kit shall be marked offline immediately when its status topic reports `offline` (MQTT last will, HW-12), or after no data for a configurable timeout (default 5 min) as a backup. | M |
| DP-10 | The external forecast (Open-Meteo) for the site shall be fetched on a schedule and stored with its issue time. | M |
| DP-11 | All data shall carry `kit_id` from day one, even with only one kit, so more kits need no redesign. | M |
| DP-12 | Every incoming message shall be validated against the MQTT contract ([02 §2.4](02-hardware.md)); messages that do not match are rejected and logged with the reason. | M |
| DP-13 | Every kit status change (`online` / `offline`) shall be stored with its time, giving an outage history per kit. | M |

## 3.3 Data quality checks

Each reading is classified as **valid**, **suspicious** (used but flagged) or **faulty** (excluded).

| ID | Check | Priority |
|---|---|---|
| DP-20 | **Range check** — default valid ranges: temperature −10 to 55 °C, humidity 0–100 %, pressure 850–1100 hPa, wind 0–200 km/h. | M |
| DP-21 | **Spike check** — e.g. temperature change > 5 °C in 1 min is faulty. | M |
| DP-22 | **Stuck check** — the same value for an unrealistically long period is suspicious. | M |
| DP-23 | **Cross-sensor check** — BME280 vs DHT11 temperature difference > 4 °C flags the kit. | S |
| DP-24 | **Neighbour check** (multi-kit) — compare with the median of other kits; exceeding the expected spread is suspicious. Expected spread per variable is learned from history once available. Pressure (after elevation correction) should almost match across kits and is the best fault detector. | S |
| DP-25 | **External check** — compare with the current Open-Meteo value for the site. | S |
| DP-26 | Faulty readings and kit faults shall be visible in the kit-health view and trigger a maintenance notice to operators. | S |

## 3.4 Multiple kits: conflicts and resolution

Disagreement between kits is expected and is useful information. The system must separate real variation from faults.

| Conflict | Resolution |
|---|---|
| Different readings | Quality checks above (self → neighbour → external) |
| Different alert levels | Per-zone alerts plus a site combination rule per hazard ([06](06-hazards-and-alerts.md)) |
| Different forecasts | Per-zone forecasts; site summary shows range or worst case; later a multi-kit model |
| Clock skew / late data | NTP, UTC, two timestamps, grace period |
| Duplicates | Unique key `(kit_id, ts)` |
| Invalid config | Validation on save ([04](04-configuration.md)) |
