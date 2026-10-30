"""Configuration validator (design/04 §4.4, CFG-02, CFG-03): one function for UI saves, API and YAML import.

    problems = validate(snapshot, site={...}, kits={"KIT-02": {...}})

`site` and each kit are the **full** set of values for that level in the new version (03 §3.5.2).
Every problem is reported together. Cross-key rules and the site area are checked on the effective
values of every affected kit, so a site save that is fine on its own but breaks a kit is rejected.
"""
from __future__ import annotations

import math
import operator
import re
from dataclasses import dataclass, replace
from typing import Any, Collection, Mapping
from zoneinfo import ZoneInfo

from ews.common.config import ConfigSnapshot, KeyMeta, ScopeValues, check_type, CatalogueError

KIT_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
EARTH_RADIUS_KM = 6371.0088
COORDINATES = ("lat", "lon")

# Order groups of 04 §4.4 step 7: keys from smallest to largest and the comparison between neighbours.
# The `order` tag of each key in defaults.yaml must name one of these groups (checked by the tests).
ORDER_GROUPS: dict[str, tuple[tuple[str, ...], tuple[str, ...], str]] = {
    "wind_levels": (("wind_yellow_kmh", "wind_orange_kmh", "wind_red_kmh"), ("<", "<"), "Yellow < Orange < Red"),
    "rain_levels": (("rain_yellow_24h_mm", "rain_orange_24h_mm", "rain_red_24h_mm"), ("<", "<"),
                    "Yellow < Orange < Red"),
    "heat_departure": (("heat_departure_c", "heat_severe_departure_c"), ("<",), "heatwave < severe departure"),
    "heat_absolute": (("heat_absolute_c", "heat_severe_absolute_c"), ("<",), "heatwave < severe absolute"),
    "heat_index": (("heat_index_caution_c", "heat_index_danger_c"), ("<",), "caution < danger"),
    "probabilities": (("alert_watch_off_prob", "alert_watch_on_prob", "alert_warning_off_prob",
                       "alert_warning_on_prob"), ("<", "<=", "<"), "watch off < watch on ≤ warning off < warning on"),
    "qc_temp": (("qc_temp_min_c", "qc_temp_max_c"), ("<",), "min < max"),
    "qc_rh": (("qc_rh_min_pct", "qc_rh_max_pct"), ("<",), "min < max"),
    "qc_pressure": (("qc_pressure_min_hpa", "qc_pressure_max_hpa"), ("<",), "min < max"),
    "normals_years": (("normals_start_year", "normals_end_year"), ("<",), "start < end"),
}
_OPS = {"<": operator.lt, "<=": operator.le}


@dataclass(frozen=True)
class Problem:
    code: str                  # field-level code of design/02 §2.3.1
    key: str                   # config key, or "kit_id"
    message: str
    kit_id: str | None = None  # the kit the problem is about (None = the site)
    path: str | None = None    # where in an imported file, e.g. "kits.KIT-02.wind_orange_kmh" (DD132)

    @property
    def field(self) -> str:
        if self.path is not None:
            return self.path
        return "kit_id" if self.key == "kit_id" else f"values.{self.key}"

    def as_error(self) -> dict[str, str]:
        """One entry of `errors[]` in a VALIDATION_FAILED response (02 §2.3)."""
        return {"field": self.field, "code": self.code, "message": self.message}


def validate(snapshot: ConfigSnapshot, *, site: Mapping[str, Any] | None = None,
             kits: Mapping[str, Mapping[str, Any]] | None = None,
             new_kits: Collection[str] = ()) -> list[Problem]:
    """Problems of saving `site` and/or `kits` (kit_id → values) on top of `snapshot`; [] means valid.

    `new_kits` are kit IDs being created, which must not exist yet (DUPLICATE_KIT_ID).
    """
    kits = dict(kits or {})
    problems: list[Problem] = []
    bad: dict[str | None, set[str]] = {}    # scope → keys with a problem in steps 1–3

    if site is not None:
        problems += _check_scope(snapshot.catalogue, "site", None, site, bad.setdefault(None, set()))
    for kit_id, values in kits.items():
        if not KIT_ID.match(kit_id):
            problems.append(Problem("RULE_VIOLATION", "kit_id",
                                    f"kit_id {kit_id!r} must be 1–32 letters, digits, '-' or '_'", kit_id))
        if kit_id in new_kits and kit_id in snapshot.kits:
            problems.append(Problem("DUPLICATE_KIT_ID", "kit_id", f"{kit_id} already exists", kit_id))
        problems += _check_scope(snapshot.catalogue, "kit", kit_id, values, bad.setdefault(kit_id, set()))

    # Candidate configuration: the new versions with the invalid values left out
    candidate = replace(
        snapshot,
        site=_without(snapshot.site, site, bad.get(None)) if site is not None else snapshot.site,
        kits={**snapshot.kits, **{k: _without(snapshot.kits.get(k), v, bad[k]) for k, v in kits.items()}})
    affected = list(candidate.kits) if site is not None else list(kits)
    affected = [k for k in affected if k in kits or candidate.value("kit_enabled", k)]
    skip = set().union(*bad.values()) if bad else set()

    problems += _check_area(candidate, affected)
    problems += _check_zones(candidate, kits)
    problems += _check_cross_keys(candidate, affected, site is not None, kits, skip)
    return problems


