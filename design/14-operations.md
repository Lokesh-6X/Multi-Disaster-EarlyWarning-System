# 14. Operations: Setup, Logging, Backup

How the system is installed on a Windows machine, what every process writes to its logs, and how the data is backed up and restored. Requirements: NFR-05 (local install, setup guide, start script), NFR-08 (secrets), D14 (no Docker, no deployment). The setup part becomes `docs/setup-guide.md` during implementation ([01 §1.6](01-architecture.md)).

Decisions referenced: DD96–DD98 in [decisions.md](decisions.md).

## 14.1 Setup (NFR-05)

### 14.1.1 What to install

| # | Software | Version | Where from | Notes |
|---|---|---|---|---|
| 1 | Python | 3.13 (64-bit, DD129) | Python install manager (`py install 3.13`) or python.org | Same minor version as the Kaggle training image |
| 2 | Node.js | 24 LTS (DD127) | nodejs.org installer | Only to build the frontend |
| 3 | PostgreSQL | 16 or 17 | EDB Windows installer | Installs the Windows service; remember the `postgres` password |
| 4 | TimescaleDB | the release matching the PostgreSQL version | TimescaleDB Windows zip | Run its `setup.exe` as administrator |
| 5 | Mosquitto | 2.x (64-bit) | mosquitto.org installer | Installs the `mosquitto` Windows service |
| 6 | Mailpit | latest | GitHub releases, Windows zip | A single `mailpit.exe`, placed in `tools/` (git-ignored) |
| 7 | Git | latest | git-scm.com | |

### 14.1.2 Steps

```
 1  Clone the repository
 2  Copy .env.example → .env and fill in passwords (never commit .env, NFR-08)
 3  PostgreSQL + TimescaleDB
      postgresql.conf: shared_preload_libraries = 'timescaledb'   → restart the PostgreSQL service
      psql -U postgres:
        CREATE ROLE ews LOGIN PASSWORD '…';
        CREATE DATABASE ews      OWNER ews;
        CREATE DATABASE ews_test OWNER ews;
        CREATE DATABASE ews_demo OWNER ews;
        ALTER DATABASE ews_demo SET ews.is_demo = 'on';           -- demo marker (11 §11.3.1)
        in each database: CREATE EXTENSION timescaledb; CREATE EXTENSION citext;
 4  Mosquitto
      C:\Program Files\mosquitto\mosquitto.conf → one line:  include_dir <repo>\config\mosquitto\conf.d
      create users:  mosquitto_passwd -c <repo>\config\mosquitto\passwd ingest
                     mosquitto_passwd    <repo>\config\mosquitto\passwd KIT-01        (one per kit)
                     mosquitto_passwd    <repo>\config\mosquitto\passwd simulator
      conf.d also sets:  persistence true
                         max_queued_messages 0      (no limit; the default 1 000 drops readings, DD109)
      restart the mosquitto service
 5  Python
      py -3.13 -m venv backend\.venv
      backend\.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
      backend\.venv\Scripts\pip install -e backend[dev]
      backend\.venv\Scripts\pip install -e simulator
 6  Frontend
      cd frontend; npm ci; npm run build
 7  Models
      copy the model folders from the Kaggle training output into models\   (registry.json is in git)
 8  Check
      scripts\check-setup.ps1       → every line must say OK
 9  First start
      scripts\start.ps1 -Seed config\example-site.yaml
      open http://localhost:8000 → first-run setup creates the admin (WEB-01)
10  Demo (optional)
      scripts\build-demo-snapshot.ps1     once, and again after a model, config or database migration change (DD108, DD116)
      scripts\start.ps1 -Demo -Reset      restores the snapshot
```

### 14.1.3 `check-setup.ps1`

| Check | OK when |
|---|---|
| Python, Node versions | 3.13.x (DD129), 24.x (DD127) |
| `.env` | Present; every variable of `.env.example` set |
| PostgreSQL service | Running; login as `ews` works for `ews`, `ews_test`, `ews_demo` |
| Extensions | `timescaledb` and `citext` in each database; TimescaleDB version printed |
| TimescaleDB features (DD113) | In `ews_test`: a hypertable, a continuous aggregate with `materialized_only = false`, a compression and a retention policy, and an integer hypertable with `set_integer_now_func` can be created and dropped. This is also the **week-1 check**; if it fails, the fallback is plain PostgreSQL partitions with the `series_*` views refreshed by `worker` |
| Demo policies | `ews_demo` has no retention or compression jobs (DD107) |
| Demo marker | `ews.is_demo` is `on` only in `ews_demo` |
| Mosquitto service | Running; `ingest` can connect with its password; anonymous login is refused; `max_queued_messages 0` and `persistence true` set (DD109) |
| Mailpit | `tools\mailpit.exe` exists, or SMTP settings point to a real server |
| Python packages | `import ews`, `import simulator`, `import torch, darts, lightgbm` work |
| Frontend | `frontend\dist\index.html` exists |
| Models | `registry.json` readable; every active model folder present; checksums match |
| Ports free | 8000, 1025, 8025 (1883 and 5432 belong to the services) |

