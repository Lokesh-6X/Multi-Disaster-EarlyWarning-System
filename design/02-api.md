# 2. API

The contract between the React frontend and the `api` process ([01](01-architecture.md)): conventions, authentication, error format, every REST endpoint, the WebSocket stream and the role matrix. This is the "API endpoint list" required before backend work starts (requirements D22).

Decisions referenced: DD14–DD20 in [decisions.md](decisions.md).

Field names and enum values for readings, forecasts and alerts are fixed here. Later documents ([05](05-data-pipeline.md), [07](07-forecast-worker.md), [08](08-alert-engine.md)) may refine them; any change there must be applied to this document too.

## 2.1 Conventions

| Topic | Rule |
|---|---|
| Base path | `/api/v1` (DD18). All paths below are relative to it. The built frontend is served from `/` |
| Format | JSON, UTF-8. Request bodies `application/json` except CSV upload (§2.6.3) |
| Timestamps | ISO 8601 in UTC with `Z`, e.g. `2026-11-02T09:31:00Z` (NFR-06). The site timezone is returned by `GET /site`; the frontend converts for display |
| Time ranges | `from` (inclusive) and `to` (exclusive) query parameters |
| Units | In the field name, as in the MQTT contract: `_c`, `_pct`, `_hpa`, `_kmh`, `_mm`, `_mmh`, `_deg` |
| IDs | Kits are identified by their `kit_id` (e.g. `KIT-01`). All other IDs (users, alerts, runs, commands, emails, audit entries) are opaque strings; clients must not parse them (UUIDv7 or integers, see [03 §3.1](03-database-schema.md)) |
| Enum values | Lower-case snake case: `operator`, `heavy_rain`, `orange`, `warning` |
| Absent values | `null` (e.g. `wind_dir_deg` when the kit has no wind vane) |
| Lists (DD19) | Cursor pagination: `?limit=` (default 100, max 1000) and `?cursor=`; response `{"items": [...], "next_cursor": "..." }`, `next_cursor` is `null` on the last page. Newest first unless stated. Cursors are opaque (encoded time + ID) and stay stable while new rows arrive |
| Time series | Readings and forecasts are range-bounded instead of paginated; too large a range returns `422 RANGE_TOO_LARGE` (§2.6.4) |
| Writes | Need the CSRF header (§2.2). Every write is audited (WEB-25) |
| Reason (DD20) | Writes that change configuration, users or alerts take a `reason` string. It is **required** where marked "reason" in the tables below and optional elsewhere; it becomes the "why" in the audit log |
| Caching | Forecast endpoints return `ETag: "run-<run_id>"` and honour `If-None-Match` (`304`); the server caches the response per forecast run (NFR-03). Runs are immutable, so `GET /forecast/runs/{run_id}` and its `/probabilities` are sent with `Cache-Control: private, max-age=31536000, immutable` (DD30) |
| Rate limits | Per user: 120 requests/min (all endpoints). Per IP: 10 login attempts/min, 5 password-reset requests/hour. Exceeding returns `429 RATE_LIMITED` with `Retry-After` (NFR-03). Values come from config ([04](04-configuration.md)) |

## 2.2 Authentication (DD14)

### 2.2.1 Sessions

| Item | Rule |
|---|---|
| Session cookie | `ews_session`: random 256-bit ID; the server stores only its hash with the user, creation time, expiry and IP. `HttpOnly`, `SameSite=Strict`, `Path=/`; `Secure` when served over HTTPS |
| Expiry | Absolute 8 h from login (WEB-06, configurable). An expired session returns `401 SESSION_EXPIRED` |
| CSRF | Login returns a `csrf_token` (also readable again from `GET /auth/me`). The frontend sends it as `X-CSRF-Token` on every `POST`, `PUT`, `PATCH`, `DELETE`; a missing or wrong token returns `403 CSRF_FAILED` |
| WebSocket | Authenticated by the same cookie during the handshake; the `Origin` header must equal `APP_BASE_URL` or one of `DEV_ORIGINS` (empty except with `start.ps1 -Dev`, which sets `http://localhost:5173`, DD122) |
| Ending sessions | Logout ends the current session. Deactivation (WEB-04), a role change and a password change end **all** of that user's sessions; their WebSockets are closed with code `4401` |
| Passwords | Argon2id hashes (WEB-06); minimum length 10 |
| Lockout | 5 failed logins in a row lock the account for 15 min (WEB-06); a locked login returns `423 ACCOUNT_LOCKED` with `locked_until` |
| Unknown e-mail on login | Same response as a wrong password (`401 INVALID_CREDENTIALS`) |

### 2.2.2 Endpoints reachable without login

Exactly the ones allowed by [07 §7.1](../requirements/07-web-application.md): first-run setup, login, invite acceptance, password reset (§2.6.1). Everything else returns `401 UNAUTHENTICATED` without a valid session (WEB-21, TST-16). The static frontend files (HTML, JS, CSS) are served without login so the login page can load; they contain no data.

### 2.2.3 Token links (invite, password reset)

| Link | Lifetime | Rules |
|---|---|---|
| Invite `…/invite/{token}` | 48 h (WEB-02, configurable) | One-time; stored as a hash; re-sending makes the old link invalid |
| Reset `…/reset/{token}` | 1 h | One-time; stored as a hash; ends all sessions of the user when used |

Both are sent by email through the outbox. The invite response also returns the link to the admin, and the mailer prints links to the server console if sending fails (WEB-03).

## 2.3 Error format (DD15)

Every error is `application/problem+json` (RFC 9457) with a stable `code` that the frontend switches on:

