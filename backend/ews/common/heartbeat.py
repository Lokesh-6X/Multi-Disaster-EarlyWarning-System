"""Process heartbeat (design/01 §1.5, DD12): one row per process in `process_heartbeat`, updated every
15 s of machine time (DD117, also in demo mode). The API reports a process as down after 60 s without a beat.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import asyncpg

from ews.common.clock import Clock, every
from ews.common.logging import get_logger

INTERVAL = timedelta(seconds=15)
DOWN_AFTER = timedelta(seconds=60)

log = get_logger(__name__)

_UPSERT = """
INSERT INTO process_heartbeat (name, pid, started_at, last_beat_at, version)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (name) DO UPDATE
   SET pid = EXCLUDED.pid, started_at = EXCLUDED.started_at,
       last_beat_at = EXCLUDED.last_beat_at, version = EXCLUDED.version
"""


class Heartbeat:
    def __init__(self, pool: asyncpg.Pool, name: str, version: str, started_at: datetime, pid: int | None = None):
        self.pool = pool
        self.name = name
        self.version = version
        self.started_at = started_at
        self.pid = pid if pid is not None else os.getpid()
        self.failures = 0

    async def beat(self, now: datetime) -> None:
        await self.pool.execute(_UPSERT, self.name, self.pid, self.started_at, now, self.version)

    async def _safe_beat(self, now: datetime) -> None:
        try:
            await self.beat(now)
        except (asyncpg.PostgresError, OSError) as e:
            self.failures += 1
            log.warning("heartbeat.failed", error_detail=f"{type(e).__name__}: {e}", failures=self.failures)

    async def run(self, machine: Clock) -> None:
        """Beat now, then on every 15-second slot of machine time; a failed beat is logged, not fatal."""
        await self._safe_beat(machine.now())

        async def job(slot: datetime) -> None:
            await self._safe_beat(machine.now())

        await every(machine, INTERVAL, job)
