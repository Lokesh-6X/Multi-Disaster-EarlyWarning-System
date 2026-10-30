"""TST-10: config validation and override scope (design/04 §4.4, CFG-02, CFG-03)."""
import pytest

from ews.common import config
from ews.common.config import ConfigSnapshot, ScopeValues
from ews.common.config_validation import ORDER_GROUPS, Problem, great_circle_km, validate

CATALOGUE = config.load_catalogue()

SITE = {"site_name": "ABC College", "lat": 13.08, "lon": 80.27, "elevation_m": 6, "region_type": "coastal"}
KIT_01 = {"kit_zone": "Main Block Rooftop", "lat": 13.081, "lon": 80.271, "exposure": "rooftop"}
KIT_02 = {"kit_zone": "Sports Ground", "lat": 13.079, "lon": 80.269, "exposure": "open_ground",
          "wind_orange_kmh": 45}

BASE = ConfigSnapshot(catalogue=CATALOGUE, site=ScopeValues(SITE, 1, 1),
                      kits={"KIT-01": ScopeValues(KIT_01, 2, 1), "KIT-02": ScopeValues(KIT_02, 3, 1)})


def codes(problems: list[Problem]) -> set[tuple[str, str, str | None]]:
    return {(p.code, p.key, p.kit_id) for p in problems}


def test_valid_site_and_kits_have_no_problems():
    assert validate(BASE, site=SITE, kits={"KIT-01": KIT_01, "KIT-02": KIT_02}) == []


def test_defaults_alone_are_valid():
    """The shipped defaults never break a cross-key rule."""
    assert validate(BASE, site=SITE) == []


def test_step1_unknown_key():
    assert codes(validate(BASE, site={**SITE, "wind_purple_kmh": 3})) == {("UNKNOWN_KEY", "wind_purple_kmh", None)}


def test_cfg02_timezone_on_a_kit_is_not_allowed():
    problems = validate(BASE, kits={"KIT-02": {**KIT_02, "timezone": "Asia/Kolkata"}})
    assert codes(problems) == {("OVERRIDE_NOT_ALLOWED", "timezone", "KIT-02")}
    assert problems[0].message == "timezone cannot be set on KIT-02"
    assert problems[0].as_error() == {"field": "values.timezone", "code": "OVERRIDE_NOT_ALLOWED",
                                      "message": "timezone cannot be set on KIT-02"}


@pytest.mark.parametrize("key", sorted(k for k, m in CATALOGUE.items() if "kit" not in m.levels))
def test_cfg02_every_key_not_allowed_on_a_kit(key):
    meta = CATALOGUE[key]
    value = meta.default if meta.default is not None else next(iter(meta.region_defaults.values()), "x")
    assert ("OVERRIDE_NOT_ALLOWED", key, "KIT-01") in codes(validate(BASE, kits={"KIT-01": {**KIT_01, key: value}}))


@pytest.mark.parametrize("key", sorted(k for k, m in CATALOGUE.items() if "site" not in m.levels))
def test_cfg02_every_key_not_allowed_on_the_site(key):
    meta = CATALOGUE[key]
    value = meta.default if meta.default is not None else next(iter(meta.region_defaults.values()), "x")
    assert ("OVERRIDE_NOT_ALLOWED", key, None) in codes(validate(BASE, site={**SITE, key: value}))


@pytest.mark.parametrize("key, value, code", [
    ("wind_red_kmh", "fast", "TYPE"),
    ("sampling_interval_s", 60.5, "TYPE"),
    ("kit_enabled", 1, "TYPE"),
    ("wind_red_kmh", 500, "OUT_OF_RANGE"),
    ("sampling_interval_s", 45, "OUT_OF_RANGE"),
    ("exposure", "basement", "OUT_OF_RANGE"),
    ("kit_zone", "", "OUT_OF_RANGE"),
    ("advice_high_wind", "x" * 501, "OUT_OF_RANGE"),
])
def test_step3_type_and_allowed_values_on_a_kit(key, value, code):
    assert codes(validate(BASE, kits={"KIT-01": {**KIT_01, key: value}})) == {(code, key, "KIT-01")}


