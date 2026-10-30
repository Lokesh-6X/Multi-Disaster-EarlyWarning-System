"""Kit simulator, one kit (design/11 §11.1–11.2, §11.4.0–11.4.1, §11.7, DD125, DD135; TST-01, HW-07, HW-12).
The simulator never imports ews (DD7); these tests only drive it from outside."""
import json
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from simulator import config as sim_config
from simulator import contract
from simulator.__main__ import main
from simulator.kit import SimKit, aligned
from simulator.weather import Truth
from simulator.weather.normal import NormalWeather
from simulator.weather.replay import Point, ReplayWeather, from_csv
from simulator.weather.sensor import SensorModel, station_pressure

T0 = datetime(2026, 10, 30, 9, 31, tzinfo=timezone.utc)
KIT = sim_config.KitConfig("KIT-01", 13.081, 80.271, 30.0)
VALID = {"kit_id": "KIT-01", "ts": "2026-11-02T09:31:00Z", "seq": 0, "fw": "1.0.0", "bme_temp_c": 31.2,
         "bme_rh_pct": 60.1, "bme_pressure_hpa": 1004.5, "wind_avg_kmh": 8.0, "wind_gust_kmh": 12.5, "rain_tips": 0}


def kit(source=None, cfg=KIT, seed=1) -> SimKit:
    rng = random.Random(seed)
    return SimKit(cfg, "abc", source or NormalWeather(rng), rng, boot=T0 - timedelta(hours=1))


# --- contract (05 §5.2.2) ----------------------------------------------------------------------

def test_contract_accepts_a_valid_message_with_optional_fields():
    assert contract.problems(VALID) == []
    assert contract.problems({**VALID, "dht_temp_c": None, "wind_dir_deg": 359.9, "rssi_dbm": -70,
                              "uptime_s": 5, "ts": "2026-11-02T09:31:00.250Z"}) == []


@pytest.mark.parametrize("change,expected", [
    ({"extra": 1}, "unknown field extra"),
    ({"seq": -1}, "seq: -1 is below 0"),
    ({"seq": 1.5}, "seq: expected integer"),
    ({"rain_tips": True}, "rain_tips: expected integer"),
    ({"bme_temp_c": float("nan")}, "bme_temp_c: expected number"),
    ({"bme_temp_c": "31"}, "bme_temp_c: expected number"),
    ({"wind_dir_deg": 360}, "wind_dir_deg: 360 must be below 360"),
    ({"rssi_dbm": -131}, "rssi_dbm: -131 is below -130"),
    ({"fw": ""}, "fw: shorter than 1"),
    ({"ts": "2026-11-02 09:31:00"}, "ts: '2026-11-02 09:31:00' does not match"),
    ({"ts": "2026-11-02T09:31:00+05:30"}, "does not match"),
    ({"wind_gust_kmh": None}, "wind_gust_kmh: expected number"),
])
def test_contract_problems(change, expected):
    found = contract.problems({**VALID, **change})
    assert any(expected in p for p in found), found


def test_contract_missing_field_and_size():
    assert contract.problems({k: v for k, v in VALID.items() if k != "seq"}) == ["missing field seq"]
    with pytest.raises(contract.ContractError, match="bytes"):
        contract.encode({**VALID, "ts": "2026-11-02T09:31:00." + "0" * 4100 + "Z"})


def test_schema_lists_exactly_the_contract_fields():
    """Same field set as design/05 §5.2.2; M1.8 compares it with the backend validator."""
    schema = json.loads(contract.SCHEMA_FILE.read_text(encoding="utf-8"))
    assert set(schema["properties"]) == {"kit_id", "ts", "seq", "fw", "bme_temp_c", "bme_rh_pct", "bme_pressure_hpa",
                                         "dht_temp_c", "dht_rh_pct", "wind_avg_kmh", "wind_gust_kmh", "wind_dir_deg",
                                         "rain_tips", "rssi_dbm", "uptime_s"}
    assert schema["additionalProperties"] is False


# --- sensor model and sources ------------------------------------------------------------------

