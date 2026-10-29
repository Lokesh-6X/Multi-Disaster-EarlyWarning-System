# 7. Web Application

## 7.1 Access model

There is **no public (unauthenticated) page**, **no viewer accounts** and **no kiosk/TV view**. Every page and data endpoint requires an operator or admin login.

| Who | Login | Access |
|---|---|---|
| Operator | Yes (invited) | Live dashboard, forecast, alerts, map, model reports; acknowledge alerts, notes, suppress/raise alerts, kit health |
| Admin | Yes (invited) | Everything: config, users, audit log, model reports |

There is no self sign-up. Accounts are created by admin invitation only.

One installation monitors **one site** (D26). All accounts belong to that installation and see that site; there is no site selector.

Only these endpoints are reachable without authentication: login, invite acceptance, password reset, first-run setup (WEB-01).

Students, staff and visitors are reached only through **email alerts** sent to configured recipient lists (§7.6) and through operators relaying alerts.

The dashboard is used **only on the server machine** (the control PC); it is not reachable from phones or other computers (D34). Links in emails, both alert links ("Acknowledge") and account links (invite acceptance, password reset), open only on that machine; these emails say so.

## 7.2 Pages

| Page | Audience | Content | Priority |
|---|---|---|---|
| Live dashboard | Operator/Admin | Current temperature, humidity, wind/gust, rain, pressure, heat index; alert banner; last-updated time; kit status (Live/Offline) | M |
| Forecast | Operator/Admin | 72 h charts with shaded P10–P90 ranges; hazard probabilities; Watch/Warning timeline | M |
| Alerts | Operator/Admin | Active alerts with advice; alert history; probability trend | M |
| Map | Operator/Admin | Kits/zones on a site map coloured by alert level | C (multi-kit) |
| Operator panel | Operator | Acknowledge, internal notes, advice message, suppress (reason + expiry), manual alert | M |
| Kit health | Operator/Admin | Online/offline, last data, outage history, rejected messages, QC flags, BME280 vs DHT11, signal, firmware | M |
| Configuration | Admin | Site/kit editor with validation, effective values and their source | S |
| Users | Admin | Invite, change role, deactivate | M |
| Audit log | Admin | Who, what, when, why for every write | M |
| Model reports | Operator/Admin | Accuracy by lead time, comparison with baselines, back-tests of past extreme events, variable importance | S |

## 7.3 Data visibility by role

| Operator | Admin only |
|---|---|
| Live readings, forecasts, alerts, alert history, advice message | Config, calibration |
| Internal notes, operator names, detailed kit health | User management, audit log |

Alerts have a separate **advice message** field used in alert emails to recipient lists; internal notes are never sent to recipient lists.

## 7.4 Users and accounts

| ID | Requirement | Priority |
|---|---|---|
| WEB-01 | First-run setup screen creates the first admin; it is available only while no users exist. | M |
| WEB-02 | Admins invite operators/admins; the system creates an `invited` account and a one-time invite link that expires (default 48 h). | M |
| WEB-03 | Invite and password-reset links are sent by email; they are also shown to the admin / printed in the server console as a fallback if sending fails. | M |
| WEB-04 | Account states: `invited` → `active` → `deactivated` (reactivation allowed). Accounts are deactivated, never deleted. Roles: `operator`, `admin`. | M |
| WEB-05 | Only admins change roles; admins cannot change their own role; the last admin cannot be removed or demoted. | M |
| WEB-06 | Passwords stored only as bcrypt/Argon2 hashes; temporary lock after 5 failed logins (15 min); session tokens expire (default 8 h). | M |
| WEB-07 | Bulk invite via CSV (name, email, role). | C |
| WEB-08 | Operators/admins choose in their profile which alert emails they receive (hazards, minimum level). | S |

## 7.5 Multi-user behaviour

| ID | Requirement | Priority |
|---|---|---|
| WEB-20 | Forecasts and alerts are computed **once on the server**; users only read results. | M |
| WEB-21 | Permissions are enforced by the backend, not just by hiding UI elements. No data endpoint is reachable without authentication. | M |
| WEB-22 | Config edits use version numbers; saving an outdated version is rejected with "Someone else changed this config. Reload." | M |
| WEB-23 | Alert acknowledgement is atomic, first click wins; later clicks see "Already acknowledged by X at time". | M |
| WEB-24 | The server broadcasts events over WebSocket to all authenticated clients (filtered by role): new reading, new forecast run, alert created/changed/cleared, acknowledgement, config change, kit online/offline. | M |
| WEB-25 | Every write action is recorded in the audit log (who, what, when, why). | M |
| WEB-26 | Operator notifications are deduplicated per user (a log of sent notifications prevents repeats on retry). | M |

## 7.6 Notifications

| Channel | Audience | Priority |
|---|---|---|
| Email to recipient lists (every alert change) | People at the site (e.g. site mailing lists) | M |
| Email with detail and "Acknowledge" link | Operators/Admins | M |
| Dashboard banner + optional sound | Operators/Admins | M |

Email is the only notification channel. SMS and Telegram are future enhancements ([09 §9.2](09-decisions-and-open-questions.md)); the notification sender should be written so a new channel can be added later without changing the alert engine.

| ID | Requirement | Priority |
|---|---|---|
| WEB-40 | Every alert change (created, upgraded, downgraded, cancelled) is emailed to the site's recipient lists. Subject format: `[LEVEL TYPE] Hazard – Zone – time window`, e.g. `[ORANGE WARNING] High wind – Sports Ground – 14:00–17:00 IST`. | M |
| WEB-41 | Recipient lists are configured at site level (address, hazards, minimum level); zone-specific lists come from local-risk routing ([04 §4.6](04-configuration.md)). | M |
| WEB-42 | Recipient-list emails contain only the advice message, level, hazard, zone and time window; never internal notes. | M |
| WEB-43 | Operator/admin emails add probability, forecast run and an "Acknowledge" link (login required). | M |
| WEB-44 | Emails are sent asynchronously with retries; every send is logged (used for dedup WEB-26 and cooldown AL-06); repeated failures are shown to admins. | M |
| WEB-45 | Emails are plain text with a simple HTML version that works in common mail clients. | S |
| WEB-46 | Local demo: all mail is captured by a local test mail server (Mailpit, installed and run locally); real SMTP settings come from the environment file. | M |

**Limitation (state in the report):** email delivery can take minutes and people may not check mail promptly, so it is weaker than push channels for sudden squall **Live** alerts.