```json
{
  "type": "about:blank",
  "title": "Config version conflict",
  "status": 409,
  "code": "CONFIG_VERSION_CONFLICT",
  "detail": "Someone else changed this config. Reload.",
  "current_version": 8
}
```

Validation errors list every problem with a field path:

```json
{
  "type": "about:blank",
  "title": "Validation failed",
  "status": 422,
  "code": "VALIDATION_FAILED",
  "detail": "2 problems in the submitted configuration.",
  "errors": [
    { "field": "values.timezone", "code": "OVERRIDE_NOT_ALLOWED", "message": "timezone cannot be set on KIT-02" },
    { "field": "values.wind_orange_kmh", "code": "THRESHOLD_ORDER", "message": "Yellow < Orange < Red is required (39 < 35 < 62)" }
  ]
}
```

### 2.3.1 Error codes

| Status | `code` | When |
|---|---|---|
| 400 | `BAD_REQUEST` | Malformed JSON, unknown query parameter |
| 401 | `UNAUTHENTICATED` | No valid session |
| 401 | `SESSION_EXPIRED` | Session older than 8 h |
| 401 | `INVALID_CREDENTIALS` | Wrong e-mail or password |
| 403 | `CSRF_FAILED` | Missing or wrong `X-CSRF-Token` |
| 403 | `FORBIDDEN` | Role not allowed (e.g. operator calls an admin endpoint) |
| 403 | `ACCOUNT_DEACTIVATED` | Login by a deactivated account |
| 403 | `CANNOT_CHANGE_OWN_ROLE` | Admin changes own role (WEB-05) |
| 403 | `CANNOT_DEACTIVATE_SELF` | Admin deactivates own account |
| 404 | `NOT_FOUND` | Unknown ID or `kit_id` |
| 404 | `FORECAST_NOT_AVAILABLE` | No forecast run yet (e.g. onboarding still running) |
| 409 | `SETUP_ALREADY_DONE` | First-run setup when users exist (WEB-01) |
| 409 | `SITE_NOT_CONFIGURED` | Kit or forecast request before the site exists |
| 409 | `SITE_ALREADY_EXISTS` | Creating the site a second time (one site per installation, D26) |
| 409 | `CONFIG_VERSION_CONFLICT` | `base_version` is not the current version (CFG-04, WEB-22) |
| 409 | `EMAIL_ALREADY_EXISTS` | Inviting an e-mail that already has an account |
| 409 | `LAST_ADMIN` | Demoting or deactivating the last active admin (WEB-05) |
| 409 | `ALREADY_ACKNOWLEDGED` | Second acknowledgement; includes `acknowledged_by`, `acknowledged_at` (WEB-23) |
| 409 | `ALERT_NOT_ACTIVE` | Action on a cancelled or cleared alert |
| 409 | `NOT_MANUAL_ALERT` | Manual clear of an automatic alert |
| 409 | `COMMAND_REJECTED` | The alert engine rejected the command; `detail` gives its reason |
| 409 | `ONBOARDING_RUNNING` | Re-run requested while onboarding runs |
| 409 | `EMAIL_NOT_RETRYABLE` | Retry of an email that is not in `failed` state |
| 410 | `INVITE_INVALID` | Invite link expired, used or replaced |
| 410 | `RESET_TOKEN_INVALID` | Reset link expired or used |
| 422 | `VALIDATION_FAILED` | Body or config validation failed; see `errors[]` |
| 422 | `RANGE_TOO_LARGE` | Time range above the limit for the resolution |
| 423 | `ACCOUNT_LOCKED` | Too many failed logins; includes `locked_until` |
| 429 | `RATE_LIMITED` | Rate limit exceeded; `Retry-After` header |
| 500 | `INTERNAL_ERROR` | Unexpected error (logged with a request ID, returned as `request_id`) |
| 503 | `SERVICE_UNAVAILABLE` | Database unreachable |

Field-level codes inside `errors[]`: `REQUIRED`, `TYPE`, `OUT_OF_RANGE`, `UNKNOWN_KEY`, `OVERRIDE_NOT_ALLOWED` (CFG-02), `THRESHOLD_ORDER`, `INVALID_COORDINATES`, `KIT_OUTSIDE_SITE`, `DUPLICATE_KIT_ID`, `DUPLICATE_ZONE`, `RULE_VIOLATION` (CFG-03, [04 §4.4](04-configuration.md)), `SITE_ID_IMMUTABLE`, `PASSWORD_TOO_SHORT`, `EXPIRY_INVALID`.

## 2.4 Roles

| Role value | Meaning in the tables below |
|---|---|
| `public` | No session needed (only §2.6.1) |
| `any` | `operator` or `admin` |
| `admin` | `admin` only |

## 2.5 Operator commands (DD16)

Suppress, end suppression, manual alert and manual clear go through the alert engine ([01 §1.2](01-architecture.md)):

1. `api` checks the role and body, inserts a command row, writes the audit entry and notifies `alerts`.
2. `api` waits up to **3 s** for the result.
3. Applied in time → `200` with the command and the updated alert. Rejected → `409 COMMAND_REJECTED`. Not finished in 3 s (e.g. `alerts` restarting) → `202` with the command in state `pending`; the result arrives as a WebSocket `alert.command_result` event and through `GET /alert-commands/{id}`.

```json
// 202 Accepted
{ "command": { "id": "c1f0…", "kind": "suppress", "status": "pending", "created_at": "2026-11-02T09:35:05Z" } }
```

