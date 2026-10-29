"""Wake-up events between processes over PostgreSQL NOTIFY/LISTEN (design/01 §1.3.2, DD3).

Every hand-off is a table row; the event only says "look now". `notify` inside a transaction is
delivered by PostgreSQL when the transaction commits, and never if it rolls back.

    await events.notify(conn, "forecast.run_completed", {"run_id": 4818})
    async with events.listen(dsn, types={"forecast.run_completed"}) as inbox:
        event = await inbox.get()
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

import asyncpg

from ews.common.logging import get_logger

CHANNEL = "ews"
MAX_PAYLOAD_BYTES = 8000  # PostgreSQL's NOTIFY limit

# Event types of design/01 §1.3.2
TYPES = frozenset({
    "reading.ingested", "kit.status_changed", "kit.qc_flag", "message.rejected",
    "forecast.run_completed", "onboarding.requested", "onboarding.progress",
    "alert.command", "alert.changed", "alert.acknowledged",
    "config.changed", "email.queued", "clock.tick",
})

log = get_logger(__name__)


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any]


def encode(event_type: str, payload: dict[str, Any]) -> str:
    if event_type not in TYPES:
        raise ValueError(f"unknown event type {event_type!r}")
    if "type" in payload:
        raise ValueError("payload must not contain 'type'")
    text = json.dumps({"type": event_type, **payload}, separators=(",", ":"), default=str)
    size = len(text.encode("utf-8"))
    if size >= MAX_PAYLOAD_BYTES:
        raise ValueError(f"{event_type} payload is {size} bytes; NOTIFY allows less than {MAX_PAYLOAD_BYTES}: "
                         "send IDs and let the consumer read the rows")
    return text


def decode(text: str) -> Event:
    data = json.loads(text)
    event_type = data.pop("type")
    return Event(event_type, data)


async def notify(conn: asyncpg.Connection | asyncpg.Pool, event_type: str, payload: dict[str, Any]) -> None:
    """Send after (or inside) the transaction that wrote the rows; delivered on commit."""
    await conn.execute("SELECT pg_notify($1, $2)", CHANNEL, encode(event_type, payload))


@asynccontextmanager
async def listen(dsn: str, types: set[str] | None = None) -> AsyncIterator[asyncio.Queue[Event]]:
    """Dedicated connection listening on the `ews` channel; events (optionally only `types`) go to a queue.

    A missed event loses nothing: consumers re-read from their markers on start and on every wake-up.
    """
    unknown = (types or set()) - TYPES
    if unknown:
        raise ValueError(f"unknown event type(s): {', '.join(sorted(unknown))}")
    queue: asyncio.Queue[Event] = asyncio.Queue()

    def on_notify(_conn, _pid, _channel, text: str) -> None:
        try:
            event = decode(text)
        except (ValueError, KeyError) as e:
            log.warning("event.bad_payload", error_detail=str(e))
            return
        if types is None or event.type in types:
            queue.put_nowait(event)

    conn = await asyncpg.connect(dsn)
    try:
        await conn.add_listener(CHANNEL, on_notify)
        yield queue
    finally:
        try:
            await conn.remove_listener(CHANNEL, on_notify)
        finally:
            await conn.close()
