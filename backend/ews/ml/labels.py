"""Hazard event labels from hourly history (design/06 §6.6, requirements 06 §6.1, DD104, DD133).

Used for training labels and for the back-test events of site onboarding. Pure numpy/pandas; thresholds
are arguments whose defaults are those of `config/defaults.yaml` (a test keeps them equal).

Label values: 1.0 event, 0.0 no event, NaN unknown (fewer than 80 % of the window's hours present and no
exceedance among those present).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from ews.ml.features import COVERAGE_MIN_PCT, HOUR, regular
from ews.ml.normals import normal_for

GUST_LEVELS_KMH = {"yellow": 39.0, "orange": 50.0, "red": 62.0}                  # wind_*_kmh
RAIN_24H_LEVELS_MM = {"yellow": 64.5, "orange": 115.6, "red": 204.5}             # rain_*_24h_mm
RAIN_INTENSITY_PERCENTILE = 99.0                                                 # rain_intensity_percentile
RAIN_WET_HOUR_MIN_MM = 0.1                                                       # rain_wet_hour_min_mm
RAIN_INTENSITY_FLOOR_MM = 20.0                                                   # rain_intensity_floor_mm
RAIN_DAY_END_UTC = 3   # IMD rain day ends 08:30 IST; whole hours → 03:00 UTC

# Windows (start h, end h] from the issue time (06 §6.6)
GUST_WINDOWS = tuple((a, a + 3) for a in range(0, 24, 3)) + tuple((a, a + 6) for a in range(24, 72, 6))
RAIN_INTENSITY_WINDOWS = ((0, 3), (3, 6))
RAIN_24H_DAYS = (0, 1, 2)
HEATWAVE_DAYS = (1, 2, 3)


@dataclass(frozen=True)
class HeatRules:
    """IMD heatwave rule for one region type (heat_* keys of 04 §4.3.6)."""
    min_tmax_c: float
    departure_c: float = 4.5
    severe_departure_c: float = 6.4
    absolute_c: float = 45.0
    severe_absolute_c: float = 47.0

    @classmethod
    def for_region(cls, region_type: str) -> HeatRules:
        return cls(min_tmax_c=HEAT_MIN_TMAX_C[region_type])


HEAT_MIN_TMAX_C = {"plains": 40.0, "coastal": 37.0, "hilly": 30.0}               # heat_min_tmax_c


# --- thresholds from history -------------------------------------------------------------------

def wet_hour_percentile(rain_mm: pd.Series, percentile: float = RAIN_INTENSITY_PERCENTILE,
                        wet_min_mm: float = RAIN_WET_HOUR_MIN_MM) -> float:
    wet = rain_mm[rain_mm >= wet_min_mm].to_numpy(dtype=float)
    return float(np.percentile(wet, percentile)) if len(wet) else float("nan")


def rain_burst_threshold(rain_mm: pd.Series, percentile: float = RAIN_INTENSITY_PERCENTILE,
                         wet_min_mm: float = RAIN_WET_HOUR_MIN_MM,
                         floor_mm: float = RAIN_INTENSITY_FLOOR_MM) -> float:
    """max(floor, wet-hour percentile) mm/h (D32, DD104)."""
    p = wet_hour_percentile(rain_mm, percentile, wet_min_mm)
    return floor_mm if np.isnan(p) else max(floor_mm, p)


# --- the label rule ----------------------------------------------------------------------------

def _label(value: pd.Series, count: pd.Series, hours: int | pd.Series, threshold: float,
           coverage_min_pct: float) -> pd.Series:
    """1 on an exceedance among present hours, 0 with enough coverage, else NaN (DD133)."""
    enough = count >= np.asarray(hours) * coverage_min_pct / 100
    return pd.Series(np.where(value >= threshold, 1.0, np.where(enough, 0.0, np.nan)), index=value.index)


def window_labels(series: pd.Series, issue_times: pd.DatetimeIndex, windows: Sequence[tuple[int, int]],
                  threshold: float, how: str = "max", name: str = "event",
                  coverage_min_pct: float = COVERAGE_MIN_PCT) -> pd.DataFrame:
    """Per issue time t₀ and window (a, b]: the hours ending in (t₀ + a h, t₀ + b h] (DD133).
    Columns `{name}_{a}_{b}h`."""
    s = regular(series)
    out = pd.DataFrame(index=issue_times)
    for a, b in windows:
        n = b - a
        roll = s.rolling(n, min_periods=1)
        value = (roll.max() if how == "max" else roll.sum()).reindex(issue_times + b * HOUR)
        count = roll.count().reindex(issue_times + b * HOUR).fillna(0)
        out[f"{name}_{a}_{b}h"] = _label(value, count, n, threshold, coverage_min_pct).to_numpy()
    return out


def gust_labels(gust_kmh: pd.Series, issue_times: pd.DatetimeIndex,
                levels: Mapping[str, float] = GUST_LEVELS_KMH, windows=GUST_WINDOWS,
                coverage_min_pct: float = COVERAGE_MIN_PCT) -> pd.DataFrame:
    """`gust` yellow / orange / red: max gust in the window ≥ the level."""
    return pd.concat([window_labels(gust_kmh, issue_times, windows, threshold, "max", f"gust_{level}",
                                    coverage_min_pct) for level, threshold in levels.items()], axis=1)


def rain_intensity_labels(rain_mm: pd.Series, issue_times: pd.DatetimeIndex, threshold_mm: float,
                          windows=RAIN_INTENSITY_WINDOWS,
                          coverage_min_pct: float = COVERAGE_MIN_PCT) -> pd.DataFrame:
    """`rain_intensity`: max hourly rain ≥ the location's rain-burst threshold (rain_burst_threshold)."""
    return window_labels(rain_mm, issue_times, windows, threshold_mm, "max", "rain_intensity", coverage_min_pct)


