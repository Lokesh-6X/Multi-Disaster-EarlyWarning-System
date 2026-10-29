"""Clock abstraction (design/11 §11.3, DD82, DD117)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from ews.common import clock as clk

T0 = datetime(2024, 5, 25, 6, 0, tzinfo=timezone.utc)


class Mono:
    """Controllable monotonic source for the demo clock."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# --- fake clock -------------------------------------------------------------

def test_fake_clock_returns_set_time():
    c = clk.FakeClock(T0)
    assert c.now() == T0
    c.set(T0 + timedelta(hours=1))
    assert c.now() == T0 + timedelta(hours=1)


def test_fake_clock_rejects_naive_datetimes():
    with pytest.raises(ValueError):
        clk.FakeClock(datetime(2024, 1, 1))


async def test_fake_sleep_wakes_only_when_advanced_far_enough():
    c = clk.FakeClock(T0)
    task = asyncio.create_task(c.sleep(60))
    await asyncio.sleep(0)
    await c.advance(59)
    assert not task.done()
    await c.advance(1)
    await asyncio.wait_for(task, 1)
    assert c.now() == T0 + timedelta(seconds=60)


async def test_fake_sleep_until_past_returns_at_once():
    c = clk.FakeClock(T0)
    await asyncio.wait_for(c.sleep_until(T0 - timedelta(seconds=5)), 1)


async def test_fake_advance_wakes_sleepers_in_deadline_order():
    c = clk.FakeClock(T0)
    woke = []

    async def sleeper(name, s):
        await c.sleep(s)
        woke.append((name, c.now()))

    tasks = [asyncio.create_task(sleeper("b", 20)), asyncio.create_task(sleeper("a", 10))]
    await asyncio.sleep(0)
    await c.advance(30)
    await asyncio.gather(*tasks)
    # each sleeper sees the time at its own deadline, not the end of the advance
    assert woke == [("a", T0 + timedelta(seconds=10)), ("b", T0 + timedelta(seconds=20))]


# --- demo clock -------------------------------------------------------------

def test_demo_clock_not_ready_before_first_tick():
    c = clk.DemoClock(monotonic=Mono())
    assert not c.ready
    with pytest.raises(clk.ClockNotReady):
        c.now()


def test_demo_clock_interpolates_between_ticks():
    """11.3: processes interpolate between the simulator's 1-second ticks."""
    mono = Mono()
    c = clk.DemoClock(monotonic=mono)
    c.tick(T0, speed=60)
    assert c.now() == T0
    mono.t += 0.5
    assert c.now() == T0 + timedelta(seconds=30)
    assert c.speed == 60


def test_demo_clock_follows_next_tick():
    mono = Mono()
    c = clk.DemoClock(monotonic=mono)
    c.tick(T0, speed=60)
    mono.t += 1
    c.tick(T0 + timedelta(seconds=60), speed=120)
    mono.t += 1
    assert c.now() == T0 + timedelta(seconds=180)


def test_demo_clock_accepts_tick_message():
    """sim/clock payload: {"sim_time": "...Z", "speed": 60}."""
    c = clk.DemoClock(monotonic=Mono())
    c.tick_message('{"sim_time": "2024-05-25T06:00:00Z", "speed": 60}')
    assert c.now() == T0 and c.speed == 60


@pytest.mark.parametrize("payload", ['{"speed": 60}', '{"sim_time": "x", "speed": 60}', "not json",
                                     '{"sim_time": "2024-05-25T06:00:00Z", "speed": -1}'])
def test_demo_clock_rejects_bad_tick(payload):
    c = clk.DemoClock(monotonic=Mono())
    with pytest.raises(ValueError):
        c.tick_message(payload)


def test_demo_clock_never_runs_backwards_on_a_slightly_late_tick():
    """A tick that lands a little behind the interpolated time must not move time back."""
    mono = Mono()
    c = clk.DemoClock(monotonic=mono)
    c.tick(T0, speed=60)
    mono.t += 1.2
    ahead = c.now()  # T0 + 72 s
    c.tick(T0 + timedelta(seconds=60), speed=60)  # simulator's next tick, sent at 1.0 s
    assert c.now() >= ahead


def test_demo_clock_large_backward_jump_is_a_reset():
    """A new replay (start.ps1 -Demo -Reset) moves the demo time back; follow it."""
    mono = Mono()
    c = clk.DemoClock(monotonic=mono)
    c.tick(T0, speed=60)
    c.tick(T0 - timedelta(days=2), speed=60)
    assert c.now() == T0 - timedelta(days=2)


def test_demo_clock_paused_at_speed_zero():
    mono = Mono()
    c = clk.DemoClock(monotonic=mono)
    c.tick(T0, speed=0)
    mono.t += 10
    assert c.now() == T0


async def test_demo_sleep_takes_weather_seconds_divided_by_speed():
    c = clk.DemoClock()
    c.tick(datetime.now(timezone.utc), speed=600)
    start = asyncio.get_running_loop().time()
    await c.sleep(60)  # 60 weather seconds at 600x = 0.1 real seconds
    assert 0.05 < asyncio.get_running_loop().time() - start < 0.6