def test_step3_timezone_must_be_an_iana_name():
    assert codes(validate(BASE, site={**SITE, "timezone": "Asia/Bangalore"})) == {("OUT_OF_RANGE", "timezone", None)}
    assert validate(BASE, site={**SITE, "timezone": "Asia/Kolkata"}) == []


def test_step3_odd_rule():
    """normals_smoothing_days is default-only, so its value rule is checked directly."""
    from ews.common.config_validation import _check_value

    assert _check_value(CATALOGUE["normals_smoothing_days"], 14, None).code == "OUT_OF_RANGE"
    assert _check_value(CATALOGUE["normals_smoothing_days"], 15, None) is None


def test_step4_required_keys_on_site_and_kit():
    problems = validate(BASE, site={"site_name": "ABC"}, kits={"KIT-03": {"lat": 13.08, "lon": 80.27}},
                        new_kits={"KIT-03"})
    assert codes(problems) == {("REQUIRED", k, None) for k in ("lat", "lon", "elevation_m", "region_type")} | \
        {("REQUIRED", k, "KIT-03") for k in ("kit_zone", "exposure")}


def test_step5_invalid_coordinates():
    problems = validate(BASE, kits={"KIT-01": {**KIT_01, "lat": 91}})
    assert ("INVALID_COORDINATES", "lat", "KIT-01") in codes(problems)


def test_step5_kit_outside_the_site_area():
    far = {**KIT_01, "lat": 13.20}  # ≈ 13 km north
    assert codes(validate(BASE, kits={"KIT-01": far})) == {("KIT_OUTSIDE_SITE", "lat", "KIT-01")}


def test_step5_site_move_leaves_a_kit_outside():
    """A site save is checked against every kit."""
    moved = {**SITE, "lat": 13.10, "site_radius_km": 2.0}
    assert {("KIT_OUTSIDE_SITE", "lat", "KIT-01"), ("KIT_OUTSIDE_SITE", "lat", "KIT-02")} == \
        codes(validate(BASE, site=moved))


def test_great_circle_distance():
    assert great_circle_km(13.08, 80.27, 13.08, 80.27) == 0
    assert great_circle_km(0, 0, 1, 0) == pytest.approx(111.19, abs=0.01)


def test_step6_duplicate_kit_id_and_zone():
    new = {"kit_zone": "sports ground", "lat": 13.08, "lon": 80.27, "exposure": "rooftop"}
    assert codes(validate(BASE, kits={"KIT-02": new}, new_kits={"KIT-02"})) == {("DUPLICATE_KIT_ID", "kit_id", "KIT-02")}
    assert codes(validate(BASE, kits={"KIT-03": new}, new_kits={"KIT-03"})) == {("DUPLICATE_ZONE", "kit_zone", "KIT-03")}


def test_step6_zone_of_a_retired_kit_can_be_reused():
    retired = ConfigSnapshot(catalogue=CATALOGUE, site=BASE.site,
                             kits={**BASE.kits, "KIT-02": ScopeValues({**KIT_02, "kit_enabled": False})})
    new = {"kit_zone": "Sports Ground", "lat": 13.08, "lon": 80.27, "exposure": "rooftop"}
    assert validate(retired, kits={"KIT-03": new}, new_kits={"KIT-03"}) == []


def test_bad_kit_id():
    assert ("RULE_VIOLATION", "kit_id", "KIT 9") in codes(validate(BASE, kits={"KIT 9": KIT_01}, new_kits={"KIT 9"}))


def test_step7_threshold_order_on_a_kit():
    problems = validate(BASE, kits={"KIT-02": {**KIT_02, "wind_red_kmh": 40}})
    assert codes(problems) == {("THRESHOLD_ORDER", "wind_orange_kmh", "KIT-02")}
    assert problems[0].message == "Yellow < Orange < Red is required on KIT-02 (39 < 45 < 40)"