def rain_day_end(times: pd.DatetimeIndex, day: int = 0) -> pd.DatetimeIndex:
    """End of rain day D`day` for each time: D0 ends at the first 03:00 UTC strictly after it."""
    t = pd.DatetimeIndex(times).tz_convert("UTC")
    end = (t - pd.Timedelta(hours=RAIN_DAY_END_UTC)).floor("D") + pd.Timedelta(hours=RAIN_DAY_END_UTC, days=1)
    return end + pd.Timedelta(days=day)


def rain_24h_labels(rain_mm: pd.Series, issue_times: pd.DatetimeIndex,
                    levels: Mapping[str, float] = RAIN_24H_LEVELS_MM, days: Sequence[int] = RAIN_24H_DAYS,
                    coverage_min_pct: float = COVERAGE_MIN_PCT) -> pd.DataFrame:
    """`rain_24h` per IMD rain day (24 h ending 03:00 UTC), days D0–D2 from t₀. A partial sum that already
    meets the level is an event."""
    s = regular(rain_mm)
    roll = s.rolling(24, min_periods=1)
    total, count = roll.sum(), roll.count()
    out = pd.DataFrame(index=issue_times)
    for day in days:
        ends = rain_day_end(issue_times, day)
        value, n = total.reindex(ends), count.reindex(ends).fillna(0)
        for level, threshold in levels.items():
            out[f"rain_24h_{level}_D{day}"] = _label(value, n, 24, threshold, coverage_min_pct).to_numpy()
    return out


def heatwave_level(tmax_c, normal_c, rules: HeatRules) -> np.ndarray:
    """0 none, 1 heatwave (orange), 2 severe (red), NaN unknown (requirements 06 §6.1, 08 §8.6)."""
    tmax = np.asarray(tmax_c, dtype=float)
    departure = tmax - np.asarray(normal_c, dtype=float)
    with np.errstate(invalid="ignore"):
        hot = tmax >= rules.min_tmax_c
        red = (hot & (departure > rules.severe_departure_c)) | (tmax >= rules.severe_absolute_c)
        orange = (hot & (departure >= rules.departure_c)) | (tmax >= rules.absolute_c)
    level = np.where(red, 2.0, np.where(orange, 1.0, 0.0))
    unknown = np.isnan(tmax) | (np.isnan(departure) & ~(tmax >= rules.absolute_c))
    return np.where(unknown, np.nan, level)


def heatwave_labels(tmax_c: pd.Series, normals: pd.Series, issue_times: pd.DatetimeIndex, tz: str,
                    rules: HeatRules, days: Sequence[int] = HEATWAVE_DAYS) -> pd.DataFrame:
    """`heatwave` orange (level ≥ 1) and red (level 2) for local days D1–D3 after t₀'s local day.

    `tmax_c` = daily maximum per local date (normals.daily_max); `normals` = climate_normals (+ a kit's
    normal offset at run time, D33)."""
    today = pd.DatetimeIndex(issue_times).tz_convert(tz).normalize().tz_localize(None)
    out = pd.DataFrame(index=issue_times)
    for day in days:
        dates = today + pd.Timedelta(days=day)
        level = heatwave_level(tmax_c.reindex(dates).to_numpy(), normal_for(dates, normals), rules)
        out[f"heatwave_orange_D{day}"] = np.where(np.isnan(level), np.nan, (level >= 1).astype(float))
        out[f"heatwave_red_D{day}"] = np.where(np.isnan(level), np.nan, (level >= 2).astype(float))
    return out