```json
// 200 OK
{
  "command": { "id": "c1f0…", "kind": "suppress", "status": "applied", "applied_at": "2026-11-02T09:35:05Z" },
  "alert": { "id": "a7…", "status": "active", "suppression": { "by": "Priya", "reason": "Known construction crane test, safe", "expires_at": "2026-11-02T11:30:00Z", "overridden_at": null } }
}
```

Command states: `pending` → `applied` or `rejected`.

## 2.6 Endpoints

Columns: **Role** (§2.4); **Audit**: written to the audit log; **Reason**: `reason` required.

### 2.6.1 Setup and authentication

| Method | Path | Role | Audit | Purpose |
|---|---|---|---|---|
| GET | `/setup/status` | public | | `{"setup_required": true}` while no users exist |
| POST | `/setup` | public | ✅ | Create the first admin (WEB-01); `409 SETUP_ALREADY_DONE` afterwards; logs the admin in |
| POST | `/auth/login` | public | ✅ | E-mail + password → session cookie |
| POST | `/auth/logout` | any | ✅ | End the current session |
| GET | `/auth/me` | any | | Current user, role, CSRF token, session expiry |
| GET | `/auth/invites/{token}` | public | | Invite details for the acceptance page |
| POST | `/auth/invites/{token}/accept` | public | ✅ | Set password; account `invited` → `active`; logs in |
| POST | `/auth/password-reset` | public | ✅ | Request a reset link; always `202` (no account enumeration) |
| POST | `/auth/password-reset/{token}` | public | ✅ | Set a new password |

```json
// POST /auth/login
{ "email": "priya@abc.edu", "password": "••••••••••" }

// 200 OK  (Set-Cookie: ews_session=…; HttpOnly; SameSite=Strict)
{
  "user": { "id": "u1…", "name": "Priya", "email": "priya@abc.edu", "role": "operator", "state": "active" },
  "csrf_token": "b64…",
  "session_expires_at": "2026-11-02T17:31:00Z"
}
```

```json
// POST /setup
{ "name": "Admin", "email": "admin@abc.edu", "password": "••••••••••" }
```

### 2.6.2 Profile

| Method | Path | Role | Audit | Purpose |
|---|---|---|---|---|
| PATCH | `/me` | any | ✅ | Change own display name |
| PUT | `/me/password` | any | ✅ | Current + new password; ends other sessions |
| GET | `/me/email-preferences` | any | | Which alert emails I receive (WEB-08) |
| PUT | `/me/email-preferences` | any | ✅ | Update them |

```json
// PUT /me/email-preferences
{
  "enabled": true,
  "hazards": ["heatwave", "heavy_rain", "high_wind"],
  "min_level": "orange",
  "types": ["watch", "warning", "live"],
  "maintenance_notices": true
}
```

### 2.6.3 Users (admin)

| Method | Path | Role | Audit | Reason | Purpose |
|---|---|---|---|---|---|
| GET | `/users` | admin | | | List; filters `state`, `role`; cursor |
| POST | `/users/invites` | admin | ✅ | | Invite one user (WEB-02) |
| POST | `/users/invites/bulk` | admin | ✅ | | `text/csv` with `name,email,role`; per-row result (WEB-07, C) |
| POST | `/users/{id}/invite/resend` | admin | ✅ | | New invite link; the old one stops working |
| PATCH | `/users/{id}` | admin | ✅ | ✅ | Change `name` or `role` (WEB-05 rules) |
| POST | `/users/{id}/deactivate` | admin | ✅ | ✅ | `active`/`invited` → `deactivated`; ends sessions; cancels invite |
| POST | `/users/{id}/reactivate` | admin | ✅ | ✅ | `deactivated` → `active` (or `invited` if never activated, with a new link) |

```json
// POST /users/invites
{ "name": "Ravi", "email": "ravi@abc.edu", "role": "operator" }

// 201 Created
{
  "user": { "id": "u2…", "name": "Ravi", "email": "ravi@abc.edu", "role": "operator", "state": "invited",
            "invite_expires_at": "2026-11-04T09:00:00Z" },
  "invite_link": "http://localhost:8000/invite/Zk3…",
  "email_status": "queued"
}
```

User objects in lists also carry `last_login_at` and `invite_email_status` (`queued`, `sent`, `failed`) so the admin sees when an invite email failed (WEB-03).

