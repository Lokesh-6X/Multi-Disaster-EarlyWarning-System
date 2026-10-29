# 9. Notifications

The `mailer` process and everything about email: message kinds, the two audiences, subjects and templates, rendering, the outbox, retries, deduplication, superseded messages, threading, account and maintenance emails, and the channel interface for future SMS/Telegram. Requirements: [07 §7.6](../requirements/07-web-application.md) (WEB-40 – WEB-46), WEB-03, WEB-26, AL-06, AL-08, D13, D17, D24. Who gets which alert change is decided by the alert engine ([08 §8.11](08-alert-engine.md)); tables in [03 §3.10](03-database-schema.md).

Decisions referenced: DD69–DD75 in [decisions.md](decisions.md).

## 9.1 Message kinds

| Kind | Queued by | Audience | Template |
|---|---|---|---|
| `alert` | `alerts` | Recipient lists (people at the site) | `alert_public` |
| `alert` | `alerts` | Operators and admins | `alert_operator` |
| `maintenance` | `alerts` | Operators and admins (`notify_maintenance`, personal preference) | `maintenance` |
| `invite` | `api` | Invited user | `invite` |
| `password_reset` | `api` | User | `password_reset` |

The audience follows from the addressee column (`recipient_id` or `user_id`); it is not stored ([03 §3.10](03-database-schema.md)).

## 9.2 Flow

```
alerts / api ── one transaction: state change + email_message rows (status queued) ── NOTIFY email.queued
                                                                                          │
mailer (wakes on NOTIFY, polls every 30 s as backup)                                      ▼
  1 claim:   SELECT … WHERE status = 'queued' AND next_attempt_at <= now
             ORDER BY next_attempt_at FOR UPDATE SKIP LOCKED LIMIT 20  → status 'sending'
  2 supersede check (§9.6)            → skipped
  3 render subject, text, HTML (§9.4) → subject stored
  4 send over SMTP (connection reused)
  5 email_attempt row; status sent / queued (retry) / failed; link_secret cleared after success
```

On start-up, rows left in `sending` (crash during send) go back to `queued`; the attempt log shows the interrupted attempt. Duplicate delivery is possible only in that rare crash window, which is accepted.

Target: alert change → message in the Mailpit inbox within 10 s.

## 9.3 Subjects (WEB-40, DD70)

Format: `[LEVEL TYPE] <Change:> Hazard – Zone – Time window`, times in the site timezone (NFR-06).

| Change | Subject example |
|---|---|
| `created` (forecast) | `[ORANGE WATCH] High wind – Main Block Rooftop – 14:00–18:00 IST` |
| `upgraded` | `[ORANGE WARNING] Upgraded: High wind – Main Block Rooftop – 14:00–18:00 IST` |
| `created` (live, squall) | `[ORANGE LIVE] High wind (squall) – Main Block Rooftop – now` |
| `upgraded` (live) | `[RED LIVE] Upgraded: High wind – Main Block Rooftop – now` |
| `downgraded` | `[YELLOW WATCH] Downgraded: High wind – Sports Ground – 15:00–18:00 IST` |
| `updated` (window moved, DD101) | `[ORANGE WATCH] Updated: High wind – Main Block Rooftop – 20:00–23:00 IST` |
| Live 24 h rain | `[YELLOW LIVE] Heavy rainfall – ABC College – 64.5 mm or more in the last 24 h` |
| `cancelled` | `[CANCELLED] High wind – Main Block Rooftop – no longer expected` |
| `cleared` | `[CLEARED] High wind – Main Block Rooftop – conditions back to normal` |
| Site heatwave | `[ORANGE WARNING] Heatwave – ABC College – Fri 3 Nov` |
| Site 24 h rain | `[YELLOW WATCH] Heavy rainfall – ABC College – 08:30 Fri – 08:30 Sat IST` |
| Manual | `[RED LIVE] High wind – Sports Ground – now (raised by operator)` |
| Maintenance | `[MAINTENANCE] KIT-01 Main Block Rooftop – offline since 10:02 IST` |

Windows are always shown in whole hours: start rounded down, end rounded up (requirements D38, DD119).

| Window rule | Format |
|---|---|
| Same local day | `14:00–18:00 IST` |
| Crosses midnight | `Fri 22:00 – Sat 02:00 IST` |
| Whole days (heatwave) | `Fri 3 Nov` or `Fri 3 – Sun 5 Nov` |
| Rain day | `08:30 Fri – 08:30 Sat IST` |
| Live | `now` |

