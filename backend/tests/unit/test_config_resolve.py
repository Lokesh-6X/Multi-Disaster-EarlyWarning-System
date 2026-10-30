"""TST-10: config resolution kit → site → onboarding → region default → default (design/04 §4.2, CFG-01, CFG-06)."""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ews.common import config
from ews.common.config import ConfigSnapshot, Resolved, ScopeValues

CATALOGUE = config.load_catalogue()
ONBOARDING_RAIN = "onboarding.rain_1h_wet_percentile"


def snapshot(site=None, kits=None, onboarding=None) -> ConfigSnapshot:
    return ConfigSnapshot(
        catalogue=CATALOGUE,
        site=ScopeValues(site or {}, version_id=1, version=1),
        kits={kit_id: ScopeValues(values, version_id=10 + i, version=1)
              for i, (kit_id, values) in enumerate((kits or {}).items())},
        onboarding=onboarding or {})


EXAMPLE = snapshot(
    site={"site_name": "ABC College", "lat": 13.08, "lon": 80.27, "elevation_m": 6, "region_type": "coastal",
          "wind_red_kmh": 58},
    kits={"KIT-01": {"kit_zone": "Main Block Rooftop", "lat": 13.081, "lon": 80.271, "elevation_m": 30,
                     "exposure": "rooftop", "cal_temp_offset_c": -0.5},
          "KIT-02": {"kit_zone": "Sports Ground", "lat": 13.079, "lon": 80.269, "exposure": "open_ground",
                     "wind_orange_kmh": 35, "wind_red_kmh": 45}})


def test_cfg01_kit_value_wins():
    assert EXAMPLE.resolve("wind_red_kmh", "KIT-02") == Resolved(45, "kit")


def test_cfg01_site_value_when_kit_has_none():
    assert EXAMPLE.resolve("wind_red_kmh", "KIT-01") == Resolved(58, "site")


def test_cfg01_default_when_nobody_sets_it():
    assert EXAMPLE.resolve("wind_yellow_kmh", "KIT-01") == Resolved(39, "default")
    assert EXAMPLE.resolve("timezone") == Resolved("Asia/Kolkata", "default")


def test_cfg01_kit_without_own_elevation_uses_the_site():
    """DP-05: a kit without its own elevation uses the site's."""
    assert EXAMPLE.resolve("elevation_m", "KIT-01") == Resolved(30, "kit")
    assert EXAMPLE.resolve("elevation_m", "KIT-02") == Resolved(6, "site")


def test_cfg01_site_resolution_ignores_kit_values():
    assert EXAMPLE.resolve("wind_red_kmh") == Resolved(58, "site")
    assert EXAMPLE.resolve("wind_orange_kmh") == Resolved(50, "default")


def test_cfg02_value_at_a_disallowed_level_is_never_used():
    """The validator rejects these on save (M1.2); the resolver ignores them regardless."""
    snap = snapshot(site={"cal_temp_offset_c": 2.0, "region_type": "plains"},
                    kits={"K": {"timezone": "Europe/London", "alert_watch_on_prob": 0.9}})
    assert snap.resolve("timezone", "K") == Resolved("Asia/Kolkata", "default")
    assert snap.resolve("alert_watch_on_prob", "K") == Resolved(0.30, "default")
    assert snap.resolve("cal_temp_offset_c", "K") == Resolved(0, "default")


def test_region_default_follows_the_site_region_type():
    assert EXAMPLE.resolve("heat_min_tmax_c", "KIT-01") == Resolved(37, "default", region_type="coastal")
    for region, expected in (("plains", 40), ("coastal", 37), ("hilly", 30)):
        assert snapshot(site={"region_type": region}).resolve("heat_min_tmax_c") == \
            Resolved(expected, "default", region_type=region)


def test_region_default_without_region_type_has_no_value():
    assert snapshot().resolve("heat_min_tmax_c") == Resolved(None, "default")


def test_site_value_beats_region_default():
    snap = snapshot(site={"region_type": "hilly", "heat_min_tmax_c": 33})
    assert snap.resolve("heat_min_tmax_c") == Resolved(33, "site")


