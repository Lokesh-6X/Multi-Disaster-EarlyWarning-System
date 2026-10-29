"""Week-1 check 4 (M0.4, DD11, DD109, analysis/05 §5.3): Mosquitto last will, persistent session, ACL.

Usage: python scripts/checks/mqtt_check.py [--port 1883]
Reads passwords from .env (ingest) and simulator/.env (KIT-01). Needs paho-mqtt 2.x.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

REPO = Path(__file__).resolve().parents[2]
SITE = "check"
KIT = "KIT-01"
N = 2000
READINGS = f"sites/{SITE}/kits/{KIT}/readings"
STATUS = f"sites/{SITE}/kits/{KIT}/status"


def env(path, key):
    for line in (REPO / path).read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1]
    sys.exit(f"{key} missing in {path}")


def client(user, password, client_id="", clean=True):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=clean)
    if user:
        c.username_pw_set(user, password)
    return c


def run_kit(port):
    """Child process: a kit with a last will that publishes N readings, then waits to be killed."""
    kit = client(KIT, env("simulator/.env", "MQTT_PASSWORD_KIT_01"), client_id="check-kit")
    kit.will_set(STATUS, "offline", qos=1, retain=True)
    kit.connect("localhost", port)
    kit.loop_start()
    kit.publish(STATUS, "online", qos=1, retain=True).wait_for_publish(10)
    kit.publish(f"sites/{SITE}/kits/KIT-02/readings", "not mine", qos=1).wait_for_publish(10)  # ACL: dropped
    for i in range(N):
        info = kit.publish(READINGS, str(i), qos=1)
    info.wait_for_publish(60)
    print("published", flush=True)
    time.sleep(600)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--kit", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.kit:
        return run_kit(args.port)

    results = {}

    # 1 anonymous login refused
    anon = client(None, None)
    anon_reason = []
    anon.on_connect = lambda c, u, f, reason, p: anon_reason.append(reason)
    try:
        anon.connect("localhost", args.port)
    except OSError as e:
        sys.exit(f"broker not reachable on port {args.port}: {e}")
    anon.loop_start(); time.sleep(1.5); anon.loop_stop()
    # the broker must answer and refuse, not just be unreachable
    results["anonymous refused"] = bool(anon_reason) and anon_reason[0].is_failure

    # 2 ingest: persistent session, subscribe, go away
    ingest_pw = env(".env", "MQTT_INGEST_PASSWORD")
    received = {"readings": 0, "foreign": 0, "status": []}

    def on_message(c, u, msg):
        if msg.topic == READINGS:
            received["readings"] += 1
        elif msg.topic == STATUS:
            received["status"].append((time.monotonic(), msg.payload.decode()))
        else:
            received["foreign"] += 1

    ingest = client("ingest", ingest_pw, client_id="check-ingest", clean=False)
    ingest.on_message = on_message
    ingest.connect("localhost", args.port); ingest.loop_start()
    ingest.subscribe([(f"sites/{SITE}/kits/+/readings", 1), (f"sites/{SITE}/kits/+/status", 1)])
    time.sleep(1)
    ingest.publish(f"sites/{SITE}/kits/{KIT}/readings", "from ingest", qos=1)  # ACL: dropped
    time.sleep(0.5)
    ingest.disconnect(); ingest.loop_stop()
    results["ingest cannot publish"] = received["readings"] == 0
    received.update(readings=0, foreign=0, status=[])

    # 3 kit publishes N readings while ingest is away
    kit = subprocess.Popen([sys.executable, __file__, "--kit", "--port", str(args.port)], stdout=subprocess.PIPE, text=True)
    if kit.stdout.readline().strip() != "published":
        sys.exit("kit process failed")

    # 4 ingest comes back with the same client id: the queued readings arrive
    ingest = client("ingest", ingest_pw, client_id="check-ingest", clean=False)
    ingest.on_message = on_message
    ingest.connect("localhost", args.port); ingest.loop_start()
    deadline = time.monotonic() + 30
    while received["readings"] < N and time.monotonic() < deadline:
        time.sleep(0.2)
    results[f"all {N} queued readings delivered ({received['readings']})"] = received["readings"] == N
    results["kit cannot publish to another kit's topic"] = received["foreign"] == 0

    # 5 kill the kit hard: the broker publishes its last will
    killed = time.monotonic()
    kit.kill(); kit.wait()
    while not any(p == "offline" for _, p in received["status"]) and time.monotonic() < killed + 10:
        time.sleep(0.05)
    offline = [t for t, p in received["status"] if p == "offline"]
    delay = offline[0] - killed if offline else None
    results[f"last will 'offline' after kill ({delay:.2f} s)" if delay is not None else "last will 'offline' after kill"] = delay is not None and delay < 2

    ingest.disconnect(); ingest.loop_stop()
    # remove the persistent session and the retained status
    cleanup = client("ingest", ingest_pw, client_id="check-ingest", clean=True)
    cleanup.connect("localhost", args.port); cleanup.disconnect()
    kit_clean = client(KIT, env("simulator/.env", "MQTT_PASSWORD_KIT_01"))
    kit_clean.connect("localhost", args.port); kit_clean.loop_start()
    kit_clean.publish(STATUS, b"", qos=1, retain=True).wait_for_publish(5)
    kit_clean.disconnect(); kit_clean.loop_stop()

    for name, ok in results.items():
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
    print("MQTT CHECK OK" if all(results.values()) else "MQTT CHECK FAILED")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
