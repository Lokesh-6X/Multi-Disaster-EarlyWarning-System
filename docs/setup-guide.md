# Setup Guide

How to install the Site Weather-Hazard Early-Warning System on a Windows machine. No Docker: every service is installed locally (NFR-05). Based on [design/14 §14.1](../design/14-operations.md).

## 1. Software

| # | Software | Version | Where from |
|---|---|---|---|
| 1 | Python | 3.13 (64-bit, DD129) | Python install manager (`py install 3.13`) or python.org |
| 2 | Node.js | 24 LTS (DD127) | nodejs.org installer |
| 3 | PostgreSQL | 17 | EDB Windows installer (postgresql.org → Windows) |
| 4 | TimescaleDB | latest release for PostgreSQL 17 | GitHub releases, `timescaledb-postgresql-17-windows-amd64.zip` |
| 5 | Mosquitto | 2.x (64-bit) | mosquitto.org installer |
| 6 | Mailpit | latest | GitHub releases (axllent/mailpit), `mailpit-windows-amd64.zip` |
| 7 | Git | latest | git-scm.com |

### 1.1 Python 3.13

Other Python versions may stay installed; the project always selects 3.13 with `py -3.13`. It is the same minor version as the Kaggle training image (DD129), so saved models load the same way in training and in the backend.

```powershell
py install 3.13
py -3.13 --version          # Python 3.13.x
```

**Smart App Control** (Windows 11 security, check: Windows Security → App & browser control): when it is on, Windows refuses to load compiled Python files that are too new to have a reputation, e.g. `ImportError: DLL load failed … An Application Control policy has blocked this file` (seen with pandas 3.1.0; pandas 2.3.3 loads). Fix: use the pinned versions from `backend/pyproject.toml` / `ml/requirements.txt`, which were tested on this machine. Blocked files are listed in Event Viewer → Applications and Services Logs → Microsoft → Windows → CodeIntegrity → Operational.

### 1.2 Node.js 24 LTS

Install from nodejs.org (LTS). Check: `node --version` → `v24.x`.

### 1.3 PostgreSQL 17

1. Run the EDB installer. Keep the defaults (port 5432, Windows service). Write down the `postgres` password.
2. Stack Builder at the end is not needed.
3. Add `C:\Program Files\PostgreSQL\17\bin` to the user PATH, then open a new terminal.
4. Check: `psql --version` → `psql (PostgreSQL) 17.x`.

### 1.4 TimescaleDB

1. Download `timescaledb-postgresql-17-windows-amd64.zip` from the official GitHub releases page (github.com/timescale/timescaledb/releases), not from a mirror.
2. Unzip it, then right-click `setup.exe` → **Run as administrator**. It needs `pg_config` on PATH (step 1.3). When asked, give the path `C:\Program Files\PostgreSQL\17\data\postgresql.conf` and answer `y` to the questions (it sets `shared_preload_libraries = 'timescaledb'` and tunes memory settings).
   - Without administrator rights it updates `postgresql.conf` but does not copy its files, and PostgreSQL then fails to start. Check: `C:\Program Files\PostgreSQL\17\lib` contains `timescaledb-2.x.dll`, and `share\extension` contains `timescaledb.control`.
   - The tuning step sizes memory as if PostgreSQL had the machine to itself (`shared_buffers` ≈ 25 % of RAM). On a desktop that also runs other programs, Windows may refuse that much shared memory and the service will not start (Event Log: `could not create shared memory segment: error code 1450`). After tuning, set these lines in `postgresql.conf` (keep a backup copy first):

     ```
     shared_buffers = 512MB
     maintenance_work_mem = 256MB
     effective_cache_size = 4GB
     ```
3. Restart the PostgreSQL service so the extension is loaded; the databases are set up in step 2 of this guide.

### 1.5 Mosquitto 2.x

1. Run the 64-bit installer from mosquitto.org. It installs the `mosquitto` Windows service.
2. Add `C:\Program Files\mosquitto` to the user PATH, then open a new terminal.
3. Check: `mosquitto -h` prints `mosquitto version 2.x`.
4. Configuration (users, ACL, persistence) follows in a later step.

### 1.6 Mailpit

