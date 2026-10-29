"""Week-1 check 5 (M0.9, DD82, DD117, analysis/05 §5.3): a 15-minute job follows the demo clock.

A stand-in simulator publishes {"sim_time", "speed"} retained on sim/clock every real second (user
`simulator`); a follower (user `ingest`, as ingest will relay it) feeds the ticks into DemoClock and
runs ews.common.clock.every() on 15-minute weather-time slots. At 60x the job must fire every 15 real s.

Usage: backend/.venv/Scripts/python.exe scripts/checks/demo_clock_check.py [--speed 60] [--fires 4]
"""
import argparse
import asyncio
import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

from ews.common.clock import DemoClock, every

REPO = Path(__file__).resolve().parents[2]
START = datetime(2024, 5, 25, 6, 7, 30, tzinfo=timezone.utc)  # 7.5 min before the 06:15 slot


def env(path, key):
    for line in (REPO / path).read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1]
    sys.exit(f"{key} missing in {path}")


def connect(user, password, port):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    c.username_pw_set(user, password)
    c.connect("localhost", port)
    c.loop_start()
    return c


def simulator(stop, speed, port):
    """Publishes the demo clock every real second, like the simulator in demo mode (11 §11.3)."""
    pub = connect("simulator", env("simulator/.env", "MQTT_SIMULATOR_PASSWORD"), port)
    t0 = time.monotonic()
    while not stop.is_set():
        sim_time = START + timedelta(seconds=(time.monotonic() - t0) * speed)
        payload = json.dumps({"sim_time": sim_time.isoformat().replace("+00:00", "Z"), "speed": speed})
        pub.publish("sim/clock", payload, qos=1, retain=True)
        stop.wait(1.0)
    pub.publish("sim/clock", b"", qos=1, retain=True).wait_for_publish(5)  # clear the retained tick
    pub.disconnect(); pub.loop_stop()


async def follower(speed, fires, port):
    loop = asyncio.get_running_loop()
    demo = DemoClock()
    ticks = [0]

    def on_message(client, userdata, msg):
        if msg.payload:
            ticks[0] += 1
            loop.call_soon_threadsafe(demo.tick_message, msg.payload)

    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    sub.username_pw_set("ingest", env(".env", "MQTT_INGEST_PASSWORD"))
    sub.on_message = on_message
    sub.on_connect = lambda c, u, f, rc, p: c.subscribe("sim/clock", qos=1)
    sub.connect("localhost", port)
    sub.loop_start()
    await asyncio.wait_for(demo.wait_ready(), 10)

    fired = []

    async def job(slot):
        fired.append((slot, time.monotonic()))
        print(f"  fired for slot {slot:%H:%M} (demo now {demo.now():%H:%M:%S}, real +{fired[-1][1] - fired[0][1]:.2f} s)",
              flush=True)

    task = asyncio.create_task(every(demo, timedelta(minutes=15), job))
    while len(fired) < fires:
        await asyncio.sleep(0.1)
    task.cancel()
    sub.disconnect(); sub.loop_stop()
    return fired, ticks[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=60)
    ap.add_argument("--fires", type=int, default=4)
    ap.add_argument("--port", type=int, default=1883)
    args = ap.parse_args()

    stop = threading.Event()
    sim = threading.Thread(target=simulator, args=(stop, args.speed, args.port), daemon=True)
    sim.start()
    try:
        fired, ticks = asyncio.run(follower(args.speed, args.fires, args.port))
    finally:
        stop.set(); sim.join(10)

    expected_s = 15 * 60 / args.speed
    slots = [s for s, _ in fired]
    gaps = [b - a for (_, a), (_, b) in zip(fired, fired[1:])]
    aligned = all(s.minute % 15 == 0 and s.second == 0 for s in slots)
    consecutive = all(b - a == timedelta(minutes=15) for a, b in zip(slots, slots[1:]))
    on_time = all(abs(g - expected_s) < 1.0 for g in gaps)
    print(f"ticks received: {ticks}; real seconds between fires: {', '.join(f'{g:.2f}' for g in gaps)} "
          f"(expected {expected_s:g})")
    print(f"{'OK  ' if aligned and consecutive else 'FAIL'} job fired on consecutive 15-minute weather slots")
    print(f"{'OK  ' if on_time else 'FAIL'} every {expected_s:g} real seconds at {args.speed:g}x (within 1 s)")
    ok = aligned and consecutive and on_time
    print("DEMO CLOCK CHECK OK" if ok else "DEMO CLOCK CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
