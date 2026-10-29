# 4. Demo and Operations

Demo mode, installation, the MQTT broker, network access and start-up. The demo is the moment the project is judged, so problems here are rated High even when real monitoring is not affected.

| ID | Finding | Severity |
|---|---|---|
| AN-25 | TimescaleDB jobs run on the real clock and can delete demo data | High |
| AN-26 | A reset demo has no forecasts for hours | High |
| AN-27 | Phones and other PCs cannot reach the dashboard, but emails send them there | Medium |
| AN-28 | The broker drops queued readings after 1 000 messages | High |
| AN-29 | The settings catalogue is loaded by the fourth process to start | Medium |
| AN-30 | TimescaleDB on Windows must be proven on day 1 | Medium |
| AN-31 | MQTT passwords travel unencrypted over Wi-Fi | Low |

---

## AN-25 TimescaleDB jobs run on the real clock and can delete demo data — High

**Where:** demo mode replays historical dates (e.g. `2024-05-25`, [11 §11.2](../design/11-simulator.md)) into the separate `ews_demo` database; the demo clock is ours ([11 §11.3](../design/11-simulator.md)). TimescaleDB's background jobs ([03 §3.14](../design/03-database-schema.md)) know nothing about it: they use the database's **real** `now()` (2026).

| Policy (from 03 §3.14) | Seen from real time, the 2024 demo data is … | Effect during a demo |
|---|---|---|
| Retention: `reading_derived` 180 days | 2+ years old | **Dropped**; live alerts read rain totals and tendencies from it |
| Retention: `reading_qc_flag` 1 year | 2+ years old | Dropped; kit-health page empty |
| Compression after 7 days (readings) | Old | Chunks being written are compressed; inserts into compressed chunks are slow |
| Continuous-aggregate refresh window (last 3 h / 26 h) | Outside the window | Never materialized; works only through the real-time part of the aggregate (slower, but correct) |

**Suggested fix:** in a database marked `ews.is_demo = on`, the migrations **do not create** retention and compression policies (the demo database is reset for every demo anyway, DD95). Aggregate refresh can stay. Add a test: run the demo for 10 minutes and check that no chunk was dropped.

---

## AN-26 A reset demo has no forecasts for hours — High

**Where:** `start.ps1 -Demo -Reset` starts from an empty `ews_demo` ([11 §11.3.1](../design/11-simulator.md)); forecast runs start only after onboarding is complete ([01 §1.4.5](../design/01-architecture.md)); the encoder needs 168 hours (7 days) per kit; a new kit is filled with Open-Meteo pseudo-observations ([07 §7.4](../design/07-forecast-worker.md)), but **the Open-Meteo fetch is switched off in demo mode** ([11 §11.3](../design/11-simulator.md)).

**What happens at a presentation:**

| Step | Time |
|---|---|
| Onboarding: download ≈ 35 years of history, normals, labels, top-10 events, back-tests | Minutes to tens of minutes, needs internet |
| No pseudo-observations (no fetch in demo) | Kits have < 7 days of data → what happens is **undefined** in 07 §7.4; most likely `skipped` |
| 7 simulated days of replay to fill the encoder | ≈ 2.8 h real time at 60×, 1.4 h at 120× |

Scenario 9 says "dashboard shows readings arriving live; forecasts and alerts follow". In practice only **live** alerts would work for the first hours. The automated scenario tests avoid this by injecting fixture runs ([12 §12.4](../design/12-testing.md)), so the tests would pass while the live demo does not.

