"""Model input features from hourly series, shared by training and the worker (design/06 §6.5, 05 §5.5, DD133).

Pure numpy/pandas, no `ews.common` imports: the Kaggle notebooks import this module. Every series has a
UTC, **end-labelled** index (the value at 11:00 covers 10:00–11:00, DD46).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

COVERAGE_MIN_PCT = 80          # qc_coverage_min_pct
HOUR = pd.Timedelta(hours=1)

MEAN_COLUMNS = ("temp_c", "rh_pct", "pressure_msl_hpa", "wind_avg_kmh")


def heat_index_c(temp_c, rh_pct):
    """NOAA heat index in °C (05 §5.5.1): Rothfusz regression with the NWS low- and high-humidity
    adjustments, Steadman's simple formula where its average with T is below 80 °F; T itself below 26.7 °C.
    Works on scalars, arrays and Series; NaN in → NaN out."""
    t_c = np.asarray(temp_c, dtype=float)
    rh = np.asarray(rh_pct, dtype=float)
    t = t_c * 9 / 5 + 32
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    full = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh - 0.00683783 * t * t
            - 0.05481717 * rh * rh + 0.00122874 * t * t * rh + 0.00085282 * t * rh * rh
            - 0.00000199 * t * t * rh * rh)
    with np.errstate(invalid="ignore"):
        dry = (rh < 13) & (t >= 80) & (t <= 112)
        full = np.where(dry, full - (13 - rh) / 4 * np.sqrt(np.clip(17 - np.abs(t - 95), 0, None) / 17), full)
        humid = (rh > 85) & (t >= 80) & (t <= 87)
        full = np.where(humid, full + (rh - 85) / 10 * (87 - t) / 5, full)
        hi_f = np.where((simple + t) / 2 < 80, simple, full)
        out = np.where(t < 80, t_c, (hi_f - 32) * 5 / 9)
    out = np.where(np.isnan(t_c) | np.isnan(rh), np.nan, out)
    if isinstance(temp_c, pd.Series):
        return pd.Series(out, index=temp_c.index, name="heat_index_c")
    return out if out.ndim else float(out)


def regular(frame: pd.DataFrame | pd.Series, freq: pd.Timedelta = HOUR):
    """The same data on a gap-free grid (missing hours become NaN rows), so shifts are by time."""
    if len(frame) == 0:
        return frame
    return frame.reindex(pd.date_range(frame.index[0], frame.index[-1], freq=freq))


def hourly_series(readings: pd.DataFrame, interval_s: int = 60,
                  coverage_min_pct: float = COVERAGE_MIN_PCT) -> pd.DataFrame:
    """Readings (index = reading time) → end-labelled hours like `series_1h` (05 §5.7).

    A reading at ts belongs to the hour ending at the first full hour ≥ ts. Each value is NaN when fewer
    than coverage_min_pct of the expected readings of that column are present (gaps are not calm or dry).
    """
    expected = 3600 / interval_s * coverage_min_pct / 100
    bins = readings.resample("1h", label="right", closed="right")
    out = pd.DataFrame(index=bins.size().index)
    for column in readings.columns:
        count = bins[column].count()
        if column in MEAN_COLUMNS:
            out[column] = bins[column].mean().where(count >= expected)
        if column == "temp_c":
            out["temp_max_c"] = bins[column].max().where(count >= expected)
            out["temp_min_c"] = bins[column].min().where(count >= expected)
        elif column == "wind_gust_kmh":
            out[column] = bins[column].max().where(count >= expected)
        elif column == "rain_mm":
            out[column] = bins[column].sum(min_count=1).where(count >= expected)
    return regular(out)


def _rolling(series: pd.Series, hours: int, how: str, coverage_min_pct: float) -> pd.Series:
    roll = series.rolling(hours, min_periods=1)
    value = roll.sum() if how == "sum" else roll.mean()
    return value.where(roll.count() >= hours * coverage_min_pct / 100)


def rolling_features(hourly: pd.DataFrame, coverage_min_pct: float = COVERAGE_MIN_PCT) -> pd.DataFrame:
    """Past covariates of 06 §6.5 from an hourly frame (temp_c, rh_pct, pressure_msl_hpa, wind_gust_kmh,
    rain_mm). Windows end at the row's time; NaN below coverage; sums over the present hours."""
    h = regular(hourly)
    out = pd.DataFrame(index=h.index)
    p = h["pressure_msl_hpa"]
    out["pressure_tendency_1h_hpa"] = p - p.shift(1)
    out["pressure_tendency_3h_hpa"] = p - p.shift(3)
    out["rain_3h_mm"] = _rolling(h["rain_mm"], 3, "sum", coverage_min_pct)
    out["rain_24h_mm"] = _rolling(h["rain_mm"], 24, "sum", coverage_min_pct)
    gust = _rolling(h["wind_gust_kmh"], 3, "mean", coverage_min_pct)
    out["gust_trend_3h_kmh"] = gust - gust.shift(3)       # last 3 h mean − the 3 h before (positive = rising)
    out["temp_change_3h_c"] = h["temp_c"] - h["temp_c"].shift(3)
    out["heat_index_c"] = heat_index_c(h["temp_c"], h["rh_pct"])
    return out


def calendar_features(index: pd.DatetimeIndex, tz: str) -> pd.DataFrame:
    """Hour of day (fractional for rolling hours, 07 §7.3) and day of year in the site's local time as
    sin/cos, plus the month (DD133)."""
    local = index.tz_convert(tz)
    hour = local.hour + local.minute / 60
    day = (local.dayofyear - 1) + hour / 24
    out = pd.DataFrame(index=index)
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    out["doy_sin"] = np.sin(2 * np.pi * day / 365.25)
    out["doy_cos"] = np.cos(2 * np.pi * day / 365.25)
    out["month"] = local.month
    return out
