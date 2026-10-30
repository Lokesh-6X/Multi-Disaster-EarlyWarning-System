"""Sensor model (design/11 §11.4.1): true weather → BME280, DHT11, anemometer and rain-gauge values."""
from __future__ import annotations

import random

from simulator.weather import Truth


def station_pressure(pressure_msl_hpa: float, elevation_m: float, temp_c: float) -> float:
    """Inverse of the server's reduction to sea level (design/05 §5.3), so ingest gets the true value back."""
    h = elevation_m
    return pressure_msl_hpa * (1 - 0.0065 * h / (temp_c + 0.0065 * h + 273.15)) ** 5.257


class SensorModel:
    def __init__(self, rng: random.Random, *, elevation_m: float, rain_mm_per_tip: float = 0.28,
                 dht11: bool = True, wind_vane: bool = False):
        self.rng = rng
        self.elevation_m = elevation_m
        self.rain_mm_per_tip = rain_mm_per_tip
        self.dht11 = dht11
        self.wind_vane = wind_vane
        self._rain_left = 0.0      # rain below one tip waits in the bucket

    def read(self, truth: Truth) -> dict[str, float | int]:
        g = self.rng.gauss
        out: dict[str, float | int] = {
            "bme_temp_c": round(truth.temp_c + g(0, 0.05), 2),
            "bme_rh_pct": round(min(100.0, max(0.0, truth.rh_pct + g(0, 0.3))), 2),
            "bme_pressure_hpa": round(station_pressure(truth.pressure_msl_hpa, self.elevation_m, truth.temp_c)
                                      + g(0, 0.05), 2),
        }
        if self.dht11:
            out["dht_temp_c"] = float(round(truth.temp_c + g(0, 0.5)))
            out["dht_rh_pct"] = float(round(min(100.0, max(0.0, truth.rh_pct + g(0, 1.5)))))
        avg = max(0.0, truth.wind_avg_kmh)
        out["wind_avg_kmh"] = round(avg, 1)
        out["wind_gust_kmh"] = round(max(avg, truth.wind_gust_kmh), 1)
        if self.wind_vane:
            out["wind_dir_deg"] = round((truth.wind_dir_deg or 0.0) % 360, 1) % 360
        self._rain_left += max(0.0, truth.rain_mm)
        tips = int(self._rain_left / self.rain_mm_per_tip + 1e-9)
        self._rain_left -= tips * self.rain_mm_per_tip
        out["rain_tips"] = tips
        return out
