"""YAML import, checks without a database: file structure, identifiers, recipients, problem paths and the
shipped site files (design/04 §4.6, DD41, DD132, TST-10, CFG-03)."""
import uuid

import pytest
import yaml

from ews.common.config import ConfigSnapshot, ScopeValues, load_catalogue
from ews.common.config_import import ImportFileError, ImportPlan, Recipient, parse
from ews.common.ids import uuid7
from ews.common.settings import REPO_ROOT

CATALOGUE = load_catalogue()
SITE = {"site_name": "ABC College", "lat": 13.08, "lon": 80.27, "elevation_m": 6, "region_type": "coastal"}
KIT = {"kit_zone": "Main Block Rooftop", "lat": 13.081, "lon": 80.271, "exposure": "rooftop"}


def empty() -> ConfigSnapshot:
    return ConfigSnapshot(CATALOGUE)


def existing() -> ConfigSnapshot:
    return ConfigSnapshot(CATALOGUE, site=ScopeValues(SITE, 1, 1), kits={"KIT-01": ScopeValues(KIT, 2, 1)})


def plan(data, snapshot=None, site_id=None, recipients=None) -> ImportPlan:
    return ImportPlan(data, snapshot or empty(), site_id, recipients or {})


def fields(p: ImportPlan) -> dict[str, str]:
    return {problem.field: problem.code for problem in p.problems}


def new_file(**extra):
    return {"site": {"site_id": "abc", **SITE}, "kits": [{"kit_id": "KIT-01", **KIT}], **extra}


@pytest.mark.parametrize("name", ["example-site.yaml", "demo-site.yaml"])
def test_dd132_shipped_site_files_are_valid(name):
    data = parse((REPO_ROOT / "config" / name).read_text(encoding="utf-8"))
    p = plan(data)
    assert p.problems == []
    assert p.site_status == "created" and set(p.kit_status.values()) == {"created"}
    assert all(s == "created" for s in p.recipient_status.values()) and p.recipients


def test_design_example_is_valid():
    """The example file in design/04 §4.6 passes its own validator."""
    text = (REPO_ROOT / "design" / "04-configuration.md").read_text(encoding="utf-8")
    block = text.split("## 4.6", 1)[1].split("```yaml\n", 1)[1].split("```", 1)[0]
    p = plan(parse(block))
    assert p.problems == [] and set(p.kit_status) == {"KIT-01", "KIT-02"}


def test_shipped_site_ids():
    example = yaml.safe_load((REPO_ROOT / "config" / "example-site.yaml").read_text(encoding="utf-8"))
    demo = yaml.safe_load((REPO_ROOT / "config" / "demo-site.yaml").read_text(encoding="utf-8"))
    assert example["site"]["site_id"] == "abc" and example["site"]["site_name"] == "ABC College"
    assert [k["kit_id"] for k in example["kits"]] == ["KIT-01"]
    assert demo["site"]["site_id"] == "demo"


@pytest.mark.parametrize("text", ["site: [unclosed", "- just\n- a list", "42", ""])
def test_unreadable_file_is_rejected_as_a_whole(text):
    with pytest.raises(ImportFileError):
        parse(text)


def test_valid_new_file_plans_creation():
    p = plan(new_file())
    assert p.problems == [] and p.site_id == "abc"
    assert p.site == SITE and p.kits == {"KIT-01": KIT}


def test_unknown_section_and_wrong_shapes():
    p = plan({"site": ["no"], "kits": {"KIT-01": {}}, "recipients": "x", "replace_recipients": "yes", "users": []})
    assert fields(p) == {"site": "TYPE", "kits": "TYPE", "recipients": "TYPE", "replace_recipients": "TYPE",
                         "users": "UNKNOWN_KEY"}


def test_first_import_needs_a_site_and_a_site_id():
    assert fields(plan({"kits": [{"kit_id": "KIT-01", **KIT}]}))["site"] == "REQUIRED"
    assert fields(plan({"site": SITE}))["site.site_id"] == "REQUIRED"
    assert fields(plan({"site": {"site_id": "ABC College", **SITE}}))["site.site_id"] == "RULE_VIOLATION"


def test_dd132_other_installations_site_id_is_refused():
    p = plan(new_file(), existing(), site_id="demo")
    assert fields(p) == {"site.site_id": "SITE_ID_IMMUTABLE"}


def test_site_section_may_leave_out_the_site_id_when_the_site_exists():
    p = plan({"site": SITE}, existing(), site_id="abc")
    assert p.problems == [] and p.site_status == "unchanged"


def test_unchanged_scopes_are_not_saved_or_validated():
    p = plan(new_file(), existing(), site_id="abc")
    assert p.site_status == "unchanged" and p.kit_status == {"KIT-01": "unchanged"}