@pytest.mark.parametrize("elevation", [0, 30, 900])
def test_station_pressure_inverts_the_server_reduction(elevation):
    """design/05 §5.3: p0 = p · (1 − 0.0065 h / (T + 0.0065 h + 273.15))^−5.257"""
    p = station_pressure(1008.0, elevation, 31.0)
    h = elevation
    assert p * (1 - 0.0065 * h / (31.0 + 0.0065 * h + 273.15)) ** -5.257 == pytest.approx(1008.0)


def test_sensor_resolution_and_rain_bucket():
    model = SensorModel(random.Random(0), elevation_m=30, rain_mm_per_tip=0.28, dht11=True, wind_vane=False)
    r = model.read(Truth(30.0, 60.0, 1008.0, 8.0, 12.0, rain_mm=0.5))
    assert r["rain_tips"] == 1 and r["dht_temp_c"] == round(r["dht_temp_c"]) and "wind_dir_deg" not in r
    assert model.read(Truth(30.0, 60.0, 1008.0, 8.0, 12.0, rain_mm=0.1))["rain_tips"] == 1   # 0.22 + 0.1 ≥ 0.28
    no_dht = SensorModel(random.Random(0), elevation_m=30, dht11=False).read(Truth(30, 60, 1008, 8, 12))
    assert "dht_temp_c" not in no_dht and no_dht["wind_gust_kmh"] >= no_dht["wind_avg_kmh"]


def test_dd135_normal_weather_is_dry_calm_and_diurnal():
    w = NormalWeather(random.Random(3))
    afternoon = w.truth(datetime(2026, 10, 30, 9, 30, tzinfo=timezone.utc), 60)   # 15:00 IST
    night = w.truth(datetime(2026, 10, 29, 21, 30, tzinfo=timezone.utc), 60)      # 03:00 IST
    assert afternoon.temp_c == pytest.approx(34) and night.temp_c == pytest.approx(26)
    assert afternoon.rh_pct == pytest.approx(50) and night.rh_pct == pytest.approx(80)
    gusts = [w.truth(T0 + timedelta(minutes=i), 60) for i in range(600)]
    assert all(t.rain_mm == 0 and t.wind_gust_kmh < 39 for t in gusts)   # never a yellow wind


def test_tst01_replay_interpolates_and_keeps_rain_totals():
    points = [Point(datetime(2024, 5, 25, h, tzinfo=timezone.utc),
                    {"temp_c": 30 + h, "rh_pct": 50, "pressure_msl_hpa": 1000, "wind_avg_kmh": 10,
                     "rain_mm": 5.6 if h == 2 else 0.0}) for h in range(4)]
    shift = T0.replace(minute=0) - points[0].ts
    w = ReplayWeather(points, random.Random(0), rain_mm_per_tip=0.28, shift=shift)
    assert w.start == T0.replace(minute=0) and w.end == w.start + timedelta(hours=3)
    at = [w.truth(w.start + timedelta(minutes=m), 60) for m in range(1, 181)]
    assert at[59].temp_c == pytest.approx(31) and 31 < at[89].temp_c < 32
    assert sum(t.rain_mm for t in at) == pytest.approx(5.6)
    assert sum(t.rain_mm for t in at[60:120]) == pytest.approx(5.6)   # all within the hour ending 02:00


def test_replay_from_csv(tmp_path: Path):
    f = tmp_path / "kit.csv"
    f.write_text("ts,temp_c,rh_pct,pressure_msl_hpa,wind_avg_kmh,rain_mm\n"
                 "2024-05-25T00:00:00Z,30,50,1005,10,0\n2024-05-25T01:00:00Z,31,48,1005.5,12,1.2\n", encoding="utf-8")
    points = from_csv(f)
    assert len(points) == 2 and points[1].values["rain_mm"] == 1.2 and points[0].ts.tzinfo is not None


# --- the kit ----------------------------------------------------------------------------------