### 14.1.4 Connecting the real kit

| Item | Rule |
|---|---|
| Network | Laptop and kit on the same Wi-Fi; give the laptop a fixed IP (router reservation) so the kit firmware can use it |
| Firewall | One inbound Windows Firewall rule: TCP 1883, **private networks only**. Ports 8000, 5432, 1025, 8025 stay local: the dashboard is used only on this machine (requirements D34) |
| Encryption (limitation) | MQTT on 1883 is not encrypted, so kit passwords and readings are visible to others on the same Wi-Fi. Acceptable on a private network for this project; stated in the report, with TLS on port 8883 as the fix for a real installation |
| Credentials | The kit's MQTT username is its `kit_id`; the password is given to the hardware builders, not stored in the repository |
| Kit config | Add the kit in the UI or YAML (zone, position, elevation, calibration) before it connects; unknown kits are rejected ([05 §5.2.1](05-data-pipeline.md)) |

## 14.2 Logging (DD96)

### 14.2.1 Format

Each process writes **one JSON object per line** to `logs/<process>.log` (machine-readable, easy to filter); with `start.ps1 -Dev` the console shows the same records as readable text.

```json
{"ts":"2026-11-02T09:31:00.214Z","level":"INFO","process":"ingest","event":"reading.stored",
 "kit_id":"KIT-01","reading_ts":"2026-11-02T09:31:00Z","duration_ms":12,"qc":"valid"}
{"ts":"2026-11-02T09:31:05.902Z","level":"WARNING","process":"ingest","event":"message.rejected",
 "kit_id":"KIT-01","reason_code":"wrong_type","detail":"bme_rh_pct: expected number, got string"}
{"ts":"2026-11-02T09:47:41.330Z","level":"INFO","process":"worker","event":"forecast.run_completed",
 "run_id":"4818","issue_time":"2026-11-02T09:45:00Z","kits":2,"degraded":0,"duration_ms":14210}
```

| Field | Always | Meaning |
|---|---|---|
| `ts` | ✅ | UTC time of the log record (wall clock, also in demo mode) |
| `level` | ✅ | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `process` | ✅ | `api`, `ingest`, `worker`, `alerts`, `mailer`, `simulator` |
| `event` | ✅ | Stable dotted code (table below); tests and searches use it |
| `msg` | when useful | Human-readable text |
| `request_id`, `user_id` | `api` | Request ID also returned as `X-Request-ID` and in 500 errors ([02 §2.3](02-api.md)) |
| `kit_id`, `run_id`, `alert_id`, `email_id`, `command_id` | when relevant | Link a log line to database rows |
| `duration_ms` | timed work | |
| `sim_time` | demo mode | Demo clock time, next to the real `ts` |
| `error` | on errors | Exception type, message and stack trace |

### 14.2.2 What each process logs (INFO unless stated)

| Process | Events |
|---|---|
| all | `process.started` (version, config summary, clock mode), `process.stopping`, `heartbeat.failed` (WARNING), `db.reconnect` (WARNING) |
| `api` | `http.request` (method, path, status, duration; DEBUG for `GET`, INFO for writes), `auth.login` / `auth.login_failed` (WARNING) / `auth.locked` (WARNING), `ws.connected` / `ws.closed` (with close code), `rate_limited` (WARNING) |
| `ingest` | `mqtt.connected` / `mqtt.disconnected` (WARNING), `reading.stored` (DEBUG; one INFO summary per kit per 15 min), `message.rejected` (WARNING), `duplicate.conflicting` (WARNING), `kit.status_changed`, `qc.flag` (WARNING for faulty) |
| `worker` | `forecast.run_started`, `forecast.run_completed`, `forecast.run_failed` (ERROR), `forecast.run_skipped` (WARNING), `model.fallback_used` (WARNING), `model.load_failed` (ERROR), `openmeteo.fetched` / `openmeteo.failed` (WARNING), `onboarding.step`, `job.completed` |
| `alerts` | `alert.changed` (every change, with change kind, level, type, trigger), `command.applied` / `command.rejected` (WARNING), `notice.opened` / `notice.closed`, `catchup.done` |
| `mailer` | `email.sent`, `email.retry` (WARNING), `email.failed` (ERROR), `email.skipped` (reason), `account_link.fallback` (WARNING, the WEB-03 console link) |
| `simulator` | `kit.connected`, `scenario.started`, `fault.applied`, `clock.speed` |

