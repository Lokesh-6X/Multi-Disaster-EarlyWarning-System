"""Replay source (design/11 §11.4.1, TST-01, DD84): Open-Meteo Archive (ERA5) or a CSV, turned into readings.

Instantaneous values (temperature, humidity, pressure, wind) are interpolated with a cubic Hermite curve
between the points; the wind gets AR(1) turbulence and a gust factor (random walk 1.3–1.7, rare bursts).
Each point's rain (the amount since the previous point, end-labelled like ERA5) falls as tip-sized drops at
random times inside its interval, so tips arrive like a Poisson process.
"""
from __future__ import annotations

import bisect
import csv
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from simulator.weather import Truth

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES = ("temp_c", "rh_pct", "pressure_msl_hpa", "wind_avg_kmh")
OPEN_METEO = {"temperature_2m": "temp_c", "relative_humidity_2m": "rh_pct", "pressure_msl": "pressure_msl_hpa",
              "wind_speed_10m": "wind_avg_kmh", "precipitation": "rain_mm"}


@dataclass(frozen=True)
class Point:
    ts: datetime                      # UTC, end of the interval for rain
    values: dict[str, float]          # VARIABLES + rain_mm


def from_open_meteo(lat: float, lon: float, start: date, end: date) -> list[Point]:
    """Hourly ERA5 from the Open-Meteo Archive (same request as onboarding, design/05 §5.8.2)."""
    import httpx

    params = {"latitude": lat, "longitude": lon, "start_date": start.isoformat(), "end_date": end.isoformat(),
              "hourly": ",".join(OPEN_METEO), "wind_speed_unit": "kmh", "timezone": "GMT", "models": "era5"}
    response = httpx.get(ARCHIVE_URL, params=params, timeout=60)
    response.raise_for_status()
    hourly = response.json()["hourly"]
    points = []
    for i, text in enumerate(hourly["time"]):
        values = {name: hourly[api][i] for api, name in OPEN_METEO.items()}
        if any(v is None for v in values.values()):
            continue
        points.append(Point(datetime.fromisoformat(text).replace(tzinfo=timezone.utc), values))
    return points


def from_csv(path: Path) -> list[Point]:
    """Columns ts (ISO 8601, UTC), temp_c, rh_pct, pressure_msl_hpa, wind_avg_kmh, rain_mm (since the previous row)."""
    points = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            points.append(Point(ts.astimezone(timezone.utc),
                                {name: float(row[name]) for name in (*VARIABLES, "rain_mm")}))
    return points


class ReplayWeather:
    def __init__(self, points: list[Point], rng: random.Random, *, rain_mm_per_tip: float = 0.28,
                 shift: timedelta = timedelta(0)):
        if len(points) < 2:
            raise ValueError("a replay needs at least two points")
        self.points = sorted(points, key=lambda p: p.ts)
        self.times = [p.ts.timestamp() for p in self.points]
        self.rng = rng
        self.shift = shift            # real clock: sim time = replay time + shift (11 §11.4.1)
        self.drop_mm = rain_mm_per_tip
        self._drops: list[tuple[float, float]] = []   # (time, mm), built point by point
        self._drops_until = 0                          # points whose rain is already in _drops
        self._turbulence = 0.0
        self._gust_factor = 1.5

    @property
    def start(self) -> datetime:
        return self.points[0].ts + self.shift

    @property
    def end(self) -> datetime:
        return self.points[-1].ts + self.shift

    def truth(self, ts: datetime, interval_s: int) -> Truth:
        t = (ts - self.shift).timestamp()
        values = {name: self._interpolate(name, t) for name in VARIABLES}
        self._turbulence = 0.9 * self._turbulence + self.rng.gauss(0, 0.15 * max(values["wind_avg_kmh"], 2.0) *
                                                                 math.sqrt(1 - 0.81))
        self._gust_factor = min(1.7, max(1.3, self._gust_factor + self.rng.gauss(0, 0.02)))
        wind = max(0.0, values["wind_avg_kmh"] + self._turbulence)
        burst = 1.3 if self.rng.random() < 0.002 else 1.0
        return Truth(temp_c=values["temp_c"], rh_pct=values["rh_pct"],
                     pressure_msl_hpa=values["pressure_msl_hpa"], wind_avg_kmh=wind,
                     wind_gust_kmh=wind * self._gust_factor * burst, rain_mm=self._rain(t - interval_s, t))

    def _interpolate(self, name: str, t: float) -> float:
        """Cubic Hermite with centred slopes (non-uniform spacing allowed); held flat outside the data."""
        i = bisect.bisect_right(self.times, t) - 1
        if i < 0:
            return self.points[0].values[name]
        if i >= len(self.points) - 1:
            return self.points[-1].values[name]
        t0, t1 = self.times[i], self.times[i + 1]
        y0, y1 = self.points[i].values[name], self.points[i + 1].values[name]

        def slope(k: int) -> float:
            lo, hi = max(k - 1, 0), min(k + 1, len(self.points) - 1)
            return (self.points[hi].values[name] - self.points[lo].values[name]) / (self.times[hi] - self.times[lo])

        h = t1 - t0
        s = (t - t0) / h
        h00, h10, h01, h11 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s, -2 * s**3 + 3 * s**2, s**3 - s**2
        return h00 * y0 + h10 * h * slope(i) + h01 * y1 + h11 * h * slope(i + 1)

    def _rain(self, after: float, until: float) -> float:
        """Rain in (after, until]: drops of each point's interval placed at random times."""
        while self._drops_until < len(self.points) and self.times[self._drops_until] <= until + 3600 * 24:
            k = self._drops_until
            if k > 0:
                lo, hi = self.times[k - 1], self.times[k]
                amount = max(0.0, self.points[k].values["rain_mm"])
                while amount > 1e-9:
                    drop = min(self.drop_mm, amount)
                    self._drops.append((self.rng.uniform(lo, hi), drop))
                    amount -= drop
            self._drops_until += 1
        self._drops.sort()
        mm = sum(d for at, d in self._drops if after < at <= until)
        self._drops = [(at, d) for at, d in self._drops if at > until]
        return mm