### 2.6.4 Site, kits and live data

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/site` | any | Site summary: name, `site_id`, timezone, coordinates, region type, onboarding state, current site status per hazard, `latest_run_id` |
| GET | `/live` | any | Dashboard first load: latest clean reading and derived values per kit, kit status, data age, site status per hazard, active alert summary, `latest_run_id` |
| GET | `/kits` | any | Kits with zone, position, exposure, status, last reading time (for the map and selectors) |
| GET | `/kits/{kit_id}` | any | One kit (no calibration values; those are admin config) |
| GET | `/kits/{kit_id}/readings` | any | Time series; `from`, `to`, `resolution` = `raw`, `15m`, `1h`; optional `fields=`, `variant` = `clean` (default) or `raw`, and `format` = `rows` (default) or `columnar` (DD31, example in [13 §13.3.4](13-frontend-performance.md)) |

Range limits for readings: `raw` 7 days, `15m` 31 days, `1h` 366 days.

```json
// GET /live
{
  "server_time": "2026-11-02T09:31:01Z",
  "latest_run_id": "4817",
  "site_status": { "heatwave": "green", "heavy_rain": "yellow", "high_wind": "green" },
  "active_alerts": { "count": 1, "highest_level": "yellow" },
  "kits": [
    {
      "kit_id": "KIT-01",
      "zone": "Main Block Rooftop",
      "status": "online",
      "last_reading_at": "2026-11-02T09:31:00Z",
      "reading": {
        "ts": "2026-11-02T09:31:00Z",
        "temp_c": 30.92, "rh_pct": 64.1, "pressure_msl_hpa": 1012.1,
        "wind_avg_kmh": 12.4, "wind_gust_kmh": 21.7, "wind_dir_deg": null,
        "rain_mm": 0.84, "rain_1h_mm": 3.1, "rain_24h_mm": 12.6, "rain_rate_mmh": 50.4,
        "heat_index_c": 36.0,
        "pressure_tendency_1h_hpa": -0.6, "pressure_tendency_3h_hpa": -1.4,
        "temp_change_30m_c": -0.3,
        "squall_precursor": false,
        "qc": { "status": "valid", "flags": [] }
      }
    }
  ]
}
```

```json
// GET /kits/KIT-01/readings?from=2026-11-02T00:00:00Z&to=2026-11-03T00:00:00Z&resolution=15m&fields=temp_c,wind_gust_kmh
{
  "kit_id": "KIT-01",
  "resolution": "15m",
  "fields": ["temp_c", "wind_gust_kmh"],
  "items": [
    { "ts": "2026-11-02T00:00:00Z", "temp_c": 26.8, "wind_gust_kmh": 9.4, "qc_status": "valid" },
    { "ts": "2026-11-02T00:15:00Z", "temp_c": 26.6, "wind_gust_kmh": 11.0, "qc_status": "valid" }
  ]
}
```

For `15m` and `1h`, gusts are the maximum in the interval, rain is the sum, other values the mean (exact rules in [05](05-data-pipeline.md)).

### 2.6.5 Kit health and system status

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/kits/{kit_id}/health` | any | Status, last data, RSSI, uptime, firmware, clock offset, QC counts (24 h), BME280 vs DHT11 difference, open maintenance notices |
| GET | `/kits/{kit_id}/status-history` | any | Online/offline changes and outages (DP-13); cursor |
| GET | `/kits/{kit_id}/qc-flags` | any | Flagged readings (suspicious/faulty) with check and value; cursor |
| GET | `/rejected-messages` | any | Messages that failed contract validation (DP-12), incl. unknown kits; filter `kit_id`; cursor |
| GET | `/system/status` | any | Process heartbeats, latest forecast run age, onboarding state, clock mode, `warnings[]` (stale forecast, model fallback, invalid configuration, slow runs); for admins also failed-email count |

```json
// GET /kits/KIT-01/health
{
  "kit_id": "KIT-01",
  "status": "online",
  "since": "2026-11-02T04:40:12Z",
  "last_reading_at": "2026-11-02T09:31:00Z",
  "fw": "1.0.0",
  "rssi_dbm": -67,
  "uptime_s": 17448,
  "clock_offset_s": 0.4,
  "qc_24h": { "valid": 1421, "suspicious": 12, "faulty": 2 },
  "bme_dht_temp_diff_c": -0.6,
  "rejected_24h": 0,
  "maintenance_notices": [
    { "id": "m1…", "opened_at": "2026-11-02T08:05:00Z", "kind": "stuck_sensor", "detail": "dht_rh_pct unchanged for 3 h" }
  ]
}
```

```json
// GET /rejected-messages?kit_id=KIT-01
{
  "items": [
    {
      "id": "r1…", "received_at": "2026-11-02T09:12:03Z",
      "topic": "sites/abc/kits/KIT-01/readings", "kit_id": "KIT-01",
      "reason_code": "wrong_type",
      "reason": "bme_rh_pct: expected number, got string",
      "payload_excerpt": "{\"kit_id\":\"KIT-01\",\"ts\":\"2026-11-02T09:12:00Z\",\"bme_rh_pct\":\"64\"…"
    }
  ],
  "next_cursor": null
}
```

```json
// GET /system/status
{
  "processes": [
    { "name": "ingest", "state": "up", "last_beat_at": "2026-11-02T09:31:00Z", "started_at": "2026-11-02T04:00:02Z" },
    { "name": "worker", "state": "down", "last_beat_at": "2026-11-02T09:20:11Z", "started_at": "2026-11-02T04:00:03Z" }
  ],
  "forecast": { "latest_run_at": "2026-11-02T09:15:00Z", "age_s": 961, "stale": false },
  "onboarding": { "state": "completed" },
  "clock": { "mode": "real", "speed": 1 },
  "warnings": [],
  "failed_emails": 0
}
```