def test_hw07_messages_are_valid_and_numbered():
    k = kit()
    messages = [k.message(T0 + timedelta(minutes=i)) for i in range(120)]
    assert all(contract.problems(m) == [] for m in messages)
    assert [m["seq"] for m in messages[:3]] == [0, 1, 2]
    assert messages[0]["ts"] == "2026-10-30T09:31:00Z" and messages[0]["uptime_s"] == 3600
    assert all(-80 <= m["rssi_dbm"] <= -55 for m in messages)


def test_seed_makes_runs_identical():
    assert kit(seed=7).message(T0) == kit(seed=7).message(T0)
    assert kit(seed=7).message(T0) != kit(seed=8).message(T0)


def test_dd135_timestamps_on_the_sampling_interval():
    assert aligned(datetime(2026, 10, 30, 9, 31, 0, tzinfo=timezone.utc), 60) == T0
    assert aligned(datetime(2026, 10, 30, 9, 30, 0, 1, tzinfo=timezone.utc), 60) == T0
    assert aligned(datetime(2026, 10, 30, 9, 31, 20, tzinfo=timezone.utc), 300).minute == 35


def test_kit_without_connection_does_not_buffer():
    """HW-09: while disconnected the reading is lost; seq still moves on."""
    k = kit()
    assert k.publish(T0) is None and k.seq == 1


def test_password_name_and_lookup(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("MQTT_PASSWORD_KIT_01=secret\n", encoding="utf-8")
    monkeypatch.delenv("MQTT_PASSWORD_KIT_01", raising=False)
    assert KIT.password_env == "MQTT_PASSWORD_KIT_01"
    assert sim_config.password(KIT, env) == "secret"
    with pytest.raises(sim_config.ConfigError):
        sim_config.password(sim_config.KitConfig("KIT-09", 0, 0, 0), env)


# --- command line and the D39 guard -------------------------------------------------------------

def write_config(tmp_path: Path, mode: str) -> Path:
    f = tmp_path / "config.yaml"
    f.write_text(f"site_id: abc\nclock: {{ mode: {mode} }}\nkits:\n"
                 "  - {kit_id: KIT-01, lat: 13.081, lon: 80.271, elevation_m: 30}\n", encoding="utf-8")
    return f


@pytest.mark.parametrize("extra", [["--scenario", "squall"], ["--fault", "KIT-01 disconnect 10m"]])
def test_dd125_scenarios_and_faults_refused_on_the_real_clock(tmp_path, capsys, extra):
    assert main(["--config", str(write_config(tmp_path, "real")), "run", *extra]) == 3
    assert "D39, DD125" in capsys.readouterr().err


def test_real_clock_runs_at_1x_only(tmp_path, capsys):
    assert main(["--config", str(write_config(tmp_path, "real")), "run", "--speed", "60"]) == 3


def test_demo_clock_not_yet_available(tmp_path, capsys):
    assert main(["--config", str(write_config(tmp_path, "demo")), "run"]) == 3
    assert "M2.8" in capsys.readouterr().err


def test_validate_shipped_config(capsys):
    assert main(["validate"]) == 0
    assert "KIT-01: message valid" in capsys.readouterr().out


def test_shipped_config_matches_the_example_site():
    """The stand-in kit must be a kit the server knows (config/example-site.yaml)."""
    import yaml
    site = yaml.safe_load((sim_config.SIM_DIR.parent / "config" / "example-site.yaml").read_text(encoding="utf-8"))
    cfg = sim_config.load()
    assert cfg.site_id == site["site"]["site_id"]
    by_id = {k["kit_id"]: k for k in site["kits"]}
    for k in cfg.kits:
        assert (k.lat, k.lon, k.elevation_m, k.sampling_interval_s) == (
            by_id[k.kit_id]["lat"], by_id[k.kit_id]["lon"], by_id[k.kit_id]["elevation_m"],
            by_id[k.kit_id].get("sampling_interval_s", 60))


def test_dd7_simulator_never_imports_ews():
    code = ("import sys, simulator.__main__, simulator.kit, simulator.weather.replay; "
            "bad = [m for m in sys.modules if m == 'ews' or m.startswith('ews.')]; print(bad); sys.exit(1 if bad else 0)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