def test_onboarding_value_before_and_after():
    """Before onboarding: static fallback 30, source default; after: the computed value (DD104)."""
    assert EXAMPLE.resolve("rain_intensity_1h_mm", "KIT-01") == Resolved(30, "default")
    onboarded = snapshot(onboarding={ONBOARDING_RAIN: 41.5})
    assert onboarded.resolve("rain_intensity_1h_mm") == Resolved(41.5, "onboarding")


def test_site_and_kit_beat_onboarding():
    snap = snapshot(site={"rain_intensity_1h_mm": 35}, kits={"K": {"rain_intensity_1h_mm": 25}},
                    onboarding={ONBOARDING_RAIN: 41.5})
    assert snap.resolve("rain_intensity_1h_mm") == Resolved(35, "site")
    assert snap.resolve("rain_intensity_1h_mm", "K") == Resolved(25, "kit")


def test_required_key_not_set_resolves_to_none():
    assert snapshot().resolve("site_name") == Resolved(None, "default")


def test_unknown_key_and_unknown_kit_are_errors():
    with pytest.raises(KeyError, match="unknown config key"):
        EXAMPLE.resolve("wind_purple_kmh")
    with pytest.raises(KeyError, match="unknown kit"):
        EXAMPLE.resolve("wind_red_kmh", "KIT-99")


def test_cfg06_effective_covers_every_key_with_a_valid_source():
    effective = EXAMPLE.effective("KIT-02")
    assert set(effective) == set(CATALOGUE)
    assert {r.source for r in effective.values()} <= set(config.SOURCES)
    assert effective["wind_orange_kmh"].source == "kit"
    assert effective["site_name"] == Resolved("ABC College", "site")


def test_value_shortcut():
    assert EXAMPLE.value("wind_orange_kmh", "KIT-02") == 35


# --- property: the most specific allowed level that sets the key wins ---------------------------

@st.composite
def cases(draw):
    key = draw(st.sampled_from(sorted(CATALOGUE)))
    meta = CATALOGUE[key]
    # region_type is itself a key: under test, only set_site may set it
    region = None if key == "region_type" else draw(st.sampled_from([None, *config.REGIONS]))
    set_kit, set_site, set_onboarding = draw(st.booleans()), draw(st.booleans()), draw(st.booleans())
    ask_kit = draw(st.booleans())
    site = {"region_type": region} if region else {}
    if set_site:
        site[key] = "site-value"
    kits = {"K": {key: "kit-value"} if set_kit else {}}
    onboarding = {meta.computed_from: "onboarding-value"} if set_onboarding and meta.computed_from else {}
    return key, meta, region, set_kit, set_site, set_onboarding, ask_kit, snapshot(site, kits, onboarding)


@settings(max_examples=500, deadline=None)
@given(cases())
def test_property_most_specific_allowed_level_wins(case):
    key, meta, region, set_kit, set_site, set_onboarding, ask_kit, snap = case
    # Levels from most to least specific; the first one that is allowed and set wins
    levels = [
        (ask_kit and meta.kit_allowed and set_kit, Resolved("kit-value", "kit")),
        (meta.site_allowed and set_site, Resolved("site-value", "site")),
        (bool(meta.computed_from) and set_onboarding, Resolved("onboarding-value", "onboarding")),
        (region in meta.region_defaults, Resolved(meta.region_defaults.get(region), "default", region_type=region)),
        (True, Resolved(meta.default, "default")),
    ]
    expected = next(result for applies, result in levels if applies)
    assert snap.resolve(key, "K" if ask_kit else None) == expected


@settings(max_examples=200, deadline=None)
@given(key=st.sampled_from(sorted(CATALOGUE)), site_set=st.booleans())
def test_property_a_kit_override_changes_only_its_own_kit(key, site_set):
    site = {key: "site-value"} if site_set else {}
    snap = snapshot(site, {"A": {key: "kit-value"}, "B": {}})
    assert snap.resolve(key, "B") == snap.resolve(key)
    if CATALOGUE[key].kit_allowed:
        assert snap.resolve(key, "A") == Resolved("kit-value", "kit")
    else:
        assert snap.resolve(key, "A") == snap.resolve(key)