# --- steps 1–4: one level on its own ----------------------------------------------------------

def _check_scope(catalogue: Mapping[str, KeyMeta], scope: str, kit_id: str | None,
                 values: Mapping[str, Any], bad: set[str]) -> list[Problem]:
    where = kit_id or "the site"
    out: list[Problem] = []
    for key, value in values.items():
        meta = catalogue.get(key)
        if meta is None:
            out.append(Problem("UNKNOWN_KEY", key, f"{key} is not a configuration key", kit_id))
        elif scope not in meta.levels:
            out.append(Problem("OVERRIDE_NOT_ALLOWED", key, f"{key} cannot be set on {where}", kit_id))
        else:
            problem = _check_value(meta, value, kit_id)
            if problem:
                out.append(problem)
            else:
                continue
        bad.add(key)
    for key, meta in catalogue.items():
        if scope in meta.required and key not in values:
            out.append(Problem("REQUIRED", key, f"{key} is required on {where}", kit_id))
    return out


def _check_value(meta: KeyMeta, value: Any, kit_id: str | None) -> Problem | None:
    key, rules = meta.key, meta.rules
    try:
        check_type(meta.value_type, value)
    except CatalogueError:
        return Problem("TYPE", key, f"{key} must be a {meta.value_type.replace('_', ' ')}, not {value!r}", kit_id)
    # lat/lon ranges are step 5 (INVALID_COORDINATES)
    code = "INVALID_COORDINATES" if key in COORDINATES else "OUT_OF_RANGE"
    if "min" in rules and value < rules["min"] or "max" in rules and value > rules["max"]:
        return Problem(code, key, f"{key} must be between {rules.get('min', '-∞')} and {rules.get('max', '∞')}, "
                                  f"not {value}", kit_id)
    if "allowed" in rules and value not in rules["allowed"]:
        allowed = ", ".join(str(a) for a in rules["allowed"])
        return Problem("OUT_OF_RANGE", key, f"{key} must be one of {allowed}, not {value!r}", kit_id)
    if meta.value_type == "string":
        if not rules.get("min_length", 0) <= len(value) <= rules.get("max_length", math.inf):
            return Problem("OUT_OF_RANGE", key, f"{key} must be {rules.get('min_length', 0)}–"
                                                f"{rules.get('max_length')} characters", kit_id)
    if rules.get("odd") and value % 2 == 0:
        return Problem("OUT_OF_RANGE", key, f"{key} must be odd, not {value}", kit_id)
    if rules.get("iana_timezone") and not _is_timezone(value):
        return Problem("OUT_OF_RANGE", key, f"{value!r} is not an IANA time zone name", kit_id)
    return None


def _is_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ValueError, KeyError, OSError):  # ZoneInfoNotFoundError is a KeyError
        return False
    return True


def _without(old: ScopeValues | None, values: Mapping[str, Any], bad: set[str] | None) -> ScopeValues:
    kept = {k: v for k, v in values.items() if k not in (bad or ())}
    return ScopeValues(kept, *((old.version_id, old.version) if old else (None, None)))


# --- steps 5–7: across levels and kits ---------------------------------------------------------

