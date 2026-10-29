"""Database access, NOTIFY/LISTEN events and heartbeat (design/01 §1.3.2, §1.5, DD3, DD12, DD117)."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from ews.common import db, events, heartbeat
from ews.common.clock import FakeClock

from .conftest import demo_database_url, ews_test_url

pytestmark = pytest.mark.integration

HEARTBEAT_DDL = """
CREATE TABLE process_heartbeat (           -- design/03 §3.12 (created by the migration from M0.11)
  name         text PRIMARY KEY,
  pid          integer NOT NULL,
  started_at   timestamptz NOT NULL,
  last_beat_at timestamptz NOT NULL,
  version      text NOT NULL
)"""
T0 = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)


async def test_pool_connects_and_uses_schema(schema):
    dsn, name = schema
    pool = await db.create_pool(dsn, schema=name)
    try:
        assert await pool.fetchval("SELECT current_schema()") == name
        assert await pool.fetchval("SELECT 1") == 1
    finally:
        await pool.close()


async def test_notify_after_commit_is_received(schema):
    """DD3: the wake-up signal arrives only after the transaction commits."""
    dsn, name = schema
    pool = await db.create_pool(dsn, schema=name)
    try:
        async with events.listen(dsn) as inbox:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await events.notify(conn, "forecast.run_completed", {"run_id": 4818})
                    await asyncio.sleep(0.3)
                    assert inbox.empty(), "NOTIFY must not be delivered before commit"
            event = await asyncio.wait_for(inbox.get(), 5)
        assert event.type == "forecast.run_completed"
        assert event.payload == {"run_id": 4818}
    finally:
        await pool.close()


async def test_notify_in_rolled_back_transaction_is_never_received(schema):
    dsn, name = schema
    pool = await db.create_pool(dsn, schema=name)
    try:
        async with events.listen(dsn) as inbox:
            async with pool.acquire() as conn:
                tr = conn.transaction()
                await tr.start()
                await events.notify(conn, "alert.changed", {"alert_id": 1})
                await tr.rollback()
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(inbox.get(), 0.5)
    finally:
        await pool.close()


async def test_listen_filters_by_type(schema):
    dsn, name = schema
    pool = await db.create_pool(dsn, schema=name)
    try:
        async with events.listen(dsn, types={"email.queued"}) as inbox:
            await events.notify(pool, "alert.changed", {"alert_id": 1})
            await events.notify(pool, "email.queued", {"email_id": 9})
            event = await asyncio.wait_for(inbox.get(), 5)
        assert event.type == "email.queued" and event.payload == {"email_id": 9}
    finally:
        await pool.close()


def test_payload_over_8000_bytes_is_refused():
    """1.3.2: payloads stay below PostgreSQL's 8000-byte limit; refuse before sending."""
    with pytest.raises(ValueError, match="8000"):
        events.encode("reading.ingested", {"values": "x" * 8000})


def test_unknown_event_type_is_refused():
    with pytest.raises(ValueError, match="unknown event type"):
        events.encode("reading.stored", {})


def test_encoded_event_is_compact_json_with_type():
    text = events.encode("kit.status_changed", {"kit_id": "KIT-01", "status": "offline"})
    assert json.loads(text) == {"type": "kit.status_changed", "kit_id": "KIT-01", "status": "offline"}
    assert " " not in text


async def test_heartbeat_row_inserted_then_updated(schema):
    """DD12: each process updates its own row (name, pid, start time, last beat, version)."""
    dsn, name = schema
    pool = await db.create_pool(dsn, schema=name)
    try:
        await pool.execute(HEARTBEAT_DDL)
        hb = heartbeat.Heartbeat(pool, "ingest", version="0.1.0", started_at=T0)
        await hb.beat(T0)
        await hb.beat(T0 + timedelta(seconds=15))
        rows = await pool.fetch("SELECT * FROM process_heartbeat")
        assert len(rows) == 1
        row = rows[0]
        assert row["name"] == "ingest" and row["pid"] == os.getpid() and row["version"] == "0.1.0"
        assert row["started_at"] == T0 and row["last_beat_at"] == T0 + timedelta(seconds=15)
    finally:
        await pool.close()


async def test_heartbeat_loop_beats_every_15_s_of_machine_time(schema):
    """DD12, DD117: every 15 s of machine time; driven here by a fake machine clock."""
    dsn, name = schema
    pool = await db.create_pool(dsn, schema=name)
    machine = FakeClock(T0)
    try:
        await pool.execute(HEARTBEAT_DDL)
        hb = heartbeat.Heartbeat(pool, "worker", version="0.1.0", started_at=T0)
        task = asyncio.create_task(hb.run(machine))
        await _until(lambda: pool.fetchval("SELECT last_beat_at FROM process_heartbeat"), T0)
        await machine.advance(15)
        await _until(lambda: pool.fetchval("SELECT last_beat_at FROM process_heartbeat"), T0 + timedelta(seconds=15))
        await machine.advance(15)
        await _until(lambda: pool.fetchval("SELECT last_beat_at FROM process_heartbeat"), T0 + timedelta(seconds=30))
        task.cancel()
    finally:
        await pool.close()


async def test_heartbeat_failure_is_logged_and_loop_continues(schema, caplog):
    """14.2.2: heartbeat.failed (WARNING); the process keeps running."""
    dsn, name = schema
    pool = await db.create_pool(dsn, schema=name)
    machine = FakeClock(T0)
    try:
        hb = heartbeat.Heartbeat(pool, "alerts", version="0.1.0", started_at=T0)  # no table yet
        task = asyncio.create_task(hb.run(machine))
        await _until(lambda: _value(hb.failures), 1)
        await pool.execute(HEARTBEAT_DDL)
        await machine.advance(15)
        await _until(lambda: pool.fetchval("SELECT count(*) FROM process_heartbeat"), 1)
        assert not task.done()
        task.cancel()
    finally:
        await pool.close()


async def test_demo_process_refuses_real_database():
    """11 §11.3.1: EWS_CLOCK=demo refuses a database not marked ews.is_demo = on."""
    pool = await db.create_pool(ews_test_url())
    try:
        with pytest.raises(db.WrongDatabase, match="not a demo database"):
            await db.check_database_mode(pool, "demo")
        await db.check_database_mode(pool, "real")
    finally:
        await pool.close()


async def test_real_process_refuses_demo_database():
    pool = await db.create_pool(demo_database_url())
    try:
        with pytest.raises(db.WrongDatabase, match="demo database"):
            await db.check_database_mode(pool, "real")
        await db.check_database_mode(pool, "demo")
    finally:
        await pool.close()


async def _value(v):
    return v


async def _until(fetch, expected, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        value = await fetch()
        if value == expected:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"expected {expected!r}, last value {value!r}")
        await asyncio.sleep(0.05)