async def test_demo_wait_ready():
    c = clk.DemoClock()

    async def later():
        await asyncio.sleep(0.05)
        c.tick(T0, speed=60)

    asyncio.create_task(later())
    await asyncio.wait_for(c.wait_ready(), 1)
    assert c.ready


# --- weather and machine clocks (DD117) -------------------------------------

def test_real_mode_both_clocks_are_real():
    clocks = clk.make_clocks("real")
    assert isinstance(clocks.weather, clk.RealClock) and isinstance(clocks.machine, clk.RealClock)
    assert abs((clocks.weather.now() - datetime.now(timezone.utc)).total_seconds()) < 1


def test_demo_mode_machine_time_stays_real():
    """DD117: timeouts, heartbeats, pings, sessions always use the real clock."""
    clocks = clk.make_clocks("demo")
    assert isinstance(clocks.weather, clk.DemoClock)
    assert isinstance(clocks.machine, clk.RealClock)


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        clk.make_clocks("fast")


def test_now_is_always_utc_aware():
    for c in (clk.RealClock(), clk.FakeClock(T0)):
        assert c.now().tzinfo is not None and c.now().utcoffset() == timedelta(0)


# --- the 15-minute loop on weather time -------------------------------------

def test_next_slot_aligns_to_the_interval():
    every = timedelta(minutes=15)
    assert clk.next_slot(datetime(2024, 5, 25, 6, 7, tzinfo=timezone.utc), every) == datetime(2024, 5, 25, 6, 15, tzinfo=timezone.utc)
    assert clk.next_slot(datetime(2024, 5, 25, 6, 15, tzinfo=timezone.utc), every) == datetime(2024, 5, 25, 6, 30, tzinfo=timezone.utc)


async def test_every_fires_on_aligned_weather_slots():
    """DD82: the forecast loop waits for weather-time issue times (:00, :15, :30, :45)."""
    c = clk.FakeClock(T0 + timedelta(minutes=7))
    fired = []

    async def job(slot):
        fired.append(slot)

    task = asyncio.create_task(clk.every(c, timedelta(minutes=15), job))
    await asyncio.sleep(0)
    for _ in range(6):
        await c.advance(10 * 60)
    task.cancel()
    assert fired == [T0 + timedelta(minutes=m) for m in (15, 30, 45, 60)]


async def test_every_skips_slots_it_cannot_keep_up_with():
    """DD58: a run that cannot keep up is skipped, not queued."""
    c = clk.FakeClock(T0)
    fired, skipped = [], []

    async def slow_job(slot):
        fired.append(slot)
        await c.advance(40 * 60)  # the job itself takes 40 minutes of weather time

    task = asyncio.create_task(clk.every(c, timedelta(minutes=15), slow_job, on_skip=skipped.append))
    await asyncio.sleep(0)
    await c.advance(15 * 60)  # 06:15 fires; the job runs until 06:55
    await c.advance(5 * 60)   # 07:00 fires (06:30 and 06:45 were missed)
    task.cancel()
    assert fired[:2] == [T0 + timedelta(minutes=15), T0 + timedelta(minutes=60)]
    assert skipped[:2] == [T0 + timedelta(minutes=30), T0 + timedelta(minutes=45)]


async def test_every_runs_latest_missed_slot_within_grace():
    """DD130: after a busy run, the latest missed slot still runs if it is at most `grace` late."""
    c = clk.FakeClock(T0)
    fired, skipped = [], []

    async def job(slot):
        fired.append((slot, c.now()))
        if len(fired) == 1:
            await c.advance(17 * 60)  # first run ends at 06:32: the 06:30 slot is 2 minutes late

    task = asyncio.create_task(clk.every(c, timedelta(minutes=15), job, on_skip=skipped.append, grace_s=300))
    await asyncio.sleep(0)
    await c.advance(15 * 60)
    task.cancel()
    assert fired[1] == (T0 + timedelta(minutes=30), T0 + timedelta(minutes=32))  # run late, labelled 06:30
    assert skipped == []


async def test_every_coalesces_to_the_latest_missed_slot():
    """DD130: of several missed slots only the latest may run; older ones are skipped."""
    c = clk.FakeClock(T0)
    fired, skipped = [], []

    async def job(slot):
        fired.append(slot)
        if len(fired) == 1:
            await c.advance(32 * 60)  # ends at 06:47: 06:30 and 06:45 missed, 06:45 only 2 min late

    task = asyncio.create_task(clk.every(c, timedelta(minutes=15), job, on_skip=skipped.append, grace_s=300))
    await asyncio.sleep(0)
    await c.advance(15 * 60)
    task.cancel()
    assert fired[:2] == [T0 + timedelta(minutes=15), T0 + timedelta(minutes=45)]
    assert skipped == [T0 + timedelta(minutes=30)]


def test_grace_is_machine_time_in_demo_mode():
    """DD117, DD130: 300 s of start grace are 300 real seconds, i.e. 5 weather hours at 60x."""
    mono = Mono()
    demo = clk.DemoClock(monotonic=mono)
    demo.tick(T0, speed=60)
    assert clk.machine_seconds(demo, timedelta(hours=5)) == pytest.approx(300)
    assert clk.machine_seconds(clk.FakeClock(T0), timedelta(minutes=5)) == pytest.approx(300)
