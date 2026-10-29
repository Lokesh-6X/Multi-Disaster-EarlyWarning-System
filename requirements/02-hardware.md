# 2. Sensor Kit Interface (hardware out of scope)

The sensor kit (hardware, wiring, mounting, firmware) is **built separately and is out of scope for this project**. This document defines only what the software expects from a kit: the sensors it reports, the assumptions the software relies on, and the MQTT message contract. Until a real kit is connected, the kit simulator ([08 §8.2](08-non-functional-and-testing.md)) produces the same messages.

## 2.1 Expected sensors

| Sensor | Measures | Used by the software for |
|---|---|---|
| BME280 | Temperature (±1 °C), humidity (±3 %), pressure (±1 hPa abs, ~±0.12 hPa relative) | Primary temperature / humidity / pressure |
| DHT11 | Temperature (±2 °C), humidity (±5 %) | Backup and cross-check (DP-23) |
| Anemometer | Wind speed | Wind average and gusts |
| DFRobot tipping-bucket rain gauge | Rainfall, 0.28 mm per tip | Rainfall amount and intensity |
| Wind vane (optional) | Wind direction | Squall detection, if present |

## 2.2 Kit assumptions

The software relies on these; they are the responsibility of the hardware builders. Breaking them degrades data quality, which the QC checks ([03 §3.3](03-data-pipeline.md)) are designed to catch.

| ID | Assumption | Priority |
|---|---|---|
| HW-01 | The pressure/humidity sensor is a real BME280 (chip ID `0x60`), not a BMP280 (`0x58`, no humidity). | M |
| HW-02 | Temperature/humidity sensors are in a ventilated radiation shield. | M |
| HW-03 | The anemometer is mounted high and clear of obstructions. | M |
| HW-04 | The kit samples wind at ≥ 1 Hz and reports average speed and gust (max 3-second average) per interval. | M |
| HW-05 | The kit reports the **number of rain tips** per interval, not a converted amount. | M |
| HW-06 | The kit clock is synced via NTP; timestamps are UTC. | M |
| HW-07 | The kit publishes one aggregated message per minute (configurable) over MQTT. | M |
| HW-08 | Every message includes `kit_id`, measurement timestamp, firmware version and a sequence number. | M |
| HW-09 | No offline buffering: readings taken while the kit is disconnected are lost; the kit resumes publishing when the connection returns. | M |
| HW-10 | The kit reports basic health (Wi-Fi signal, uptime) inside each reading message; there is no separate health message. | S |
| HW-11 | Wind direction is optional; the software works without it and uses it for squall detection when present. | C |
| HW-12 | On connecting, the kit publishes `online` (retained) to its status topic and registers an MQTT **last will** of `offline` (retained) on the same topic, so the broker announces an unexpected disconnect immediately. | M |

## 2.3 Calibration

Side-by-side calibration of kits is done by the hardware builders before installation. The software only stores the resulting offsets in kit config ([04](04-configuration.md)). After installation, differences between kits are treated as **real** local variation and are not configured away.

## 2.4 MQTT message contract (final)

The software validates every incoming message against this contract; the simulator and the real kit must both follow it. Fields marked optional may be omitted or `null`.

```json
{
  "kit_id": "KIT-01",
  "ts": "2026-11-02T09:31:00Z",
  "seq": 18234,
  "fw": "1.0.0",
  "bme_temp_c": 31.42,
  "bme_rh_pct": 64.1,
  "bme_pressure_hpa": 1008.63,
  "dht_temp_c": 32.0,
  "dht_rh_pct": 61,
  "wind_avg_kmh": 12.4,
  "wind_gust_kmh": 21.7,
  "wind_dir_deg": null,
  "rain_tips": 3,
  "rssi_dbm": -67,
  "uptime_s": 86400
}
```

Topics:

| Topic | Sent by | Payload | When |
|---|---|---|---|
| `sites/{site_id}/kits/{kit_id}/readings` | Kit | Reading message above | Every minute |
| `sites/{site_id}/kits/{kit_id}/status` | Kit / broker | `online` or `offline` (retained) | Kit publishes `online` on connect; broker publishes `offline` (last will) if the kit drops off unexpectedly |

Optional fields: `dht_temp_c`, `dht_rh_pct`, `wind_dir_deg`, `rssi_dbm`, `uptime_s`. Any change to this contract must be agreed with the hardware builders.