In demo mode every subject starts with `[DEMO]` ([11 §11.3.1](11-simulator.md)).

Hazard names: "Heatwave" (red: "Severe heatwave"), "Heavy rainfall", "Heavy rain burst" (`rain_intensity`), "High wind".

## 9.4 Content (WEB-42, WEB-43, WEB-45, DD69)

Every email has a **plain-text** part and a **simple HTML** part (single column, inline styles, no images or scripts, level shown as a coloured label **with text**, readable in Outlook, Gmail and phone clients).

### 9.4.1 Recipient lists (`alert_public`)

Only level, type, hazard, zone, time window and the advice message (WEB-42); never probabilities, notes or names of operators.

```
ORANGE WARNING – High wind
Zone: Main Block Rooftop
When: 14:00–18:00 IST, Thursday 2 November
Status: Upgraded from Watch – strong gusts are now likely.

What to do:
Secure loose objects on rooftops. Avoid the sports ground after 14:00.

You receive this because you are on the "Site mailing list" alert list of ABC College.
Colours: Yellow = be aware, Orange = be prepared, Red = take action.
Watch = possible, Warning = likely, Live = happening now.
```

### 9.4.2 Operators and admins (`alert_operator`)

The public content plus (WEB-43):

| Added | Example |
|---|---|
| Probabilities of all levels | Red (≥ 62 km/h) 12 %, Orange (≥ 50 km/h) 72 %, Yellow 91 % |
| Trend | 35 % → 41 % → 44 % → 72 % |
| Source | Forecast run 12:30 IST, model `tft-nwp-1.0.0`; or trigger "squall rule", "sustained gusts" |
| Take-over | "Replaces the Orange Warning issued 11:00 IST" (D29) |
| Suppression / acknowledgement state | "Not yet acknowledged" |
| **Acknowledge** link | `APP_BASE_URL/alerts/<id>?ack=1`; opens on the server machine only (requirements D34); the email says "Open on the control PC" |
| Heatwave normal state | "Normal not yet calibrated" until the kit's normal offset exists (D33) |

The acknowledge link opens the alert page after login and asks "Acknowledge this alert?"; nothing is changed by opening a link (no state change on GET, DD74). Internal notes are never emailed.

### 9.4.3 Advice and data at send time

The email is rendered **when it is sent**, from the change it belongs to plus current context:

| Item | Source |
|---|---|
| State (level, type, window, probabilities) | The `alert_change` row of this email (what changed, not later state) |
| Advice | `alert.advice_override`, else the effective `advice_<hazard>` (kit level for zone alerts, site level for site alerts) at send time |
| Site name, timezone, zone name | Current configuration |

## 9.5 Recipients and deduplication

Selection rules are in [08 §8.11](08-alert-engine.md). Additional rules here:

- One email per addressee per change: unique `(alert_change_id, to_address)` (WEB-26). The engine inserts **user rows first**, then recipient-list rows, with `ON CONFLICT DO NOTHING`, so an operator who is also on a mailing list gets only the detailed version.
- A recipient list address is a single mailbox (e.g. a mailing list); the site's mail server fans it out. The system never expands lists.
- Inactive recipients and deactivated users get nothing; invited (not yet active) users get no alert emails.
- **Sticky audience (D36, DD102):** an addressee who received any email of an alert receives every later change of it, including its end, even if their filters (`min_level`, hazards, types) would no longer select it and even while the alert is suppressed. A Live alert that takes over another alert is also sent to that alert's audience. Personal and list filters decide only who is told first. The previous rule still wins: deactivated users and inactive recipients get nothing, sticky or not.

## 9.6 Superseded and delayed emails (AL-06, DD73)

Before sending an `alert` email, the mailer checks whether a **newer change of the same alert** is queued or sent for the same address. If so, and `email_skip_superseded` is on, this email is `skipped` ("superseded by …"). Result:

- Cooldown-delayed downgrades/cancels/clears ([08 §8.11](08-alert-engine.md)) collapse into one message with the latest state.
- After a mailer outage, each addressee gets only the newest state of each alert, not a burst of old ones.
- A `created` email still unsent when the `upgraded` one is queued is replaced by the upgrade (which contains the full current state).

## 9.7 Retries and failures (WEB-44, DD71)

