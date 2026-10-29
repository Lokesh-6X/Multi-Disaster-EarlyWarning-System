"""Key catalogue in config/defaults.yaml (design/04 §4.3, §4.4, §4.7, CFG-01, CFG-02)."""
import pytest

from ews.common import config


@pytest.fixture(scope="module")
def catalogue():
    return config.load_catalogue()


def test_catalogue_has_about_130_keys(catalogue):
    assert 120 <= len(catalogue) <= 140


@pytest.mark.parametrize("key", ["site_name", "lat", "wind_orange_kmh", "rain_intensity_1h_mm", "heat_min_tmax_c",
                                 "alert_warning_off_prob", "advice_high_wind", "report_horizons_h", "retention_rejected_days"])
def test_known_keys_present(catalogue, key):
    assert key in catalogue


def test_every_key_is_snake_case_with_description(catalogue):
    for key, meta in catalogue.items():
        assert key == key.lower() and " " not in key, key
        assert meta.description, key


def test_defaults_match_their_type(catalogue):
    for key, meta in catalogue.items():
        for value in ([meta.default] if meta.default is not None else []) + list(meta.region_defaults.values()):
            config.check_type(meta.value_type, value)  # raises on mismatch


def test_defaults_respect_their_own_rules(catalogue):
    for key, meta in catalogue.items():
        for value in ([meta.default] if meta.default is not None else []) + list(meta.region_defaults.values()):
            rules = meta.rules
            if "min" in rules:
                assert value >= rules["min"], key
            if "max" in rules:
                assert value <= rules["max"], key
            if "allowed" in rules:
                assert value in rules["allowed"], key
            if "max_length" in rules:
                assert len(value) <= rules["max_length"], key


def test_region_defaults_cover_every_region(catalogue):
    """DD38: region defaults have one value per region type."""
    heat = [k for k, m in catalogue.items() if m.region_defaults]
    assert set(heat) == {"heat_min_tmax_c", "heat_departure_c", "heat_severe_departure_c", "heat_absolute_c",
                         "heat_severe_absolute_c", "heat_index_caution_c", "heat_index_danger_c"}
    for key in heat:
        assert set(catalogue[key].region_defaults) == {"plains", "coastal", "hilly"}
        assert catalogue[key].default is None


def test_required_keys_match_validation_step_4(catalogue):
    """04 §4.4 step 4: site: site_name, lat, lon, elevation_m, region_type; kit: kit_zone, lat, lon, exposure."""
    at_site = {k for k, m in catalogue.items() if "site" in m.required}
    at_kit = {k for k, m in catalogue.items() if "kit" in m.required}
    assert at_site == {"site_name", "lat", "lon", "elevation_m", "region_type"}
    assert at_kit == {"kit_zone", "lat", "lon", "exposure"}


def test_required_keys_may_be_set_where_required(catalogue):
    for key, meta in catalogue.items():
        assert set(meta.required) <= set(meta.levels), key


def test_keys_without_default_level_have_no_default(catalogue):
    for key, meta in catalogue.items():
        if "default" not in meta.levels:
            assert meta.default is None and not meta.region_defaults, key


def test_default_only_keys_of_4_3_9(catalogue):
    """DD40: security, limits and retention can be set only in defaults.yaml."""
    for key in ["session_hours", "login_lockout_attempts", "password_min_length", "rate_user_per_min",
                "command_wait_s", "retention_forecast_days", "retention_rejected_days"]:
        assert catalogue[key].levels == ("default",), key


def test_probability_keys_are_default_and_site_only(catalogue):
    """DD39: probability thresholds at default and site level only."""
    for key in ["alert_watch_on_prob", "alert_watch_off_prob", "alert_warning_on_prob", "alert_warning_off_prob"]:
        assert catalogue[key].levels == ("default", "site"), key


@pytest.mark.parametrize("group, members", [
    ("wind_levels", ["wind_yellow_kmh", "wind_orange_kmh", "wind_red_kmh"]),
    ("rain_levels", ["rain_yellow_24h_mm", "rain_orange_24h_mm", "rain_red_24h_mm"]),
    ("heat_departure", ["heat_departure_c", "heat_severe_departure_c"]),
    ("heat_absolute", ["heat_absolute_c", "heat_severe_absolute_c"]),
    ("heat_index", ["heat_index_caution_c", "heat_index_danger_c"]),
    ("probabilities", ["alert_watch_off_prob", "alert_watch_on_prob", "alert_warning_off_prob", "alert_warning_on_prob"]),
])
def test_order_groups_hold_for_the_defaults(catalogue, group, members):
    """04 §4.4 step 7 cross-key rules hold for the shipped defaults (probabilities: watch_on <= warning_off)."""
    assert {k for k, m in catalogue.items() if m.rules.get("order") == group} == set(members)
    for region in ("plains", "coastal", "hilly"):
        values = [catalogue[k].default if catalogue[k].default is not None else catalogue[k].region_defaults[region]
                  for k in members]
        if group == "probabilities":
            off, on, w_off, w_on = values
            assert off < on <= w_off < w_on
        else:
            assert values == sorted(values) and len(set(values)) == len(values)


def test_computed_default_of_rain_intensity(catalogue):
    """D32, DD104: computed from onboarding, static fallback 30 mm."""
    meta = catalogue["rain_intensity_1h_mm"]
    assert meta.computed_from == "onboarding.rain_1h_wet_percentile" and meta.default == 30


@pytest.mark.parametrize("bad, message", [
    ({"x": {"type": "number", "levels": ["default"], "default": 1}}, "description"),
    ({"x": {"type": "float", "levels": ["default"], "default": 1, "description": "d"}}, "type"),
    ({"x": {"type": "number", "levels": ["everywhere"], "default": 1, "description": "d"}}, "levels"),
    ({"x": {"type": "integer", "levels": ["default"], "default": 1.5, "description": "d"}}, "integer"),
    ({"x": {"type": "number", "levels": ["default"], "default": 1, "description": "d", "colour": "red"}}, "unknown field"),
    ({"x": {"type": "number", "levels": ["default"], "description": "d", "region_defaults": {"plains": 1}}}, "region"),
    ({"X-y": {"type": "number", "levels": ["default"], "default": 1, "description": "d"}}, "snake_case"),
])
def test_invalid_catalogue_entries_are_rejected(bad, message):
    with pytest.raises(config.CatalogueError, match=message):
        config.parse_catalogue(bad)


def test_boolean_is_not_a_number():
    with pytest.raises(config.CatalogueError):
        config.check_type("number", True)
