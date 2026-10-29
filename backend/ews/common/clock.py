"""One clock abstraction for every backend process (design/11 §11.3, DD82, DD117).

    clocks = make_clocks(settings.clock_mode)
    clocks.weather.now()      # reading timestamps, issue times, every alert timer
    clocks.machine.now()      # timeouts, heartbeats, pings, retries, sessions: always real

There is no default "now": code names the clock it means. All times are UTC-aware datetimes.

Sources: `RealClock` (wall clock), `DemoClock` (follows the simulator's `sim/clock` ticks and
interpolates between them), `FakeClock` (tests: time moves only when the test advances it).
`every()` runs a job on aligned slots of any clock; APScheduler 3 cannot be used for this because it
reads `datetime.now()` directly and waits on real-time timers (week-1 check 5, M0.9).
"""
from __future__ import annotations

import asyncio
import heapq
import itertools
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Protocol

UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# A tick this far behind the interpolated time is a new replay, not jitter (start.ps1 -Demo -Reset)
RESET_JUMP = timedelta(minutes=5)
# Longest real-time step of a demo sleep, so speed changes and new ticks are picked up
DEMO_POLL_S = 0.25


class Clock(Protocol):
    def now(self) -> datetime: ...
    async def sleep(self, seconds: float) -> None: ...
    async def sleep_until(self, when: datetime) -> None: ...


class ClockNotReady(RuntimeError):
    """The demo clock has not received a `sim/clock` tick yet."""


def _aware(t: datetime) -> datetime:
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError(f"naive datetime {t!r}: clock times must be UTC-aware")
    return t.astimezone(UTC)


def parse_utc(text: str) -> datetime:
    return _aware(datetime.fromisoformat(text.replace("Z", "+00:00")))


class RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))

    async def sleep_until(self, when: datetime) -> None:
        await self.sleep((_aware(when) - self.now()).total_seconds())


class DemoClock:
    """Weather time in demo mode: the last tick plus real time elapsed since, times the speed."""

    def __init__(self, monotonic: Callable[[], float] = time.monotonic):
        self._mono = monotonic
        self._base: datetime | None = None
        self._base_mono = 0.0
        self._speed = 0.0
        self._last: datetime | None = None
        self._ready = asyncio.Event() if _has_loop() else None

    @property
    def ready(self) -> bool:
        return self._base is not None

    @property
    def speed(self) -> float:
        return self._speed

    async def wait_ready(self) -> None:
        if self._ready is None:
            self._ready = asyncio.Event()
        if self.ready:
            self._ready.set()
        await self._ready.wait()

    def tick(self, sim_time: datetime, speed: float) -> None:
        if speed < 0:
            raise ValueError(f"speed must be >= 0, got {speed}")
        sim_time = _aware(sim_time)
        current = self._interpolate() if self.ready else None
        if current is not None and current - RESET_JUMP <= sim_time < current:
            sim_time = current  # slightly late tick: hold, never run backwards
        elif current is not None and sim_time < current - RESET_JUMP:
            self._last = None  # a new replay
        self._base, self._base_mono, self._speed = sim_time, self._mono(), float(speed)
        if self._ready is not None:
            self._ready.set()

    def tick_message(self, payload: str | bytes) -> None:
        """`sim/clock` payload: {"sim_time": "2024-05-25T06:00:00Z", "speed": 60}."""
        try:
            data = json.loads(payload)
            sim_time, speed = parse_utc(data["sim_time"]), float(data["speed"])
        except (ValueError, KeyError, TypeError) as e:
            raise ValueError(f"bad sim/clock message: {e}") from None
        self.tick(sim_time, speed)

    def _interpolate(self) -> datetime:
        return self._base + timedelta(seconds=(self._mono() - self._base_mono) * self._speed)

    def now(self) -> datetime:
        if not self.ready:
            raise ClockNotReady("no sim/clock tick received yet")
        t = self._interpolate()
        if self._last is not None and t < self._last:
            t = self._last
        self._last = t
        return t

    async def sleep_until(self, when: datetime) -> None:
        when = _aware(when)
        await self.wait_ready()
        while True:
            remaining = (when - self.now()).total_seconds()
            if remaining <= 0:
                return
            step = remaining / self._speed if self._speed > 0 else DEMO_POLL_S
            await asyncio.sleep(min(step, DEMO_POLL_S))

    async def sleep(self, seconds: float) -> None:
        await self.wait_ready()
        await self.sleep_until(self.now() + timedelta(seconds=seconds))


