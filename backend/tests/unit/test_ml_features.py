"""ews.ml.features and ews.ml.normals: golden values and small hand-made series (design/06 §6.5–6.6,
05 §5.5, §5.7, DD46, DD133; DP-06, ML-01)."""
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from ews.ml import features, normals

UTC = "UTC"
IST = "Asia/Kolkata"

# NWS heat index chart (°F): temperature → values for RH 40, 45, 50 … %. Two cells are left out:
# 80 °F at 95 % and 100 %, where the NWS high-humidity adjustment (part of the algorithm, 05 §5.5.1)
# exceeds the chart by 1.0–1.3 °C.
CHART_F = {80: [80, 80, 81, 81, 82, 82, 83, 84, 84, 85, 86],
           86: [85, 87, 88, 89, 91, 93, 95, 97, 100, 102, 105, 108, 112],
           90: [91, 93, 95, 97, 100, 103, 106, 109, 113, 117, 122, 127, 132],
           96: [101, 104, 108, 112, 116, 121, 126, 132],
           100: [109, 114, 118, 124, 129, 136],
           104: [119, 124, 131, 137],
           110: [136]}
GOLDEN = [((t - 32) * 5 / 9, 40 + 5 * i, (v - 32) * 5 / 9) for t, row in CHART_F.items() for i, v in enumerate(row)]


def hours(start: str, n: int, values=None, freq="1h") -> pd.Series:
    index = pd.date_range(start, periods=n, freq=freq, tz=UTC)
    return pd.Series(np.arange(n, dtype=float) if values is None else values, index=index, dtype=float)


@pytest.mark.parametrize("temp_c,rh,expected_c", GOLDEN)
def test_dp06_heat_index_matches_the_nws_table(temp_c, rh, expected_c):
    assert features.heat_index_c(temp_c, rh) == pytest.approx(expected_c, abs=0.3)


def test_heat_index_below_26_7_is_the_temperature_and_nan_propagates():
    assert features.heat_index_c(25.0, 90.0) == 25.0
    out = features.heat_index_c(pd.Series([30.0, np.nan, 35.0]), pd.Series([np.nan, 50.0, 50.0]))
    assert out.isna().tolist() == [True, True, False]


def test_heat_index_low_humidity_adjustment():
    """Below 13 % RH between 80 and 112 °F the NWS subtracts a correction."""
    t = (100 - 32) * 5 / 9
    assert features.heat_index_c(t, 10) < features.heat_index_c(t, 13)


def test_dd46_hourly_series_is_end_labelled_with_coverage():
    index = pd.date_range("2024-05-01 10:01", "2024-05-01 12:00", freq="1min", tz=UTC)
    readings = pd.DataFrame({"temp_c": 30.0, "rh_pct": 50.0, "pressure_msl_hpa": 1005.0, "wind_avg_kmh": 10.0,
                             "wind_gust_kmh": 20.0, "rain_mm": 0.1}, index=index)
    readings.loc["2024-05-01 10:30":"2024-05-01 10:30", "wind_gust_kmh"] = 55.0
    readings.loc["2024-05-01 11:01":"2024-05-01 11:20", "temp_c"] = np.nan   # 40 of 60 left: below 80 %
    h = features.hourly_series(readings)
    assert list(h.index) == list(pd.to_datetime(["2024-05-01 11:00", "2024-05-01 12:00"]).tz_localize(UTC))
    first = h.loc["2024-05-01 11:00"]
    assert first["wind_gust_kmh"] == 55.0 and first["rain_mm"] == pytest.approx(6.0)
    assert first["temp_max_c"] == 30.0
    assert np.isnan(h.loc["2024-05-01 12:00", "temp_c"]) and h.loc["2024-05-01 12:00", "rh_pct"] == 50.0


def test_hourly_rain_with_too_few_readings_is_missing_not_zero():
    index = pd.date_range("2024-05-01 10:01", periods=30, freq="1min", tz=UTC)
    h = features.hourly_series(pd.DataFrame({"rain_mm": 0.0}, index=index))
    assert np.isnan(h["rain_mm"].iloc[0])


def test_ml01_rolling_features():
    n = 30
    frame = pd.DataFrame({"temp_c": hours("2024-05-01", n).to_numpy(), "rh_pct": 50.0,
                          "pressure_msl_hpa": 1000 + 0.5 * np.arange(n), "wind_gust_kmh": 10.0,
                          "rain_mm": 1.0}, index=hours("2024-05-01", n).index)
    frame.iloc[25:, frame.columns.get_loc("wind_gust_kmh")] = 40.0
    frame = frame.drop(frame.index[10])  # one missing hour
    f = features.rolling_features(frame)
    t = pd.Timestamp("2024-05-01 05:00", tz=UTC)
    assert f.loc[t, "pressure_tendency_1h_hpa"] == pytest.approx(0.5)
    assert f.loc[t, "pressure_tendency_3h_hpa"] == pytest.approx(1.5)
    assert f.loc[t, "temp_change_3h_c"] == 3.0
    assert f.loc[t, "rain_3h_mm"] == 3.0
    assert np.isnan(f.loc[t, "rain_24h_mm"])                         # only 6 hours of history
    # the missing hour: 3 h windows need all 3 (80 % of 3 → 2.4), 24 h windows tolerate it
    assert np.isnan(f.loc[pd.Timestamp("2024-05-01 11:00", tz=UTC), "rain_3h_mm"])
    assert f.loc[pd.Timestamp("2024-05-02 01:00", tz=UTC), "rain_24h_mm"] == 23.0
    assert np.isnan(f.loc[pd.Timestamp("2024-05-01 10:00", tz=UTC), "pressure_tendency_1h_hpa"])
    assert f.loc[pd.Timestamp("2024-05-02 03:00", tz=UTC), "gust_trend_3h_kmh"] == pytest.approx(30.0)