def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _check_area(snap: ConfigSnapshot, kits: list[str]) -> list[Problem]:
    """Step 5: every affected kit within site_radius_km of the site centre (CFG-03)."""
    centre = [snap.value(k) for k in COORDINATES]
    radius = snap.value("site_radius_km")
    if None in centre or radius is None:
        return []  # the site itself is incomplete: already a REQUIRED or coordinate problem
    out = []
    for kit_id in kits:
        own = snap.kits[kit_id].values
        if not all(k in own for k in COORDINATES):
            continue  # REQUIRED already reported
        distance = great_circle_km(*centre, own["lat"], own["lon"])
        if distance > radius:
            out.append(Problem("KIT_OUTSIDE_SITE", "lat", f"{kit_id} is {distance:.2f} km from the site centre; "
                                                          f"the site radius is {radius} km", kit_id))
    return out


def _check_zones(snap: ConfigSnapshot, saved: Mapping[str, Any]) -> list[Problem]:
    """Step 6: kit_zone unique among enabled kits."""
    zones: dict[str, list[str]] = {}
    for kit_id in snap.kits:
        zone = snap.kits[kit_id].values.get("kit_zone")
        if zone is not None and snap.value("kit_enabled", kit_id):
            zones.setdefault(zone.strip().casefold(), []).append(kit_id)
    out = []
    for kit_id in saved:
        zone = snap.kits[kit_id].values.get("kit_zone")
        others = [k for k in zones.get(zone.strip().casefold(), []) if k != kit_id] if zone else []
        if others and snap.value("kit_enabled", kit_id):
            out.append(Problem("DUPLICATE_ZONE", "kit_zone", f"zone {zone!r} is already used by {', '.join(others)}",
                               kit_id))
    return out


def _check_cross_keys(snap: ConfigSnapshot, kits: list[str], site_saved: bool, saved_kits: Collection[str],
                      skip: set[str]) -> list[Problem]:
    """Step 7 on the effective values of the site and every affected kit."""
    out: list[Problem] = []
    scopes: list[str | None] = ([None] if site_saved else []) + kits
    for kit_id in scopes:
        for group, (keys, ops, label) in ORDER_GROUPS.items():
            if skip & set(keys):
                continue
            values = [snap.value(k, kit_id) for k in keys]
            if kit_id is not None and site_saved and values == [snap.value(k) for k in keys]:
                continue  # same as the site: reported once for the site
            if None in values or all(_OPS[op](a, b) for op, a, b in zip(ops, values, values[1:])):
                continue
            # point at a key of the level being saved: the kit's own, else the site's
            saved = [snap.kits[kit_id].values] if kit_id in saved_kits else []
            saved += [snap.site.values] if site_saved else []
            key = next((k for values_ in saved for k in keys if k in values_), keys[0])
            shown = " ".join(f"{v} {op}" for v, op in zip(values, ops)) + f" {values[-1]}"
            where = f" on {kit_id}" if kit_id else ""
            out.append(Problem("THRESHOLD_ORDER", key, f"{label} is required{where} ({shown})", kit_id))
        out += _check_rules(snap, kit_id, site_saved, skip)
    return out


def _check_rules(snap: ConfigSnapshot, kit_id: str | None, site_saved: bool, skip: set[str]) -> list[Problem]:
    """Step 7, the other cross-key rules (RULE_VIOLATION)."""
    out = []
    where = f" on {kit_id}" if kit_id else ""
    for key, meta in snap.catalogue.items():
        rule, factor = ((meta.rules["at_least_twice"], 2) if "at_least_twice" in meta.rules
                        else (meta.rules.get("at_least"), 1))
        if rule is None or {key, rule} & skip:
            continue
        value, limit = snap.value(key, kit_id), snap.value(rule, kit_id)
        if kit_id is not None and site_saved and (value, limit) == (snap.value(key), snap.value(rule)):
            continue  # same as the site: reported once for the site
        if value is not None and limit is not None and value < factor * limit:
            times = "2 × " if factor == 2 else ""
            out.append(Problem("RULE_VIOLATION", key, f"{key} ({value}) must be at least {times}{rule} "
                                                      f"({limit}){where}", kit_id))
    start_key, end_key = ORDER_GROUPS["normals_years"][0]
    span = snap.catalogue[end_key].rules.get("min_span_years")
    if kit_id is None and span and not {start_key, end_key} & skip:
        start, end = snap.value(start_key), snap.value(end_key)
        if start < end and end - start < span:  # start ≥ end is already THRESHOLD_ORDER
            out.append(Problem("RULE_VIOLATION", end_key, f"the normals period {start}–{end} must cover at least "
                                                          f"{span + 1} years"))
    return out