| SMTP outcome | Classified as | Action |
|---|---|---|
| 2xx accepted | `sent` | Done; `sent_at` set |
| Connection error, timeout, 4xx | `temporary_failure` | Retry after `email_retry_base_s × 2^(attempt−1)` (30 s, 60 s, 2 min, 4 min, 8 min), capped at 15 min |
| 5xx (e.g. 550 mailbox unknown) | `permanent_failure` | `failed` at once |
| `email_max_attempts` (6) reached | — | `failed` |

- Every attempt is an `email_attempt` row (time, outcome, SMTP code, error).
- Failed emails appear in `/notifications/emails?status=failed`, the admin can retry them, and `failed_emails` in `/system/status` drives an admin banner (WEB-44).
- **Account emails (WEB-03):** if an invite or reset email fails permanently or after all retries, the mailer writes the link to the server console log (`logs/mailer.log`, clearly marked); the admin also sees the invite link in the invite response ([02 §2.6.3](02-api.md)). `link_secret` is cleared once the email is sent or failed.

## 9.8 Threading and headers (DD72)

| Header | Value |
|---|---|
| `From` | `"<email_from_name>" <SMTP_FROM>` |
| `Message-ID` | `<email-<email_id>@<site_id>.ews>` |
| `In-Reply-To`, `References` | The `Message-ID` of the first email of the same alert to the same address |
| `X-EWS-Alert-Id`, `X-EWS-Change` | Alert ID and change kind (for filters and tests) |
| `Auto-Submitted` | `auto-generated` (stops auto-replies and out-of-office loops) |

All emails about one alert therefore appear as **one conversation** in mail clients: created → upgraded → cleared.

## 9.9 Maintenance notices (DP-26, DD75)

One email when a notice **opens** ([05 §5.4.9](05-data-pipeline.md)), to operators/admins with maintenance emails enabled. Closing a notice is shown on the dashboard and kit-health page but not emailed, to keep noise low. The same notice is never emailed twice (unique `(notice_id, to_address)`).

## 9.10 SMTP configuration (WEB-46, NFR-08)

| Setting (`.env`) | Local demo | Real server |
|---|---|---|
| `SMTP_HOST`, `SMTP_PORT` | `localhost`, `1025` (Mailpit) | provider host, 587 |
| `SMTP_TLS` | `none` | `starttls` |
| `SMTP_USER`, `SMTP_PASSWORD` | empty | from the provider |
| `SMTP_FROM` | `alerts@site.local` | a real sender address |

Mailpit's web inbox (`http://localhost:8025`) shows every message; its API is used by the end-to-end tests ([12](12-testing.md)).

## 9.11 Channel interface (future SMS/Telegram, 07 §7.6)

```
class Sender(Protocol):
    channel: str                                   # "email"
    def send(self, message: RenderedMessage) -> SendResult   # sent / temporary / permanent + detail
```

Rendering (templates per channel) and sending are separated from the outbox loop. A new channel (F1, F2) adds a sender, its templates and an outbox table or a `channel` column (a migration renaming `email_message` to `notification_message`); the alert engine only gains addressee rules. Nothing in the state machine changes.

## 9.12 Templates

| File (in `backend/ews/mailer/templates/`) | Parts |
|---|---|
| `alert_public.txt.j2`, `alert_public.html.j2` | §9.4.1 |
| `alert_operator.txt.j2`, `alert_operator.html.j2` | §9.4.2 |
| `maintenance.*`, `invite.*`, `password_reset.*` | Plain notices with one link; invite and reset emails say "Open this link on the control PC" (requirements D34) |
| `_layout.html.j2`, `_level_label.html.j2` | Shared HTML frame and coloured level label |

Jinja2 with auto-escaping; golden-file tests per template and change kind ([12](12-testing.md)).

## 9.13 Requirement coverage

| Requirement | Section |
|---|---|
| WEB-40 | §9.3 |
| WEB-41 | §9.5, [08 §8.11](08-alert-engine.md) |
| WEB-42 | §9.4.1 |
| WEB-43 | §9.4.2 |
| WEB-44 | §9.2, §9.7 |
| WEB-45 | §9.4 |
| WEB-46 | §9.10 |
| WEB-03 | §9.7 account emails |
| WEB-26 | §9.5 |
| AL-06, AL-08 | §9.6 with [08 §8.11](08-alert-engine.md) |
| DP-26 | §9.9 |
| D17, F1, F2 | §9.11 |
