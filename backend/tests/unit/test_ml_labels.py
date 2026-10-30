"""ews.ml.labels on small hand-made series (design/06 §6.6, requirements 06 §6.1, D32, DD104, DD133;
ML-01, AL-01). The defaults must equal config/defaults.yaml."""
import numpy as np
import pandas as pd
import pytest

from ews.common.config import load_catalogue
from ews.ml import features, labels
from ews.ml.labels import HeatRules

UTC = "UTC"
IST = "Asia/Kolkata"
T0 = pd.DatetimeIndex(["2024-05-01 00:00"]).tz_localize(UTC)


def hourly(start: str, values) -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="1h", tz=UTC), dtype=float)


def test_defaults_equal_defaults_yaml():
    cat = load_catalogue()
    assert labels.GUST_LEVELS_KMH == {lvl: cat[f"wind_{lvl}_kmh"].default for lvl in ("yellow", "orange", "red")}
    assert labels.RAIN_24H_LEVELS_MM == {lvl: cat[f"rain_{lvl}_24h_mm"].default
                                         for lvl in ("yellow", "orange", "red")}
    assert labels.RAIN_INTENSITY_PERCENTILE == cat["rain_intensity_percentile"].default
    assert labels.RAIN_WET_HOUR_MIN_MM == cat["rain_wet_hour_min_mm"].default
    assert labels.RAIN_INTENSITY_FLOOR_MM == cat["rain_intensity_floor_mm"].default
    assert labels.HEAT_MIN_TMAX_C == cat["heat_min_tmax_c"].region_defaults
    for region in ("plains", "coastal", "hilly"):
        rules = HeatRules.for_region(region)
        assert (rules.departure_c, rules.severe_departure_c, rules.absolute_c, rules.severe_absolute_c) == tuple(
            cat[k].region_defaults[region] for k in ("heat_departure_c", "heat_severe_departure_c",
                                                     "heat_absolute_c", "heat_severe_absolute_c"))
    assert features.COVERAGE_MIN_PCT == cat["qc_coverage_min_pct"].default
    from ews.ml import normals
    assert (normals.NORMALS_START_YEAR, normals.NORMALS_END_YEAR, normals.SMOOTHING_DAYS) == (
        cat["normals_start_year"].default, cat["normals_end_year"].default, cat["normals_smoothing_days"].default)


def test_gust_windows_cover_72_hours():
    assert labels.GUST_WINDOWS[:2] == ((0, 3), (3, 6)) and labels.GUST_WINDOWS[7] == (21, 24)
    assert labels.GUST_WINDOWS[8:] == tuple((a, a + 6) for a in range(24, 72, 6))


def test_al01_gust_labels_per_window_and_level():
    gust = [10.0] * 80
    gust[2] = 52.0     # hour ending 02:00 → window (0, 3]
    gust[3] = 40.0     # ending 03:00 → still (0, 3]
    gust[30] = 65.0    # ending 30:00 → (24, 30]
    out = labels.gust_labels(hourly("2024-05-01 00:00", gust), T0)
    row = out.iloc[0]
    assert (row["gust_yellow_0_3h"], row["gust_orange_0_3h"], row["gust_red_0_3h"]) == (1, 1, 0)
    assert row["gust_yellow_3_6h"] == 0
    assert (row["gust_orange_24_30h"], row["gust_red_24_30h"]) == (1, 1)
    assert len(out.columns) == 3 * 16


def test_dd133_missing_hours_give_unknown_not_zero():
    gust = hourly("2024-05-01 00:00", [10.0, np.nan, np.nan, 10.0, 60.0, np.nan, 10.0])
    out = labels.window_labels(gust, T0, [(0, 3), (3, 6)], 50.0, name="g")
    assert np.isnan(out.loc[T0[0], "g_0_3h"])       # 1 of 3 hours present, no exceedance
    assert out.loc[T0[0], "g_3_6h"] == 1.0          # gap, but a known exceedance
    beyond = labels.window_labels(gust, T0, [(6, 9)], 50.0, name="g")
    assert np.isnan(beyond.iloc[0, 0])              # after the data


def test_d32_rain_burst_threshold_uses_wet_hours_and_the_floor():
    dry_mostly = pd.Series([0.0] * 9000 + list(np.linspace(0.1, 40.0, 1000)))
    p99_all = np.percentile(dry_mostly, 99)
    p99_wet = labels.wet_hour_percentile(dry_mostly)
    assert p99_all < p99_wet == pytest.approx(np.percentile(np.linspace(0.1, 40.0, 1000), 99))
    assert labels.rain_burst_threshold(dry_mostly) == pytest.approx(p99_wet)       # above 20
    light = pd.Series([0.0, 0.2, 1.0, 5.0])
    assert labels.rain_burst_threshold(light) == 20.0                              # floor
    assert labels.rain_burst_threshold(pd.Series([0.0, 0.0])) == 20.0              # no wet hours


