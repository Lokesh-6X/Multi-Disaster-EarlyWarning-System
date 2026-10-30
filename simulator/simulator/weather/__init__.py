"""Weather sources (design/11 §11.4) and the sensor model that turns true weather into kit readings."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Truth:
    """The true weather at the kit at one time (sea-level pressure, like ERA5)."""
    temp_c: float
    rh_pct: float
    pressure_msl_hpa: float
    wind_avg_kmh: float
    wind_gust_kmh: float
    rain_mm: float = 0.0          # rain since the previous reading
    wind_dir_deg: float | None = None


class Source(Protocol):
    def truth(self, ts: datetime, interval_s: int) -> Truth:
        """Weather at `ts` (UTC); rain = the amount in (ts − interval_s, ts]. Called with increasing ts."""

    @property
    def end(self) -> datetime | None:
        """Last time with data (None = endless)."""
