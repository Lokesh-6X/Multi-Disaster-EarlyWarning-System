"""simulator/config.yaml and the kit passwords in simulator/.env (design/11 §11.2, DD135)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SIM_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILE = SIM_DIR / "config.yaml"
ENV_FILE = SIM_DIR / ".env"
INTERVALS = (30, 60, 120, 300)    # sampling_interval_s (design/04 §4.3.2)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class KitConfig:
    kit_id: str
    lat: float
    lon: float
    elevation_m: float
    sampling_interval_s: int = 60
    rain_mm_per_tip: float = 0.28
    fw: str = "1.0.0-sim"
    dht11: bool = True
    wind_vane: bool = False

    @property
    def password_env(self) -> str:
        return "MQTT_PASSWORD_" + re.sub(r"[^A-Z0-9]", "_", self.kit_id.upper())


@dataclass(frozen=True)
class SimConfig:
    site_id: str
    kits: tuple[KitConfig, ...]
    host: str = "localhost"
    port: int = 1883
    clock_mode: str = "real"
    speed: float = 1.0
    seed: int = 42
    timezone: str = "Asia/Kolkata"
    clock: dict[str, Any] = field(default_factory=dict)


def load(path: Path = CONFIG_FILE) -> SimConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    try:
        clock = data.get("clock") or {}
        kits = tuple(_kit(k) for k in data["kits"])
        cfg = SimConfig(site_id=str(data["site_id"]), kits=kits,
                        host=data.get("broker", {}).get("host", "localhost"),
                        port=int(data.get("broker", {}).get("port", 1883)),
                        clock_mode=clock.get("mode", "real"), speed=float(clock.get("speed", 1)),
                        seed=int(data.get("seed", 42)), timezone=data.get("timezone", "Asia/Kolkata"), clock=clock)
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError(f"{path}: {type(e).__name__}: {e}") from None
    if cfg.clock_mode not in ("real", "demo"):
        raise ConfigError(f"{path}: clock.mode must be real or demo")
    if not kits:
        raise ConfigError(f"{path}: no kits")
    if len({k.kit_id for k in kits}) != len(kits):
        raise ConfigError(f"{path}: a kit_id is listed twice")
    return cfg


def _kit(data: dict[str, Any]) -> KitConfig:
    sensors = data.get("sensors") or {}
    kit = KitConfig(kit_id=str(data["kit_id"]), lat=float(data["lat"]), lon=float(data["lon"]),
                    elevation_m=float(data["elevation_m"]),
                    sampling_interval_s=int(data.get("sampling_interval_s", 60)),
                    rain_mm_per_tip=float(data.get("rain_mm_per_tip", 0.28)), fw=str(data.get("fw", "1.0.0-sim")),
                    dht11=bool(sensors.get("dht11", True)), wind_vane=bool(sensors.get("wind_vane", False)))
    if kit.sampling_interval_s not in INTERVALS:
        raise ValueError(f"{kit.kit_id}: sampling_interval_s must be one of {INTERVALS}")
    return kit


def password(kit: KitConfig, env_file: Path = ENV_FILE) -> str:
    """The kit's MQTT password: environment first, then simulator/.env."""
    if kit.password_env in os.environ:
        return os.environ[kit.password_env]
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(kit.password_env + "="):
                return line.split("=", 1)[1].strip()
    raise ConfigError(f"{kit.password_env} is not set in {env_file} (scripts/setup-mosquitto.ps1 writes it)")