def test_calendar_features_use_local_time():
    index = pd.DatetimeIndex(["2024-05-01 00:30", "2024-05-01 18:30"]).tz_localize(UTC)
    c = features.calendar_features(index, IST)
    assert c["hour_sin"].iloc[0] == pytest.approx(np.sin(2 * np.pi * 6 / 24))       # 06:00 IST
    assert c["hour_cos"].iloc[1] == pytest.approx(1.0)                             # 00:00 IST next day
    assert c["month"].tolist() == [5, 5]
    rolling = features.calendar_features(pd.DatetimeIndex(["2024-05-01 03:45"]).tz_localize(UTC), IST)
    assert rolling["hour_sin"].iloc[0] == pytest.approx(np.sin(2 * np.pi * 9.25 / 24))  # 07 §7.3


def test_leap_day_of_year():
    days = normals.leap_day_of_year(["2023-02-28", "2023-03-01", "2024-02-29", "2024-03-01", "2023-12-31"])
    assert days.tolist() == [59, 61, 60, 61, 366]


def test_daily_max_per_local_day():
    # local day 2 May = hours ending in (1 May 18:30 UTC, 2 May 18:30 UTC] = 19:00 … 18:00 UTC, 24 hours
    temp = hours("2024-05-01 19:00", 48, [30.0] * 48)
    temp.iloc[5] = 41.0     # ends 2 May 00:00 UTC (05:30 IST)
    temp.iloc[29] = 39.0    # ends 3 May 00:00 UTC
    tmax = normals.daily_max(temp, IST)
    assert tmax.to_dict() == {pd.Timestamp("2024-05-02"): 41.0, pd.Timestamp("2024-05-03"): 39.0}
    short = normals.daily_max(temp.drop(temp.index[40:45]), IST)  # 19 of 24 hours on 3 May: below 80 %
    assert short.loc[pd.Timestamp("2024-05-02")] == 41.0 and np.isnan(short.loc[pd.Timestamp("2024-05-03")])


def test_local_day_boundary_is_end_labelled():
    ends = pd.DatetimeIndex(["2024-05-01 18:30", "2024-05-01 19:30"]).tz_localize(UTC)  # 00:00 / 01:00 IST
    assert normals.local_day(ends, IST).strftime("%m-%d").tolist() == ["05-01", "05-02"]


def test_climate_normals_mean_smoothing_and_leap_day():
    dates = pd.date_range("1991-01-01", "2020-12-31", freq="D")
    doy = normals.leap_day_of_year(dates)
    tmax = pd.Series(30 + 5 * np.sin(2 * np.pi * (doy - 1) / 366), index=dates)
    tmax[dates.year == 2000] += 3       # one year 3 °C warmer → mean + 0.1
    tmax[pd.Timestamp("1985-06-01")] = 99.0  # outside the period: ignored
    n = normals.climate_normals(tmax, smoothing_days=1)
    assert list(n.index) == list(range(1, 367))
    assert n.loc[100] == pytest.approx(30 + 5 * np.sin(2 * np.pi * 99 / 366) + 0.1)
    assert n.loc[60] == pytest.approx(30 + 5 * np.sin(2 * np.pi * 59 / 366) + 3 / 8, abs=1e-9)  # 8 leap years
    smooth = normals.climate_normals(tmax)
    assert smooth.loc[1] == pytest.approx(n.loc[[359, 360, 361, 362, 363, 364, 365, 366, 1, 2, 3, 4, 5, 6, 7, 8]
                                                 [1:]].mean())   # wraps over the year end
    assert smooth.mean() == pytest.approx(n.mean())


def test_climate_normals_need_every_day():
    with pytest.raises(ValueError):
        normals.climate_normals(pd.Series([30.0], index=pd.DatetimeIndex(["2000-01-01"])))


def test_normal_max_of_the_local_day():
    n = pd.Series(np.arange(1, 367, dtype=float), index=pd.RangeIndex(1, 367))
    index = pd.DatetimeIndex(["2024-02-29 12:00", "2023-12-31 20:00"]).tz_localize(UTC)
    assert normals.normal_max(index, n, IST).tolist() == [60.0, 1.0]   # 20:00 UTC = 01:30 IST on 1 Jan


def test_dd133_ews_ml_needs_only_numpy_and_pandas():
    code = ("import sys, ews.ml.features, ews.ml.labels, ews.ml.normals; "
            "bad = [m for m in ('ews.common', 'asyncpg', 'yaml', 'torch') if m in sys.modules]; "
            "print(', '.join(bad)); sys.exit(1 if bad else 0)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