### 2.6.6 Forecast

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/forecast/latest` | any | Latest completed run: hourly P10/P50/P90 per kit and variable, 1–72 h; `?kit_id=` to limit |
| GET | `/forecast/latest/probabilities` | any | Hazard exceedance probabilities of the latest run; filters `hazard`, `kit_id` |
| GET | `/forecast/runs` | any | List of runs: issue time, status, duration, model and config versions; `from`, `to`; cursor |
| GET | `/forecast/runs/{run_id}` | any | One run, same shape as `latest` |
| GET | `/forecast/runs/{run_id}/probabilities` | any | Probabilities of that run |
| GET | `/external-forecast/latest` | any | Latest stored Open-Meteo forecast for the site, with its issue time (DP-10) |

All return `ETag: "run-<run_id>"` (or the external forecast issue time) for caching.

```json
// GET /forecast/latest?kit_id=KIT-01
{
  "run": {
    "id": "4817",
    "issue_time": "2026-11-02T09:30:00Z",
    "status": "completed",
    "finished_at": "2026-11-02T09:31:42Z",
    "model_versions": { "tft": "tft-nwp-1.0.0", "event_classifier": "lgbm-events-nwp-1.0.0" },
    "config_versions": { "site": 8, "kits": { "KIT-01": 12 } }
  },
  "kits": [
    {
      "kit_id": "KIT-01",
      "run_status": "ok",
      "filled_hours": 0,
      "target_times": ["2026-11-02T10:30:00Z", "2026-11-02T11:30:00Z", "…72 entries (rolling hours ending at issue time + n h, 07 §7.3)"],
      "variables": {
        "temp_c":        { "p10": [30.1, 30.8], "p50": [31.0, 31.9], "p90": [31.8, 33.0] },
        "rh_pct":        { "p10": [58, 55],     "p50": [63, 60],     "p90": [68, 66] },
        "wind_gust_kmh": { "p10": [12, 14],     "p50": [19, 22],     "p90": [29, 34] },
        "rain_mm":       { "p10": [0, 0],       "p50": [0, 0.2],     "p90": [0.6, 2.4] },
        "pressure_msl_hpa": { "p10": [1011.2, 1010.6], "p50": [1011.8, 1011.3], "p90": [1012.4, 1012.0] }
      }
    }
  ]
}
```

```json
// GET /forecast/latest/probabilities?hazard=high_wind
{
  "run_id": "4817",
  "issue_time": "2026-11-02T09:30:00Z",
  "items": [
    {
      "hazard": "high_wind", "event": "gust", "level": "orange",
      "scope": { "kind": "kit", "kit_id": "KIT-01", "zone": "Main Block Rooftop" },
      "threshold": { "variable": "wind_gust_kmh", "op": ">=", "value": 50 },
      "window_start": "2026-11-02T14:00:00Z", "window_end": "2026-11-02T18:00:00Z",
      "probability": 0.35, "source": "tft"
    }
  ]
}
```

### 2.6.7 Alerts

| Method | Path | Role | Audit | Reason | Purpose |
|---|---|---|---|---|---|
| GET | `/alerts` | any | | | List; filters `status` (`active` default, `closed`, `all`), `hazard`, `type`, `level`, `kit_id`, `from`, `to`; cursor |
| GET | `/alerts/{id}` | any | | | Full alert (AL-03) with acknowledgement, suppression, notes, history, probability trend (AL-13), email summary |
| GET | `/alerts/{id}/history` | any | | | All changes of the alert; cursor |
| POST | `/alerts/{id}/acknowledge` | any | ✅ | | Acknowledges the alert's latest escalation; atomic, first click wins (WEB-23). Every upgrade (higher level or watch → warning → live) needs a new acknowledgement (DD36) |
| POST | `/alerts/{id}/notes` | any | ✅ | | Add an internal note (never emailed, WEB-42) |
| PUT | `/alerts/{id}/advice` | any | ✅ | | Set the advice message used in this alert's future emails |
| POST | `/alerts/{id}/suppress` | any | ✅ | ✅ | Command: suppress until `expires_at` (AL-15) |
| POST | `/alerts/{id}/unsuppress` | any | ✅ | ✅ | Command: end the suppression early |
| POST | `/alerts/manual` | any | ✅ | ✅ | Command: raise a manual alert |
| POST | `/alerts/{id}/clear` | any | ✅ | ✅ | Command: clear a manual alert (`409 NOT_MANUAL_ALERT` for automatic ones) |
| GET | `/alert-commands/{id}` | any | | | Command state and result (§2.5) |

Alert enums (defined in [08 §8.2–8.3](08-alert-engine.md)):

| Field | Values |
|---|---|
| `hazard` | `heatwave`, `heavy_rain`, `high_wind` |
| `event` | `heatwave` (orange = heatwave, red = severe heatwave), `rain_24h`, `rain_intensity`, `gust` ([08 §8.2](08-alert-engine.md)) |
| history `trigger` | `forecast`, `sustained`, `squall`, `manual`, `system` |
| `type` | `watch`, `warning`, `live` |
| `level` | `yellow`, `orange`, `red` (green = no alert) |
| `source` | `forecast`, `live`, `manual` |
| `status` | `active`, `cancelled` (forecast no longer expects it), `cleared` (live conditions ended or manual clear) |
| `scope.kind` | `kit` (per zone), `site` (combined, AL-14) |
| history `change` | `created`, `upgraded`, `downgraded`, `updated` (window moved, DD101), `cancelled`, `cleared`, `taken_over`, `suppressed`, `unsuppressed`, `suppression_overridden`, `suppression_expired`, `threshold_changed`, `advice_updated` |

```json
// GET /alerts/a7…
{
  "id": "a7…",
  "hazard": "high_wind", "event": "gust", "type": "warning", "level": "orange",
  "source": "forecast", "status": "active",
  "scope": { "kind": "kit", "kit_id": "KIT-01", "zone": "Main Block Rooftop" },
  "probability": 0.72,
  "threshold": { "variable": "wind_gust_kmh", "op": ">=", "value": 50 },
  "window_start": "2026-11-02T08:30:00Z", "window_end": "2026-11-02T12:30:00Z",
  "issued_at": "2026-11-02T05:30:00Z", "updated_at": "2026-11-02T07:00:00Z", "closed_at": null,
  "forecast_run_id": "4796",
  "advice_message": "Secure loose objects on rooftops. Avoid the sports ground after 14:00.",
  "needs_acknowledgement": false,
  "acknowledged": { "by": { "id": "u1…", "name": "Priya" }, "at": "2026-11-02T07:10:00Z", "change": "upgraded" },
  "acknowledgements": [
    { "by": { "id": "u2…", "name": "Ravi" },  "at": "2026-11-02T05:40:00Z", "change": "created" },
    { "by": { "id": "u1…", "name": "Priya" }, "at": "2026-11-02T07:10:00Z", "change": "upgraded" }
  ],
  "suppression": null,
  "probability_trend": [
    { "run_id": "4790", "issue_time": "2026-11-02T05:30:00Z", "probability": 0.35 },
    { "run_id": "4793", "issue_time": "2026-11-02T06:15:00Z", "probability": 0.44 },
    { "run_id": "4796", "issue_time": "2026-11-02T07:00:00Z", "probability": 0.72 }
  ],
  "notes": [ { "id": "n1…", "by": { "id": "u1…", "name": "Priya" }, "at": "2026-11-02T07:11:00Z", "text": "Informed sports dept by phone." } ],
  "history": [
    { "at": "2026-11-02T05:30:00Z", "change": "created", "type": "watch", "level": "orange", "probability": 0.35, "run_id": "4790" },
    { "at": "2026-11-02T07:00:00Z", "change": "upgraded", "type": "warning", "level": "orange", "probability": 0.72, "run_id": "4796" }
  ],
  "emails": { "sent": 9, "failed": 0, "last_sent_at": "2026-11-02T07:00:40Z" }
}
```

```json
// POST /alerts/a7…/acknowledge   → 409 for the second operator
{
  "type": "about:blank", "title": "Already acknowledged", "status": 409,
  "code": "ALREADY_ACKNOWLEDGED",
  "detail": "Already acknowledged by Priya at 12:40 IST",
  "acknowledged_by": { "id": "u1…", "name": "Priya" },
  "acknowledged_at": "2026-11-02T07:10:00Z"
}
```

```json
// POST /alerts/a7…/suppress
{ "reason": "Known construction crane test, safe", "expires_at": "2026-11-02T11:30:00Z" }
```

`expires_at` must be in the future and at most the configured maximum suppression length (`EXPIRY_INVALID`).

```json
// POST /alerts/manual
{
  "hazard": "high_wind", "event": "gust", "type": "live", "level": "red",
  "scope": { "kind": "kit", "kit_id": "KIT-02" },
  "window_start": null, "window_end": null,
  "advice_message": "Stop outdoor games and move everyone indoors.",
  "reason": "Tree branch fell near the sports ground"
}
```

### 2.6.8 Configuration (admin)

| Method | Path | Role | Audit | Reason | Purpose |
|---|---|---|---|---|---|
| GET | `/config/schema` | admin | | | Key catalogue: key, type, default, allowed levels, validation rules ([04](04-configuration.md)) |
| GET | `/config/site` | admin | | | Current site record: `version`, values set at site level, who/when |
| POST | `/config/site` | admin | ✅ | | Create the site (first run only; `409 SITE_ALREADY_EXISTS`); starts onboarding (CFG-07) |
| PUT | `/config/site` | admin | ✅ | ✅ | Replace site values with `base_version` (CFG-04) |
| GET | `/config/kits` | admin | | | All kit records |
| POST | `/config/kits` | admin | ✅ | ✅ | Add a kit |
| GET | `/config/kits/{kit_id}` | admin | | | One kit record |
| PUT | `/config/kits/{kit_id}` | admin | ✅ | ✅ | Replace kit values with `base_version`; `kit_enabled: false` retires a kit (kept, never deleted). Values use the flat keys of [04 §4.3](04-configuration.md) |
| GET | `/config/effective` | admin | | | Resolved value and source of every key; `?kit_id=` for one kit, without it the site-level view (CFG-06) |
| POST | `/config/validate` | admin | | | Dry run of a site or kit save: errors, `warnings[]` and the effective result for every affected kit; nothing stored |
| POST | `/config/import` | admin | ✅ | ✅ | YAML body (`application/yaml`) with site, kits and recipients; `?dry_run=true` validates only; atomic ([04 §4.6](04-configuration.md)) |
| GET | `/config/export` | admin | | | YAML of the site, kits and recipients; `?effective=true` adds resolved values with sources |
| GET | `/config/recipients` | admin | | | Alert recipient lists with hazards and zones (WEB-41) |
| POST | `/config/recipients` | admin | ✅ | ✅ | Add a recipient |
| PUT | `/config/recipients/{id}` | admin | ✅ | ✅ | Replace a recipient with `base_version` (row version) |
| GET | `/config/history` | admin | | | Versions with author, time, reason and changed keys; filters `scope` (`site`, `kit`), `kit_id`; cursor |
| GET | `/config/history/{version_id}` | admin | | | Full snapshot of one version |

Rules:

- `PUT` replaces the whole set of values defined at that level; keys left out fall back to the next level. The response is the new record with `version` + 1.
- A save based on an old version returns `409 CONFIG_VERSION_CONFLICT` with `current_version` (WEB-22).
- Changing `site_id` after a kit has connected → `SITE_ID_IMMUTABLE`.
- Changing site latitude, longitude, elevation or region type starts onboarding again; the response contains `"onboarding_started": true`.
- Kit MQTT credentials are set in Mosquitto's password file (setup guide), not through the API.

```json
// PUT /config/kits/KIT-01
{
  "base_version": 7,
  "reason": "Lower orange gust threshold after site review",
  "values": {
    "kit_zone": "Main Block Rooftop",
    "lat": 13.081, "lon": 80.271, "elevation_m": 30, "mount_height_m": 3,
    "exposure": "rooftop",
    "cal_temp_offset_c": -0.5,
    "wind_orange_kmh": 45
  }
}

