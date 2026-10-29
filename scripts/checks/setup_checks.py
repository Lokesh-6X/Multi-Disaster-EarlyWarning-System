"""Python part of check-setup.ps1 (design/14 §14.1.3): MQTT logins, Python packages, model registry.

Prints one line per check: OK|FAIL<TAB>check<TAB>detail. Exit code 1 if any check fails.
"""
import hashlib
import importlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
results = []


def check(name, ok, detail=""):
    results.append((ok, name, detail))


def env(path, key):
    p = REPO / path
    if not p.exists():
        return None
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


def mqtt_login(user, password, port):
    import paho.mqtt.client as mqtt

    reasons = []
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if user:
        c.username_pw_set(user, password)
    c.on_connect = lambda cl, u, f, reason, p: reasons.append(reason)
    try:
        c.connect("localhost", port, keepalive=10)
    except OSError as e:
        return None, str(e)
    c.loop_start()
    deadline = time.monotonic() + 5
    while not reasons and time.monotonic() < deadline:
        time.sleep(0.05)
    c.disconnect()
    c.loop_stop()
    if not reasons:
        return None, "no answer"
    return not reasons[0].is_failure, str(reasons[0])


def main():
    port = int(env(".env", "MQTT_PORT") or 1883)
    ok, detail = mqtt_login(env(".env", "MQTT_INGEST_USER") or "ingest", env(".env", "MQTT_INGEST_PASSWORD"), port)
    check("Mosquitto: ingest login", ok is True, detail)
    ok, detail = mqtt_login(None, None, port)
    check("Mosquitto: anonymous refused", ok is False, detail)

    missing = []
    for module in ("ews", "simulator", "torch", "darts", "lightgbm"):
        try:
            importlib.import_module(module)
        except Exception as e:  # noqa: BLE001 - any import failure is a failed check (e.g. Smart App Control)
            missing.append(f"{module}: {type(e).__name__}: {e}"[:160])
    check("Python packages (ews, simulator, torch, darts, lightgbm)", not missing, "; ".join(missing) or "import OK")

    registry_file = REPO / "models" / "registry.json"
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        problems = []
        versions = {m["version"]: m for m in registry.get("models", [])}
        active = set()
        for group in ("variables", "events"):
            for entry in registry.get("active", {}).get(group, {}).values():
                active.update(v for v in (entry.get("model"), entry.get("fallback")) if v)
        for version in sorted(active):
            meta = versions.get(version)
            folder = REPO / "models" / (meta or {}).get("path", version)
            if meta is None or not folder.is_dir():
                problems.append(f"{version}: folder missing")
                continue
            for file, digest in meta.get("sha256", {}).items():
                path = folder / file
                if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    problems.append(f"{version}/{file}: checksum")
        detail = "; ".join(problems) or f"{len(active)} active model(s)" + (" (none yet)" if not active else "")
        check("Models (registry.json)", not problems, detail)
    except (OSError, ValueError, KeyError) as e:
        check("Models (registry.json)", False, str(e))

    for ok, name, detail in results:
        print(f"{'OK' if ok else 'FAIL'}\t{name}\t{detail}")
    return 0 if all(ok for ok, _, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
