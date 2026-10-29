"""Start-up shared by the five processes (design/01 §1.2, §1.5, design/14 §14.2.2).

`python -m ews.<name>` calls `run(name)`: settings, logging, clocks, database pool, demo-database guard,
`process.started`, heartbeat. In M0 the processes do nothing else; their work is added milestone by
milestone. A failure at start exits non-zero, and run-process.ps1 restarts the process after 5 s.
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Awaitable, Callable

import asyncpg

import ews
from ews.common.clock import Clocks, make_clocks
from ews.common.db import WrongDatabase, check_database_mode, create_pool
from ews.common.heartbeat import Heartbeat
from ews.common.logging import EventLogger, setup_logging, shutdown
from ews.common.settings import Settings, SettingsError, load_settings, mask_url

PROCESSES = ("api", "ingest", "worker", "alerts", "mailer")

Work = Callable[[Settings, Clocks, asyncpg.Pool, EventLogger], Awaitable[None]]


async def _main(name: str, work: Work | None) -> int:
    settings = load_settings()
    pid_file = os.environ.get("EWS_PID_FILE")
    if pid_file:  # run-process.ps1: the real interpreter PID (the venv python.exe is only a launcher)
        with open(pid_file, "w", encoding="ascii") as f:
            f.write(str(os.getpid()))
    log = setup_logging(name, settings.log_dir, settings.log_level, console=os.environ.get("EWS_CONSOLE") == "1")
    clocks = make_clocks(settings.clock_mode)
    try:
        pool = await create_pool(settings.active_database_url, application_name=f"ews-{name}")
    except (OSError, asyncpg.PostgresError) as e:
        log.error("db.connect_failed", database=mask_url(settings.active_database_url), error_detail=str(e))
        return 1
    try:
        await check_database_mode(pool, settings.clock_mode)
        log.info("process.started", version=ews.__version__, pid=os.getpid(), clock=settings.clock_mode,
                 database=mask_url(settings.active_database_url), log_level=settings.log_level)
        heartbeat = Heartbeat(pool, name, ews.__version__, started_at=clocks.machine.now())
        tasks = [asyncio.create_task(heartbeat.run(clocks.machine), name="heartbeat")]
        if work:
            tasks.append(asyncio.create_task(work(settings, clocks, pool, log), name=name))
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()  # re-raise a crash so the wrapper restarts the process
        return 0
    except WrongDatabase as e:
        log.critical("process.wrong_database", msg=str(e))
        return 3
    finally:
        log.info("process.stopping")
        await pool.close()


def run(name: str, work: Work | None = None) -> None:
    if name not in PROCESSES:
        raise ValueError(f"unknown process {name!r}")
    try:
        code = asyncio.run(_main(name, work))
    except SettingsError as e:
        print(f"{name}: {e}", file=sys.stderr)  # logging is not set up without settings
        code = 2
    except KeyboardInterrupt:
        code = 0
    finally:
        shutdown()
    sys.exit(code)
