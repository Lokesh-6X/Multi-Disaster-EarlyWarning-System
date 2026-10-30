"""`normal` source (design/11 §11.4.0, DD135): dry, calm diurnal weather for a stand-in kit."""
from __future__ import annotations

import math
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from simulator.weather import Truth


class NormalWeather:
    end = None

    def __init__(self, rng: random.Random, timezone: str = "Asia/Kolkata"):
        self.rng = rng
        self.tz = ZoneInfo(timezone)
        self._turbulence = 0.0
        self._gust_factor = 1.5

    def truth(self, ts: datetime, interval_s: int) -> Truth:
        local = ts.astimezone(self.tz)
        hour = local.hour + local.minute / 60 + local.second / 3600
        day = math.cos(2 * math.pi * (hour - 15) / 24)
        self._turbulence = 0.9 * self._turbulence + self.rng.gauss(0, 1.5 * math.sqrt(1 - 0.81))
        self._gust_factor = min(1.7, max(1.3, self._gust_factor + self.rng.gauss(0, 0.02)))
        wind = max(0.0, 8 + self._turbulence)
        return Truth(temp_c=30 + 4 * day,
                     rh_pct=65 - 15 * day,
                     pressure_msl_hpa=1008 + 1.0 * math.cos(4 * math.pi * (hour - 10) / 24),
                     wind_avg_kmh=wind,
                     wind_gust_kmh=wind * self._gust_factor,
                     rain_mm=0.0,
                     wind_dir_deg=(200 + 30 * self._turbulence) % 360)