**Suggested fix:** a **prepared demo snapshot**. Build `ews_demo` once (onboarding done, 7+ days of replayed readings before the interesting part, a few forecast runs), save it with `pg_dump` (`config/demo-snapshot.dump`, git-ignored, rebuilt by a script), and let `-Reset` **restore the snapshot** instead of starting empty. Also define in 07 §7.4 what happens when no Open-Meteo fetch exists for a kit with short history (suggested: in demo mode, use the replay source's ERA5 hours as pseudo-observations; otherwise `skipped` with a clear reason).

---

## AN-27 Phones and other PCs cannot reach the dashboard, but emails send them there — Medium (owner decision)

**Where:** the firewall rule opens only MQTT 1883; "ports 8000, 5432, 1025, 8025 stay local" ([14 §14.1.4](../design/14-operations.md)); `APP_BASE_URL` is `http://localhost:8000` ([01 §1.7](../design/01-architecture.md)). At the same time DD80 says the alerts pages are phone-ready "because acknowledge links are opened from email on phones", and operator emails carry an Acknowledge link (WEB-43).

**What happens:** an operator opens the alert email on a phone and taps **Acknowledge** → `http://localhost:8000/alerts/…` → the phone tries to connect to itself and fails. Operators on other PCs cannot log in at all.

**Options:**

| Option | What changes | Cost |
|---|---|---|
| A | Dashboard is used **only on the server laptop**. Remove the phone claim from DD80; the email says "open the dashboard on the control PC" | None; honest |
| B (suggested for a realistic demo) | Open port 8000 on **private networks**, set `APP_BASE_URL` to the laptop's fixed LAN IP. Passwords and session cookies then travel as plain HTTP on the Wi-Fi; state this as a limitation | One firewall rule |
| C | As B, plus HTTPS with a self-signed certificate (uvicorn supports it) | Certificate warnings on every phone |

---

## AN-28 The broker drops queued readings after 1 000 messages — High

**Where:** `ingest` uses a persistent session so "readings published while `ingest` restarts are queued by the broker and delivered afterwards" ([01 §1.3.1, §1.5](../design/01-architecture.md), DD11).

**The problem:** Mosquitto queues at most **`max_queued_messages` = 1 000** messages per offline client by default, then **drops** new ones silently.

| Situation | Messages per minute | Queue full after |
|---|---|---|
| 1 kit, real time | 1 | ≈ 16 h |
| 5 kits, real time | 5 | ≈ 3.3 h |
| 5 kits, demo at 60× | 300 | ≈ 3 min |

So `ingest` down for an afternoon (or 3 minutes in a demo) loses readings, contradicting the failure table.

**Fix:** in `config/mosquitto/conf.d`, set `max_queued_messages 0` (no limit) or a large number, keep `persistence true`, and add a check to `check-setup.ps1`. Add an integration test: stop `ingest`, publish 2 000 readings, start it, all 2 000 stored.

---

## AN-29 The settings catalogue is loaded by the fourth process to start — Medium

**Where:** `worker` loads `config/defaults.yaml` into `config_key` at start-up ([04 §4.7](../design/04-configuration.md)); `start.ps1` starts **`ingest`, `alerts`, `mailer`, then `worker`, then `api`** ([01 §1.7.4](../design/01-architecture.md)).

**What happens:** on the very first start (empty database) `ingest` and `alerts` resolve configuration from an empty catalogue. After a software update with a new key, they start with the old catalogue. Also, if a key is ever removed from `defaults.yaml`, deleting its `config_key` row would break the foreign key from old `config_value` rows.

**Fix:** load the catalogue in `start.ps1` step 3, right after `alembic upgrade head` (`python -m ews.common.config sync`), before any process starts; keys removed from `defaults.yaml` are marked `deprecated`, never deleted.

---

## AN-30 TimescaleDB on Windows must be proven on day 1 — Medium

**Where:** the whole storage design depends on TimescaleDB features: hypertables, continuous aggregates, compression, integer hypertables ([03](../design/03-database-schema.md)), installed from the Windows zip ([14 §14.1.1](../design/14-operations.md)).

**The risk:** Windows is the least-used TimescaleDB platform; the release must match the exact PostgreSQL major version, and the community features (continuous aggregates, compression) must be in that build. If installation fails late, the schema has to be reworked.

**Action:** week-1 check ([05 §5.3](05-scope-and-plan.md)): install PostgreSQL + TimescaleDB on the demo laptop, create one hypertable, one continuous aggregate with `materialized_only = false`, one compression and one retention policy, and an integer hypertable with `set_integer_now_func`. **Fallback if it fails:** plain PostgreSQL with native partitioning, and the 15 min / 1 h series refreshed by a `worker` job. Consumers read only the `series_15m` / `series_1h` views ([05 §5.7](../design/05-data-pipeline.md)), which keeps a fallback contained.

---

## AN-31 MQTT passwords travel unencrypted over Wi-Fi — Low

**Where:** kits connect to port 1883 with a username and password ([14 §14.1.4](../design/14-operations.md)); no TLS.

**The point:** anyone on the same Wi-Fi can read kit passwords and publish fake readings for that kit. Acceptable for a local student project on a private network, but it should be **stated in the report** with TLS on port 8883 as the fix for a real installation.

---

## Checked and sound

| Topic | Result |
|---|---|
| Last will + retained status + no-data timeout (HW-12, DP-09) | Covers both "kit dropped" and "broker down" |
| Demo database separated by marker, site `demo` and refusal on mismatch (DD95) | Strong; real data cannot be mixed with demo data |
| Restart wrapper, heartbeats, stored markers (DD12, DD13) | Restarts lose nothing (given AN-28 fixed) |
| Backup with `timescaledb_pre_restore` / `post_restore`, practice restore (DD98) | Correct procedure |
| Secrets in `.env`, never logged (NFR-08, DD96) | Correct |