1. Download `mailpit-windows-amd64.zip` from the GitHub releases page. Compare its SHA-256 with the digest shown on the release page (`Get-FileHash <zip>`).
2. Put `mailpit.exe` in `tools\` in the repository (the folder is git-ignored).
3. Check: `tools\mailpit.exe version`.

### 1.7 Git

Install from git-scm.com. Check: `git --version`.

### 1.8 Check

Open a **new** terminal (so the PATH changes apply):

```powershell
py -3.13 --version
node --version
psql --version
mosquitto -h
git --version
tools\mailpit.exe version
```

## 2. Databases

Creates role `ews`, the databases `ews`, `ews_test`, `ews_demo` (demo marker `ews.is_demo = on` only in `ews_demo`) and the `timescaledb` and `citext` extensions in each. Run once, from an **administrator** PowerShell; psql asks for the `postgres` password:

```powershell
powershell -ExecutionPolicy Bypass -File "<repo>\scripts\setup-databases.ps1"
```

The script restarts PostgreSQL (so TimescaleDB is loaded), generates the `ews` password and writes `DATABASE_URL` and `DEMO_DATABASE_URL` into `.env` (never committed). Running it again keeps the role, databases and password.

Check (the password is in `.env`):

```powershell
psql -U ews -h localhost -d ews_demo -c "SHOW ews.is_demo"    # on
psql -U ews -h localhost -d ews -c "\dx"                      # timescaledb and citext
```

`SHOW ews.is_demo` in `ews` or `ews_test` gives "unrecognized configuration parameter": the marker only exists in the demo database. Code reads it with `current_setting('ews.is_demo', true)`, which returns NULL there.

## 3. Mosquitto

Writes `config\mosquitto\conf.d\ews.conf` (no anonymous login, password file, ACL, `persistence true`, `max_queued_messages 0`, log file), `config\mosquitto\acl` and the password file `config\mosquitto\passwd` (never committed) with the users `ingest`, `KIT-01` and `simulator`. Adds one line to `C:\Program Files\mosquitto\mosquitto.conf` (backup `mosquitto.conf.bak-m0.4`):

```
include_dir <repo>\config\mosquitto\conf.d
```

and restarts the `mosquitto` service. Run from an **administrator** PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File "<repo>\scripts\setup-mosquitto.ps1"            # more kits: -Kits KIT-01,KIT-02
```

Passwords are generated once and kept in `.env` (`MQTT_INGEST_*`) and `simulator\.env` (kits, simulator); running the script again keeps them. Once the site exists, run it again with `-SiteId <site_id>` so each kit may publish only to `sites/<site_id>/kits/<its kit_id>/#`.

Known traps:
- `mosquitto_passwd` makes the password file readable by the current user only, but the service runs as SYSTEM and then quits right after starting. The script gives SYSTEM read access (and nobody else). If you recreate the file by hand: `icacls config\mosquitto\passwd /grant *S-1-5-18:R`.
- The service log `C:\ProgramData\mosquitto\mosquitto.log` is readable by SYSTEM only. To read it, run Mosquitto by hand with the same settings (stop the service first): `mosquitto -c "C:\Program Files\mosquitto\mosquitto.conf" -v`.

Check (needs `paho-mqtt` 2.x in the Python environment):

```powershell
python scripts\checks\mqtt_check.py       # anonymous refused, 2 000 queued readings delivered, last will, ACL → MQTT CHECK OK
```

## 4. Python environment and frontend

One virtual environment for the backend and the simulator (design/01 §1.6). PyTorch comes first, from the CPU index, so pip does not fetch the large GPU build:

```powershell
py -3.13 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu
backend\.venv\Scripts\python.exe -m pip install -e backend[dev]
backend\.venv\Scripts\python.exe -m pip install -e simulator
backend\.venv\Scripts\python.exe -m pip check          # No broken requirements found.
```

All versions in `backend/pyproject.toml` are exact pins that were tested on this machine; keep them when upgrading anything (Smart App Control, §1.1).

Frontend (Node 24):

```powershell
cd frontend; npm ci; npm run build                      # creates frontend\dist
```

`.env`: copy `.env.example` to `.env`. The database and MQTT lines are written by the setup scripts (§2, §3); fill in the rest.

## 5. Check, start and stop

Use a **normal** PowerShell window (not "Run as administrator"); only the setup scripts in §2 and §3 need administrator rights.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check-setup.ps1    # every line must say OK
powershell -ExecutionPolicy Bypass -File scripts\start.ps1          # services, migrations, settings sync, frontend, 5 processes
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1           # stops what start.ps1 started; services keep running
powershell -ExecutionPolicy Bypass -File scripts\test.ps1           # all test suites (-Unit, -Integration, ... for one)
```

`start.ps1` waits for a heartbeat from each of `ingest`, `alerts`, `mailer`, `worker`, `api` and prints the URLs. Each process runs under `scripts\run-process.ps1`, which restarts it 5 s after it stops. Files in `logs\`: `<process>.log` (JSON lines), `<process>.stdout.log` (crash output and restarts), `<process>.pid` (the Python interpreter; `backend\.venv\Scripts\python.exe` is only a launcher).

Known trap: processes started from an administrator window can only be stopped from an administrator window.