// 200 OK
{ "kit_id": "KIT-01", "version": 8, "updated_at": "2026-11-02T04:33:00Z", "updated_by": { "id": "u0…", "name": "Admin A" }, "values": { "…": "…" } }
```

```json
// GET /config/effective?kit_id=KIT-02
{
  "kit_id": "KIT-02",
  "items": [
    { "key": "timezone",        "value": "Asia/Kolkata", "source": "site" },
    { "key": "heat_min_tmax_c", "value": 37,             "source": "default", "region_type": "coastal" },
    { "key": "rain_intensity_1h_mm", "value": 28.0,      "source": "onboarding" },
    { "key": "wind_yellow_kmh", "value": 39,             "source": "default" },
    { "key": "wind_orange_kmh", "value": 35,             "source": "kit" },
    { "key": "wind_red_kmh",    "value": 45,             "source": "kit" }
  ]
}
```

### 2.6.9 Onboarding

| Method | Path | Role | Audit | Reason | Purpose |
|---|---|---|---|---|---|
| GET | `/onboarding` | any | | | State (`pending`, `running`, `completed`, `failed`) and per-step progress (04 §4.5) |
| POST | `/onboarding/rerun` | admin | ✅ | ✅ | Run onboarding again (`409 ONBOARDING_RUNNING` if running); `202` |

```json
// GET /onboarding
{
  "state": "running", "started_at": "2026-11-01T10:00:00Z", "finished_at": null,
  "steps": [
    { "step": "download_history", "state": "completed" },
    { "step": "compute_normals",  "state": "completed" },
    { "step": "generate_labels",  "state": "running" },
    { "step": "find_top_events",  "state": "pending" },
    { "step": "backtest",         "state": "pending" },
    { "step": "report",           "state": "pending" }
  ],
  "error": null
}
```

### 2.6.10 Notifications (admin)

| Method | Path | Role | Audit | Purpose |
|---|---|---|---|---|
| GET | `/notifications/emails` | admin | | Outbox and send log: filters `status` (`queued`, `sent`, `failed`, `skipped`), `alert_id`, `from`, `to`; cursor (WEB-44) |
| GET | `/notifications/emails/{id}` | admin | | One email with all attempts and errors |
| POST | `/notifications/emails/{id}/retry` | admin | ✅ | Queue a failed email again (`409 EMAIL_NOT_RETRYABLE` otherwise) |

Recipient lists are part of site config (D24) and edited through §2.6.8 (`/config/recipients`).

### 2.6.11 Audit log (admin)

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/audit` | admin | Filters `actor_id`, `action`, `entity_type`, `entity_id`, `from`, `to`; cursor |

