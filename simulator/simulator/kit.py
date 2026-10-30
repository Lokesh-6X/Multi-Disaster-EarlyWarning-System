"""One simulated kit (design/11 §11.7, HW-07, HW-09, HW-12): readings built from a weather source and the
sensor model, checked against the contract and published over MQTT like a real kit."""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from simulator import contract
from simulator.config import KitConfig
from simulator.weather import Source
from simulator.weather.sensor import SensorModel


def aligned(t: datetime, interval_s: int) -> datetime:
    """The first multiple of interval_s at or after t (DD135)."""
    epoch = t.timestamp()
    slot = -(-epoch // interval_s) * interval_s
    return datetime.fromtimestamp(slot, timezone.utc)


def iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SimKit:
    def __init__(self, cfg: KitConfig, site_id: str, source: Source, rng: random.Random, boot: datetime):
        self.cfg = cfg
        self.source = source
        self.rng = rng
        self.sensors = SensorModel(rng, elevation_m=cfg.elevation_m, rain_mm_per_tip=cfg.rain_mm_per_tip,
                                   dht11=cfg.dht11, wind_vane=cfg.wind_vane)
        self.readings_topic = f"sites/{site_id}/kits/{cfg.kit_id}/readings"
        self.status_topic = f"sites/{site_id}/kits/{cfg.kit_id}/status"
        self.boot = boot
        self.seq = 0
        self._rssi = rng.uniform(-75, -60)
        self.client: Any = None

    def message(self, ts: datetime) -> dict[str, Any]:
        """The reading for `ts`; seq increments per message."""
        reading = self.sensors.read(self.source.truth(ts, self.cfg.sampling_interval_s))
        self._rssi = min(-55.0, max(-80.0, self._rssi + self.rng.gauss(0, 0.5)))
        message = {"kit_id": self.cfg.kit_id, "ts": iso(ts), "seq": self.seq, "fw": self.cfg.fw, **reading,
                   "rssi_dbm": round(self._rssi), "uptime_s": max(0, int((ts - self.boot).total_seconds()))}
        self.seq += 1
        return message

    def payload(self, ts: datetime) -> bytes:
        return contract.encode(self.message(ts))

    # --- MQTT -------------------------------------------------------------------------------------

    def connect(self, host: str, port: int, password: str) -> None:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{self.cfg.kit_id}")
        client.username_pw_set(self.cfg.kit_id, password)
        client.will_set(self.status_topic, "offline", qos=1, retain=True)   # HW-12

        def on_connect(c, userdata, flags, reason_code, properties):
            if reason_code.is_failure:
                print(f"{self.cfg.kit_id}: connection refused ({reason_code})", flush=True)
                return
            c.publish(self.status_topic, "online", qos=1, retain=True)
            print(f"{self.cfg.kit_id}: connected, online", flush=True)

        client.on_connect = on_connect
        client.connect(host, port, keepalive=30)
        client.loop_start()
        self.client = client

    def publish(self, ts: datetime) -> dict[str, Any] | None:
        """Publish the reading for ts; while disconnected the reading is lost, never buffered (HW-09)."""
        payload = self.payload(ts)
        if self.client is None or not self.client.is_connected():
            return None
        self.client.publish(self.readings_topic, payload, qos=1)
        return {"topic": self.readings_topic, "payload": payload}

    def close(self) -> None:
        """Clean stop: `offline` sent by the kit itself, not the last will (11 §11.8 `quit`)."""
        if self.client is None:
            return
        self.client.publish(self.status_topic, "offline", qos=1, retain=True).wait_for_publish(5)
        self.client.disconnect()
        self.client.loop_stop()
        self.client = None

