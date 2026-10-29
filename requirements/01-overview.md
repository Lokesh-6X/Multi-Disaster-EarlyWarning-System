# 1. Overview

## 1.1 Problem

Weather hazards at a site — heat stress, sudden heavy rain and waterlogging, strong gusts from thunderstorm squalls — cause injuries and damage, and regional forecasts are too coarse to warn about conditions at a specific site. The site needs local measurements, short-term local forecasts and clear alerts.

## 1.2 Goal

Build a system that:

1. Measures local weather with one or more sensor kits placed around a region.
2. Forecasts temperature, humidity, wind gusts, rainfall and pressure for the next 72 hours.
3. Converts forecasts into **heatwave**, **heavy rainfall** and **high-speed wind** alerts, using IMD and Beaufort standards adjusted to the local climate.
4. Shows live data, forecasts and alerts on a real-time web dashboard for operators and admins (login required), with tools for managing alerts and configuration, and sends email alerts to people at the site.
5. Works for **any location in India** by changing configuration only (D37). Hazard rules (IMD), the 08:30 IST rain day and the training locations are Indian; other countries are a future enhancement (F3).

## 1.3 Scope

| In scope | Out of scope |
|---|---|
| Heatwave, heavy rainfall, high-speed wind | Cyclone prediction (synoptic scale; cannot be done with local kits) |
| Ingesting data from one kit now; design supports many | Sensor kit hardware and firmware (built separately; interface in [02](02-hardware.md)) |
| | Earthquake, flood-routing, landslide |
| Forecast horizons from 1 h to 72 h | Long-range / seasonal forecasts |
| Live alerts from current readings | Production cloud deployment (runs locally for the project) |
| Login-only dashboard (operators/admins) | Public (unauthenticated) dashboard, kiosk/TV view |
| Operator and admin accounts (invited) | Viewer accounts / self sign-up |
| Email alerts (the only notification channel) | Mobile apps |
| | SMS and Telegram alerts (future enhancement, [09 §9.2](09-decisions-and-open-questions.md)) |

## 1.4 Users

| User | Login | Purpose |
|---|---|---|
| Operator (safety officer, security) | Yes | Acknowledge alerts, add notes, manual overrides |
| Admin (project team, IT) | Yes | Configuration, users, audit log, model reports |

## 1.5 System at a glance

```
Kit (external) ──MQTT──► Ingestion ──► Database ◄── Open-Meteo (external forecast)
                                                 │
                          Forecast worker (every 15 min): TFT → hazard layer → alert engine
                                                 │
                       Backend API (REST + WebSocket) ──► Web dashboard / Email
```

## 1.6 Glossary

| Term | Meaning |
|---|---|
| Kit | One hardware unit with sensors, placed at one spot |
| Site | The region being monitored (e.g. a college, tech park or industrial area) |
| Zone | Named area around a kit (e.g. "Sports Ground") |
| Gust | Maximum 3-second average wind speed within an interval |
| Pressure tendency | Change in pressure over 1 h / 3 h |
| Normal | Climatological average for a date at the site (1991–2020) |
| Persistence | Baseline forecast: "the future equals now" |
| TFT | Temporal Fusion Transformer, the main forecasting model |
| Watch | Hazard is possible (moderate probability) |
| Warning | Hazard is likely (high probability) |
| Live alert | Hazard is happening now (measured) |
| Lead time | How long before an event the first alert was issued |
| Local risk | Extra danger at a zone due to exposure and vulnerability (Risk = Hazard × Exposure × Vulnerability) |