def test_changed_value_type_counts_as_a_change():
    """true and 1 are equal in Python but not as stored JSON."""
    snap = ConfigSnapshot(CATALOGUE, site=ScopeValues(SITE, 1, 1),
                          kits={"KIT-01": ScopeValues({**KIT, "kit_enabled": True}, 2, 1)})
    p = plan({"kits": [{"kit_id": "KIT-01", **KIT, "kit_enabled": 1}]}, snap, site_id="abc")
    assert p.kit_status == {"KIT-01": "updated"}
    assert fields(p) == {"kits.KIT-01.kit_enabled": "TYPE"}


def test_kit_problems_are_located_by_kit_id():
    data = new_file()
    data["kits"].append({"kit_id": "KIT-02", "kit_zone": "Sports Ground", "lat": 13.079, "lon": 80.269,
                         "exposure": "open_ground", "wind_orange_kmh": 70, "timezone": "UTC"})
    data["kits"].append({"kit_zone": "Nowhere"})
    data["kits"].append({"kit_id": "KIT-01", **KIT})
    assert fields(plan(data)) == {"kits.KIT-02.wind_orange_kmh": "THRESHOLD_ORDER",
                                  "kits.KIT-02.timezone": "OVERRIDE_NOT_ALLOWED",
                                  "kits[2].kit_id": "REQUIRED",
                                  "kits.KIT-01.kit_id": "DUPLICATE_KIT_ID"}


def test_kit_outside_the_site_area():
    data = new_file()
    data["kits"][0]["lat"] = 13.2
    assert fields(plan(data)) == {"kits.KIT-01.lat": "KIT_OUTSIDE_SITE"}


def test_site_value_that_breaks_a_stored_kit_points_at_the_site():
    snap = ConfigSnapshot(CATALOGUE, site=ScopeValues(SITE, 1, 1),
                          kits={"KIT-02": ScopeValues({**KIT, "kit_zone": "Sports", "wind_orange_kmh": 45}, 2, 1)})
    p = plan({"site": {**SITE, "wind_yellow_kmh": 46}}, snap, site_id="abc")
    assert fields(p) == {"site.wind_yellow_kmh": "THRESHOLD_ORDER"}
    assert "KIT-02" in p.problems[0].message


def test_recipient_defaults():
    p = plan(new_file(recipients=[{"email": "all@abc.example", "label": " Site list "}]))
    assert p.problems == []
    assert p.recipients == [Recipient("all@abc.example", "Site list", "yellow",
                                      frozenset({"heatwave", "heavy_rain", "high_wind"}), frozenset(), True)]


def test_recipient_problems():
    p = plan(new_file(recipients=[
        {"email": "not-an-address", "label": "", "min_level": "amber", "hazards": [], "zones": "KIT-01"},
        {"email": "a@abc.example", "label": "A", "hazards": ["flood"], "zones": ["KIT-09"], "active": "yes",
         "phone": "123"},
        {"label": "no email"},
        {"email": "A@ABC.example", "label": "same address"},
    ]))
    assert fields(p) == {
        "recipients[0].email": "OUT_OF_RANGE", "recipients[0].label": "OUT_OF_RANGE",
        "recipients[0].min_level": "OUT_OF_RANGE", "recipients[0].hazards": "OUT_OF_RANGE",
        "recipients[0].zones": "TYPE",
        "recipients[1].phone": "UNKNOWN_KEY", "recipients[1].hazards": "OUT_OF_RANGE",
        "recipients[1].zones": "RULE_VIOLATION", "recipients[1].active": "TYPE",
        "recipients[2].email": "REQUIRED",
        "recipients[3].email": "RULE_VIOLATION",
    }
    assert p.recipients == []


def test_recipient_zone_may_name_a_stored_kit():
    p = plan({"recipients": [{"email": "s@abc.example", "label": "S", "zones": ["KIT-01"]}]}, existing(), "abc")
    assert p.problems == []


def test_dd132_recipient_matching_and_replace():
    old_id, other_id = uuid.uuid4(), uuid.uuid4()
    stored = {"all@abc.example": (old_id, Recipient("All@abc.example", "Site list")),
              "old@abc.example": (other_id, Recipient("old@abc.example", "Old list")),
              "gone@abc.example": (uuid.uuid4(), Recipient("gone@abc.example", "Gone", active=False))}
    keep = {"recipients": [{"email": "all@abc.example", "label": "Site list"},
                           {"email": "new@abc.example", "label": "New"}]}
    p = plan(keep, existing(), "abc", stored)
    assert p.recipient_status == {"all@abc.example": "unchanged", "new@abc.example": "created"}
    p = plan({**keep, "replace_recipients": True}, existing(), "abc", stored)
    assert p.recipient_status["old@abc.example"] == "deactivated"
    assert "gone@abc.example" not in p.recipient_status  # already inactive
    p = plan({"recipients": [{"email": "all@abc.example", "label": "Site list", "min_level": "orange"}]},
             existing(), "abc", stored)
    assert p.recipient_status == {"all@abc.example": "updated"}


def test_uuid7_layout_and_order():
    a, b = uuid7(1_700_000_000_000), uuid7(1_700_000_000_001)
    assert a.version == 7 and a.variant == uuid.RFC_4122
    assert a.int >> 80 == 1_700_000_000_000
    assert a < b