def test_step7_site_save_that_breaks_a_kit():
    """04 §4.4: wind_yellow_kmh 46 is fine for the site (46 < 50 < 62) but breaks KIT-02 (orange 45)."""
    problems = validate(BASE, site={**SITE, "wind_yellow_kmh": 46})
    assert codes(problems) == {("THRESHOLD_ORDER", "wind_yellow_kmh", "KIT-02")}
    assert "on KIT-02 (46 < 45 < 62)" in problems[0].message


def test_step7_site_level_break_is_reported_once():
    problems = validate(BASE, site={**SITE, "rain_orange_24h_mm": 300})
    assert codes(problems) == {("THRESHOLD_ORDER", "rain_orange_24h_mm", None)}


def test_step7_retired_kits_do_not_block_site_saves():
    retired = ConfigSnapshot(catalogue=CATALOGUE, site=BASE.site,
                             kits={**BASE.kits, "KIT-02": ScopeValues({**KIT_02, "kit_enabled": False})})
    assert validate(retired, site={**SITE, "wind_yellow_kmh": 46}) == []


@pytest.mark.parametrize("values, key", [
    ({"alert_watch_off_prob": 0.35}, "alert_watch_off_prob"),       # off ≥ on
    ({"alert_warning_off_prob": 0.25}, "alert_warning_off_prob"),   # warning off < watch on
    ({"alert_warning_on_prob": 0.45}, "alert_warning_on_prob"),     # warning on = warning off
    ({"qc_temp_min_c": 60}, "qc_temp_min_c"),
    ({"heat_severe_departure_c": 4.5}, "heat_severe_departure_c"),
    ({"normals_start_year": 2020}, "normals_start_year"),
])
def test_step7_order_groups(values, key):
    assert codes(validate(BASE, site={**SITE, **values})) == {("THRESHOLD_ORDER", key, None)}


def test_step7_watch_on_may_equal_warning_off():
    assert validate(BASE, site={**SITE, "alert_watch_on_prob": 0.45}) == []


def test_step7_offline_timeout_at_least_twice_the_sampling_interval():
    """Checked on the kit, where sampling_interval_s may be longer than at the site."""
    problems = validate(BASE, kits={"KIT-01": {**KIT_01, "sampling_interval_s": 300}})
    assert codes(problems) == {("RULE_VIOLATION", "kit_offline_timeout_s", "KIT-01")}
    assert validate(BASE, site={**SITE, "kit_offline_timeout_s": 600},
                    kits={"KIT-01": {**KIT_01, "sampling_interval_s": 300}}) == []


def test_step7_normals_period_span():
    problems = validate(BASE, site={**SITE, "normals_start_year": 2001, "normals_end_year": 2015})
    assert codes(problems) == {("RULE_VIOLATION", "normals_end_year", None)}


def test_all_problems_reported_together():
    problems = validate(BASE, kits={"KIT-02": {**KIT_02, "timezone": "UTC", "wind_red_kmh": 40, "mount_height_m": 99,
                                               "lat": 13.3}})
    assert {p.code for p in problems} == {"OVERRIDE_NOT_ALLOWED", "THRESHOLD_ORDER", "OUT_OF_RANGE",
                                          "KIT_OUTSIDE_SITE"}


def test_a_bad_value_does_not_cause_a_crash_in_later_steps():
    problems = validate(BASE, kits={"KIT-02": {**KIT_02, "wind_red_kmh": "fast"}})
    assert codes(problems) == {("TYPE", "wind_red_kmh", "KIT-02")}


def test_every_order_tag_in_defaults_names_a_group_with_that_key():
    tagged = {(m.rules["order"], k) for k, m in CATALOGUE.items() if "order" in m.rules}
    in_code = {(group, k) for group, (keys, _, _) in ORDER_GROUPS.items() for k in keys}
    assert tagged == in_code