class FakeClock:
    """Test clock: `now()` changes only through `set()` / `advance()`; sleepers wake in deadline order."""

    def __init__(self, start: datetime = EPOCH):
        self._now = _aware(start)
        self._sleepers: list[tuple[datetime, int, asyncio.Future]] = []
        self._seq = itertools.count()

    def now(self) -> datetime:
        return self._now

    def set(self, t: datetime) -> None:
        self._now = _aware(t)

    async def sleep_until(self, when: datetime) -> None:
        when = _aware(when)
        if when <= self._now:
            await asyncio.sleep(0)
            return
        future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._sleepers, (when, next(self._seq), future))
        await future

    async def sleep(self, seconds: float) -> None:
        await self.sleep_until(self._now + timedelta(seconds=seconds))

    async def advance(self, seconds: float) -> None:
        """Move time forward, waking each sleeper at its own deadline and letting it run."""
        target = self._now + timedelta(seconds=seconds)
        while self._sleepers and self._sleepers[0][0] <= max(target, self._now):
            when, _, future = heapq.heappop(self._sleepers)
            if future.done():
                continue
            self._now = max(self._now, when)
            future.set_result(None)
            for _ in range(10):  # let the woken task (and what it starts) run
                await asyncio.sleep(0)
        self._now = max(self._now, target)
        await asyncio.sleep(0)


@dataclass(frozen=True)
class Clocks:
    weather: Clock   # demo clock in demo mode (DD117)
    machine: Clock   # always the real clock (DD117)


def make_clocks(mode: str) -> Clocks:
    if mode == "real":
        real = RealClock()
        return Clocks(weather=real, machine=real)
    if mode == "demo":
        return Clocks(weather=DemoClock(), machine=RealClock())
    raise ValueError(f"unknown clock mode {mode!r} (real or demo)")


def next_slot(after: datetime, interval: timedelta) -> datetime:
    """First slot strictly after `after`, aligned to whole multiples of `interval` since the epoch."""
    n = (_aware(after) - EPOCH) // interval + 1
    return EPOCH + n * interval


def machine_seconds(clock: Clock, span: timedelta) -> float:
    """Real seconds that `span` of this clock's time takes (demo time runs `speed` times faster)."""
    speed = getattr(clock, "speed", 1.0) or 1.0
    return span.total_seconds() / speed


async def every(clock: Clock, interval: timedelta, job: Callable[[datetime], Awaitable[None]],
                on_skip: Callable[[datetime], None] | None = None, grace_s: float = 0.0) -> None:
    """Run `job(slot)` on each aligned slot of `clock` (e.g. :00/:15/:30/:45 of weather time), DD130.

    One run at a time. Slots that passed while a run was busy are coalesced: only the latest one runs,
    and only if it is at most `grace_s` late in machine time (DD117); the others are skipped (DD58).
    """
    slot = next_slot(clock.now(), interval)
    while True:
        await clock.sleep_until(slot)
        await job(slot)
        now = clock.now()
        slot += interval
        missed = []
        while slot <= now:
            missed.append(slot)
            slot += interval
        if missed and machine_seconds(clock, now - missed[-1]) <= grace_s:
            slot = missed.pop()  # run the latest missed slot now, labelled with its own time
        for s in missed:
            if on_skip:
                on_skip(s)


def _has_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False
