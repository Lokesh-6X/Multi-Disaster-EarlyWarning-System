"""Daily maximum and climate normals (design/06 §6.6, 03 §3.8 `climate_normal`, DD133).

Pure numpy/pandas. Normals live on a leap-year calendar: day 1–366, 29 February = day 60.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ews.ml.features import COVERAGE_MIN_PCT

NORMALS_START_YEAR = 1991     # normals_start_year
NORMALS_END_YEAR = 2020       # normals_end_year
SMOOTHING_DAYS = 15           # normals_smoothing_days
_LEAP_YEAR = 2000


def leap_day_of_year(dates) -> np.ndarray:
    """Day number of each date's month and day in a leap year (1 March = 61 in every year)."""
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    same_day = pd.to_datetime({"year": _LEAP_YEAR, "month": idx.month, "day": idx.day})
    return same_day.dt.dayofyear.to_numpy()


def local_day(index: pd.DatetimeIndex, tz: str) -> pd.DatetimeIndex:
    """The local day each end-labelled hour belongs to: windows are (start, end], so the hour ending at
    00:00 local is the last hour of the day before (DD133)."""
    return (index - pd.Timedelta(microseconds=1)).tz_convert(tz).normalize().tz_localize(None)


def daily_max(temp_c: pd.Series, tz: str, coverage_min_pct: float = COVERAGE_MIN_PCT,
              column_max: pd.Series | None = None) -> pd.Series:
    """Daily maximum per local day (index = local date). `column_max` (e.g. `temp_max_c` of `series_1h`)
    is used for the maximum when given; coverage is counted on `temp_c`. NaN below coverage."""
    days = local_day(temp_c.index, tz)
    values = column_max if column_max is not None else temp_c
    grouped = values.groupby(days)
    count = temp_c.groupby(days).count()
    expected = pd.Series([_hours_in_day(d, tz) for d in count.index], index=count.index)
    out = grouped.max().where(count >= expected * coverage_min_pct / 100)
    out.index.name = "date"
    return out.rename("tmax_c")


def _hours_in_day(day: pd.Timestamp, tz: str) -> float:
    day = pd.Timestamp(day)
    return ((day + pd.Timedelta(days=1)).tz_localize(tz) - day.tz_localize(tz)) / pd.Timedelta(hours=1)


def climate_normals(tmax: pd.Series, start_year: int = NORMALS_START_YEAR, end_year: int = NORMALS_END_YEAR,
                    smoothing_days: int = SMOOTHING_DAYS) -> pd.Series:
    """Normal daily maximum per leap-year day (index 1–366): mean over the years, then a centred moving
    average of `smoothing_days` that wraps around the year end."""
    if smoothing_days % 2 == 0:
        raise ValueError("smoothing_days must be odd")
    dates = pd.DatetimeIndex(tmax.index)
    chosen = (dates.year >= start_year) & (dates.year <= end_year)
    values = tmax[chosen]
    mean = values.groupby(leap_day_of_year(values.index)).mean().reindex(range(1, 367))
    if mean.isna().any():
        missing = list(mean.index[mean.isna()])[:5]
        raise ValueError(f"no data for day(s) {missing} of the normals period")
    half = smoothing_days // 2
    wrapped = np.concatenate([mean.to_numpy()[-half:], mean.to_numpy(), mean.to_numpy()[:half]]) if half else \
        mean.to_numpy()
    smooth = np.convolve(wrapped, np.ones(smoothing_days) / smoothing_days, mode="valid")
    return pd.Series(smooth, index=pd.RangeIndex(1, 367, name="day_of_year"), name="tmax_c")


def normal_for(dates, normals: pd.Series) -> np.ndarray:
    """Normal maximum of each (local) date."""
    return normals.reindex(leap_day_of_year(dates)).to_numpy()


def normal_max(index: pd.DatetimeIndex, normals: pd.Series, tz: str) -> pd.Series:
    """Future covariate of 06 §6.5: the normal maximum of each hour's local day."""
    return pd.Series(normal_for(local_day(index, tz), normals), index=index, name="normal_tmax_c")