### 14.2.3 Never logged (NFR-08)

Passwords and password hashes, session cookies, CSRF tokens, invite/reset tokens (**except** the deliberate WEB-03 fallback line `account_link.fallback`, which only appears when sending failed), SMTP and MQTT passwords, and full email bodies. MQTT payloads appear only as the 2 KB excerpt of rejected messages.

### 14.2.4 Rotation and viewing

| Item | Rule |
|---|---|
| Rotation | Python rotating file handler: 10 MB per file, 10 files per process (≈ 100 MB max each) |
| Crash output | `run-process.ps1` also captures stdout/stderr to `logs/<process>.stdout.log`, so a crash before logging starts is still visible |
| Viewing | `scripts/logs.ps1 -Process alerts -Follow` (tail), `-Level WARNING`, `-Event alert.changed`, `-Since 1h` |
| Not a replacement for | The **audit log** (who changed what, in the database, WEB-25) and the **email send log** (`email_attempt`); logs are technical and may be deleted by rotation |

## 14.3 Backup and restore (DD97, DD98)

### 14.3.1 What to back up

| Item | Contains | How |
|---|---|---|
| Database `ews` | Everything that matters: readings, forecasts, alerts, configuration and versions, users, audit log, email log | `pg_dump` (below) |
| `.env`, `config/mosquitto/passwd` | Secrets | Copy to a private location (not the repository, not a shared drive) |
| `models/` | Model files | Already kept in the Kaggle run outputs; `registry.json` is in git |
| Repository | Code, `config/`, design | Git remote |
| `ews_test`, `ews_demo` | Throw-away data | Not backed up (recreated by tests or `-Demo -Reset`) |

### 14.3.2 Backup

`scripts/backup.ps1` (safe while the system runs; `pg_dump` takes a consistent snapshot):

```
pg_dump -U ews -Fc -f backups\ews-2026-11-02-0230.dump ews
```

| Rule | Detail |
|---|---|
| Output | `backups\ews-<date>-<time>.dump` (custom format, compressed; git-ignored) |
| Keep | The last 7 daily backups plus one per week for 4 weeks |
| Schedule | Optional Windows Task Scheduler task daily at 02:30 (`backup.ps1 -Install` creates it) |
| Before risky steps | Always before a migration, a TimescaleDB upgrade or a model change, and before the final demo |
| Size | Well under 1 GB per year for five kits ([03 §3.14](03-database-schema.md)) |
| Record | Each run writes `backups\backup.log` with file name, size and TimescaleDB version |

### 14.3.3 Restore

`scripts/restore.ps1 -File backups\ews-2026-11-02-0230.dump`:

```
1 scripts\stop.ps1                                     stop all processes
2 DROP DATABASE ews; CREATE DATABASE ews OWNER ews;
  CREATE EXTENSION timescaledb; CREATE EXTENSION citext;
3 SELECT timescaledb_pre_restore();
4 pg_restore -U ews -d ews backups\ews-…dump
5 SELECT timescaledb_post_restore();
6 alembic current  → must equal the code's latest migration (otherwise: alembic upgrade head)
7 scripts\start.ps1
```

| Rule | Detail |
|---|---|
| Same versions | Restore into the same PostgreSQL major version and TimescaleDB version as in `backup.log` (TimescaleDB requires this) |
| Confirmation | The script asks for confirmation and refuses if the target is `ews_demo` or `ews_test` with a production dump, or `ews` with `-Force` missing |
| Afterwards | Kits reconnect automatically; readings sent while the system was stopped are lost (HW-09); forecasts resume at the next slot (no back-fill, DD58) |
| Practice | Restore the latest backup into a scratch database (`restore.ps1 -Target ews_restore_check`) once before submission, to prove backups work |

## 14.4 Requirement coverage

| Requirement | Section |
|---|---|
| NFR-05 | §14.1 setup guide, `check-setup.ps1`; start script in [01 §1.7.4](01-architecture.md) |
| NFR-08 | §14.1.2 step 2, §14.2.3, §14.3.1 |
| D14 | Everything installed locally, no Docker |
| WEB-03 | `account_link.fallback` log event |
| WEB-25, WEB-44 | §14.2.4 (audit and email logs stay in the database) |
| DD95 | Demo database marker (§14.1.2 step 3) |