def test_rain_intensity_labels():
    rain = hourly("2024-05-01 00:00", [0, 0, 0, 0, 25, 0, 0])
    out = labels.rain_intensity_labels(rain, T0, threshold_mm=20.0)
    assert out.iloc[0].to_dict() == {"rain_intensity_0_3h": 0.0, "rain_intensity_3_6h": 1.0}


def test_imd_rain_day_end():
    times = pd.DatetimeIndex(["2024-05-01 02:00", "2024-05-01 03:00", "2024-05-01 22:00"]).tz_localize(UTC)
    ends = labels.rain_day_end(times).strftime("%d %H:%M").tolist()
    assert ends == ["01 03:00", "02 03:00", "02 03:00"]
    assert labels.rain_day_end(times[:1], 2)[0] == pd.Timestamp("2024-05-03 03:00", tz=UTC)


def test_rain_24h_labels_per_rain_day():
    # hours ending 2024-05-01 04:00 … : rain day D0 for t0 = 1 May 03:00 is (1 May 03:00, 2 May 03:00]
    rain = [0.0] * 72
    rain[0] = 70.0                 # ends 04:00 on 1 May → D0
    rain[30] = 120.0               # ends 2 May 10:00 → D1
    series = hourly("2024-05-01 04:00", rain)
    t0 = pd.DatetimeIndex(["2024-05-01 03:00"]).tz_localize(UTC)
    row = labels.rain_24h_labels(series, t0).iloc[0]
    assert (row["rain_24h_yellow_D0"], row["rain_24h_orange_D0"]) == (1, 0)
    assert (row["rain_24h_orange_D1"], row["rain_24h_red_D1"]) == (1, 0)
    assert row["rain_24h_yellow_D2"] == 0


def test_rain_24h_partial_sum_counts_but_gaps_are_unknown():
    rain = hourly("2024-05-01 04:00", [70.0] + [np.nan] * 23)
    t0 = pd.DatetimeIndex(["2024-05-01 03:00"]).tz_localize(UTC)
    row = labels.rain_24h_labels(rain, t0, days=[0]).iloc[0]
    assert row["rain_24h_yellow_D0"] == 1.0 and np.isnan(row["rain_24h_orange_D0"])


@pytest.mark.parametrize("region,tmax,normal,level", [
    ("plains", 41.0, 36.5, 1),     # departure 4.5 → heatwave
    ("plains", 42.9, 36.5, 1),     # 6.4 → still heatwave (severe is *greater than* 6.4)
    ("plains", 43.0, 36.5, 2),     # 6.5 → severe
    ("plains", 39.5, 33.0, 0),     # departure 6.5 but below the 40 °C minimum
    ("coastal", 37.0, 32.5, 1),    # coastal minimum 37
    ("hilly", 30.0, 25.0, 1),
    ("plains", 45.0, 44.0, 1),     # absolute ≥ 45
    ("plains", 47.0, 46.0, 2),     # absolute ≥ 47
    ("plains", 44.9, 41.0, 0),
    ("plains", np.nan, 36.5, None),
    ("plains", 45.5, np.nan, 1),   # absolute rule needs no normal
    ("plains", 42.0, np.nan, None),
])
def test_heatwave_level_imd_rules(region, tmax, normal, level):
    got = labels.heatwave_level(tmax, normal, HeatRules.for_region(region))
    assert np.isnan(got) if level is None else got == level


def test_heatwave_labels_for_local_days_d1_to_d3():
    n = pd.Series(36.0, index=pd.RangeIndex(1, 367))
    tmax = pd.Series({pd.Timestamp("2024-05-02"): 41.0, pd.Timestamp("2024-05-03"): 43.0,
                      pd.Timestamp("2024-05-04"): 38.0})
    t0 = pd.DatetimeIndex(["2024-04-30 20:00"]).tz_localize(UTC)   # 1 May 01:30 IST → D1 = 2 May
    row = labels.heatwave_labels(tmax, n, t0, IST, HeatRules.for_region("plains")).iloc[0]
    assert (row["heatwave_orange_D1"], row["heatwave_red_D1"]) == (1, 0)
    assert (row["heatwave_orange_D2"], row["heatwave_red_D2"]) == (1, 1)
    assert (row["heatwave_orange_D3"], row["heatwave_red_D3"]) == (0, 0)