```json
{
  "items": [
    {
      "id": "e1…", "at": "2026-11-02T04:33:00Z",
      "actor": { "id": "u0…", "name": "Admin A" }, "ip": "127.0.0.1",
      "action": "config.kit.update", "entity_type": "kit_config", "entity_id": "KIT-01",
      "reason": "Lower orange gust threshold after site review",
      "changes": { "wind_orange_kmh": { "from": null, "to": 45 } }
    }
  ],
  "next_cursor": "eyJ0…"
}
```

Logins (success and failure), logouts, and every write in this document produce an entry.

### 2.6.12 Model reports

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/reports/models` | any | Active model versions and registry entries (ML-09) |
| GET | `/reports/accuracy` | any | MAE/RMSE per variable per horizon, model vs baselines; `source` = `test` (offline test set) or `live` (stored runs vs kit observations); filters `variable`, `model` |
| GET | `/reports/hazard-skill` | any | Recall, precision, false-alarm rate, F1, PR-AUC, lead time per hazard (§5.7) |
| GET | `/reports/backtests` | any | Onboarding back-tests: top-10 events per hazard, whether and how early a Watch/Warning would have been issued (TST-15) |
| GET | `/reports/importance` | any | TFT variable importance and LightGBM SHAP summary (ML-10) |

```json
// GET /reports/accuracy?variable=wind_gust_kmh&source=test
{
  "variable": "wind_gust_kmh", "source": "test", "period": { "from": "2022-01-01", "to": "2026-01-01" },
  "horizons_h": [1, 3, 6, 24, 72],
  "models": [
    { "model": "tft-nwp-1.0.0",    "mae": [3.1, 4.0, 4.6, 5.9, 7.2], "rmse": [4.2, 5.4, 6.1, 7.8, 9.5] },
    { "model": "persistence",      "mae": [3.4, 5.6, 6.9, 8.8, 9.9], "rmse": [4.8, 7.4, 9.0, 11.2, 12.6] },
    { "model": "open_meteo",       "mae": [4.4, 4.6, 4.9, 6.3, 7.6], "rmse": [5.9, 6.1, 6.5, 8.3, 9.9] }
  ]
}
```

## 2.7 WebSocket (DD17)

### 2.7.1 Connection

| Item | Rule |
|---|---|
| URL | `ws://<host>/api/v1/ws` |
| Auth | Session cookie on handshake; `Origin` must match `APP_BASE_URL` (or `DEV_ORIGINS` in development, DD122); otherwise the handshake is refused |
| Direction | Server → client only (the client sends nothing except protocol pings) |
| First message | `hello` with user, role, server time and session expiry |
| Keep-alive | Server sends `ping` every 20 s. If the client gets no message for 45 s it treats the connection as dead |
| Reconnect (NFR-04) | Client reconnects with backoff 1, 2, 5, 10, 30 s (then every 30 s), shows "Reconnecting…" and the age of the data. After every (re)connect it reloads current state over REST (`/live`, `/alerts`, `/system/status`, and the page's own data). No event replay |
| Slow clients | If a client's send queue exceeds 1000 events the server closes with `4008`; the client reconnects and reloads |
| Close codes | `4401` session ended/expired (go to login), `4403` account deactivated, `4008` too slow, `1012` server restarting |

### 2.7.2 Envelope

```json
{ "seq": 1042, "type": "reading.new", "at": "2026-11-02T09:31:00.412Z", "data": { } }
```

`seq` counts up per connection (for ordering and debugging).

### 2.7.3 Events (WEB-24)

| Type | Role | Data | Client action |
|---|---|---|---|
| `hello` | any | `user`, `role`, `server_time`, `session_expires_at` | Start; reload state over REST |
| `ping` | any | — | Reset the 45 s timer |
| `reading.new` | any | `kit_id` + the `reading` object of `/live` | Update tiles and live charts |
| `kit.status` | any | `kit_id`, `status`, `at`, `last_reading_at` | Online/offline badge |
| `kit.qc_flag` | any | `kit_id`, `ts`, `status`, `flags` | Kit-health indicator |
| `kit.message_rejected` | any | `kit_id` (or `null`), `received_at`, `reason` | Kit-health counter |
| `kit.maintenance_notice` | any | `kit_id`, notice | Maintenance banner (DP-26) |
| `forecast.run_completed` | any | `run_id`, `issue_time`, `status` | Refetch forecast views (ETag) |
| `alert.changed` | any | `change` (history values in §2.6.7), `trigger`, `replaces_alert_id` (take-over, D29) + alert summary (`id`, `hazard`, `event`, `type`, `level`, `status`, `scope`, `probability`, `window_start`, `window_end`, `needs_acknowledgement`) | Update banner and lists; optional sound on `created`/`upgraded` (§7.6) |
| `alert.acknowledged` | any | `alert_id`, `by`, `at` | Show acknowledgement |
| `alert.note_added` | any | `alert_id`, note | Update the alert detail |
| `alert.command_result` | issuing user only | command (`id`, `kind`, `status`, error) + `alert_id` | Finish a pending (202) command |
| `config.changed` | any | `scope`, `kit_id`, `version`; admins also get `changed_keys` and `by` | Admin pages reload; others show "Configuration updated" |
| `onboarding.progress` | any | as `GET /onboarding` | Progress view |
| `system.status` | any (admins also get `failed_emails`) | process up/down, forecast stale | Status warning |

```json
{
  "seq": 2210, "type": "alert.changed", "at": "2026-11-02T08:48:00.120Z",
  "data": {
    "change": "created",
    "trigger": "squall",
    "replaces_alert_id": "a7…",
    "alert": {
      "id": "b3…", "hazard": "high_wind", "event": "gust", "type": "live", "level": "orange",
      "status": "active", "scope": { "kind": "kit", "kit_id": "KIT-01", "zone": "Main Block Rooftop" },
      "probability": null, "window_start": "2026-11-02T08:48:00Z", "window_end": null
    }
  }
}
```

## 2.8 Role matrix and permission tests (TST-16)

| Group | public | operator | admin |
|---|---|---|---|
| Setup status, first-run setup, login, invite view/accept, password reset | ✅ | ✅ | ✅ |
| Logout, `me`, profile, email preferences | | ✅ | ✅ |
| Site, live, kits, readings | | ✅ | ✅ |
| Kit health, rejected messages, system status | | ✅ | ✅ (+ failed-email count) |
| Forecast, external forecast | | ✅ | ✅ |
| Alerts: read, acknowledge, notes, advice, suppress, manual, clear | | ✅ | ✅ |
| Onboarding status | | ✅ | ✅ |
| Onboarding re-run | | | ✅ |
| Model reports | | ✅ | ✅ |
| Users | | | ✅ |
| Configuration (all, incl. calibration and effective values) | | | ✅ |
| Notifications (email log, retry) | | | ✅ |
| Audit log | | | ✅ |
| WebSocket | | ✅ | ✅ |

Permission tests generated from this matrix ([12](12-testing.md)):

1. Every non-public endpoint without a session → `401`.
2. Every admin endpoint with an operator session → `403 FORBIDDEN`.
3. A deactivated user's old session → `401`; login → `403 ACCOUNT_DEACTIVATED`; WebSocket closed with `4403`.
4. Every write without `X-CSRF-Token` → `403 CSRF_FAILED`.
5. WebSocket handshake without a session or with a wrong `Origin` → refused.
6. Operators never receive admin-only fields (`changed_keys`, `failed_emails`) over the WebSocket.

## 2.9 Requirement coverage

| Requirement | Section |
|---|---|
| WEB-01 – WEB-06 | §2.2, §2.6.1, §2.6.3 |
| WEB-07 | `POST /users/invites/bulk` |
| WEB-08 | `/me/email-preferences` |
| WEB-20 | All forecast and alert endpoints are read-only views of server results |
| WEB-21, TST-16 | §2.2.2, §2.8 |
| WEB-22, CFG-04 | `base_version`, `409 CONFIG_VERSION_CONFLICT` |
| WEB-23 | `POST /alerts/{id}/acknowledge` |
| WEB-24, NFR-01 | §2.7 |
| WEB-25 | Audit column, §2.6.11 |
| WEB-44 | §2.6.10, `failed_emails` in system status |
| CFG-02, CFG-03 | Field-level error codes, `POST /config/validate` |
| CFG-06 | `GET /config/effective` |
| CFG-07 | `POST /config/site`, onboarding endpoints |
| AL-03, AL-13, AL-15 | §2.6.7 |
| DP-12, DP-13, DP-26 | §2.6.5 |
| ML-09, ML-10, TST-15 | §2.6.12 |
| NFR-03 | Rate limits, ETag caching |
| NFR-04 | §2.7.1 reconnect and reload |
| NFR-06 | UTC timestamps, timezone from `/site` |
