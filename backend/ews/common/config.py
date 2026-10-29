"""Settings catalogue (design/04 §4.3, §4.7) and its sync into the database (DD110).

    python -m ews.common.config sync      # start.ps1 runs this after `alembic upgrade head`

`config/defaults.yaml` is the source; `config_key` and `config_key_region_default` mirror it so the API can
serve the schema and foreign keys reject unknown keys. A key removed from the file is marked `deprecated`,
never deleted (old config versions reference it). The resolver (04 §4.2) is added here in M3.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg
import yaml

from ews.common.settings import REPO_ROOT

DEFAULTS_FILE = REPO_ROOT / "config" / "defaults.yaml"

VALUE_TYPES = ("number", "integer", "string", "boolean", "integer_list")
LEVELS = ("default", "site", "kit")
REGIONS = ("plains", "coastal", "hilly")
_FIELDS = {"type", "levels", "default", "region_defaults", "computed_from", "required", "unit", "rules", "description"}
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


class CatalogueError(ValueError):
    """defaults.yaml is malformed; the message names the key."""


@dataclass(frozen=True)
class KeyMeta:
    key: str
    value_type: str
    levels: tuple[str, ...]
    description: str
    default: Any = None
    region_defaults: dict[str, Any] = field(default_factory=dict)
    computed_from: str | None = None
    required: tuple[str, ...] = ()
    unit: str | None = None
    rules: dict[str, Any] = field(default_factory=dict)

    @property
    def site_allowed(self) -> bool:
        return "site" in self.levels

    @property
    def kit_allowed(self) -> bool:
        return "kit" in self.levels


def check_type(value_type: str, value: Any) -> None:
    ok = {
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer_list": isinstance(value, list) and all(isinstance(v, int) and not isinstance(v, bool) for v in value),
    }.get(value_type)
    if ok is None:
        raise CatalogueError(f"unknown type {value_type!r}")
    if not ok:
        raise CatalogueError(f"{value!r} is not a valid {value_type}")


def parse_catalogue(data: dict[str, Any]) -> dict[str, KeyMeta]:
    if not isinstance(data, dict) or not data:
        raise CatalogueError("defaults.yaml must be a mapping of keys")
    out: dict[str, KeyMeta] = {}
    for key, spec in data.items():
        where = f"defaults.yaml: {key}"
        if not isinstance(key, str) or not _KEY.match(key):
            raise CatalogueError(f"{where}: keys are snake_case")
        if not isinstance(spec, dict):
            raise CatalogueError(f"{where}: must be a mapping")
        unknown = set(spec) - _FIELDS
        if unknown:
            raise CatalogueError(f"{where}: unknown field(s) {', '.join(sorted(unknown))}")
        if not spec.get("description"):
            raise CatalogueError(f"{where}: description missing")
        value_type = spec.get("type")
        if value_type not in VALUE_TYPES:
            raise CatalogueError(f"{where}: type must be one of {', '.join(VALUE_TYPES)}")
        levels = tuple(spec.get("levels") or ())
        if not levels or not set(levels) <= set(LEVELS):
            raise CatalogueError(f"{where}: levels must be a list of {', '.join(LEVELS)}")
        required = tuple(spec.get("required") or ())
        if not set(required) <= {"site", "kit"} or not set(required) <= set(levels):
            raise CatalogueError(f"{where}: required levels must be site/kit and allowed in levels")
        region_defaults = spec.get("region_defaults") or {}
        if region_defaults and set(region_defaults) != set(REGIONS):
            raise CatalogueError(f"{where}: region_defaults need exactly {', '.join(REGIONS)}")
        default = spec.get("default")
        if region_defaults and default is not None:
            raise CatalogueError(f"{where}: either default or region_defaults, not both")
        if (default is not None or region_defaults) and "default" not in levels:
            raise CatalogueError(f"{where}: has a default but 'default' is not in levels")
        try:
            for value in ([default] if default is not None else []) + list(region_defaults.values()):
                check_type(value_type, value)
        except CatalogueError as e:
            raise CatalogueError(f"{where}: {e}") from None
        rules = dict(spec.get("rules") or {})
        out[key] = KeyMeta(key=key, value_type=value_type, levels=levels, description=str(spec["description"]),
                           default=default, region_defaults=dict(region_defaults),
                           computed_from=spec.get("computed_from"), required=required,
                           unit=spec.get("unit"), rules=rules)
    return out


def load_catalogue(path: Path | str = DEFAULTS_FILE) -> dict[str, KeyMeta]:
    return parse_catalogue(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


# --- sync into the database (DD110) ------------------------------------------------------------

@dataclass
class SyncResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    deprecated: int = 0
    undeprecated: int = 0

    def __str__(self) -> str:
        return (f"{self.inserted} inserted, {self.updated} updated, {self.unchanged} unchanged, "
                f"{self.deprecated} deprecated, {self.undeprecated} restored")


def _row(meta: KeyMeta) -> dict[str, Any]:
    rules = dict(meta.rules)
    if len(meta.required) > 1:
        rules["required"] = list(meta.required)  # required_at holds one level; the full list is kept here
    return {
        "value_type": meta.value_type,
        "default_value": None if meta.default is None else json.dumps(meta.default),
        "computed_from": meta.computed_from,
        "site_allowed": meta.site_allowed,
        "kit_allowed": meta.kit_allowed,
        "required_at": meta.required[0] if meta.required else None,
        "unit": meta.unit,
        "rules": json.dumps(rules, sort_keys=True),
        "description": meta.description,
    }


async def sync(conn: asyncpg.Connection, path: Path | str = DEFAULTS_FILE) -> SyncResult:
    """Make config_key / config_key_region_default match defaults.yaml, in one transaction."""
    catalogue = load_catalogue(path)
    result = SyncResult()
    async with conn.transaction():
        existing = {r["key"]: r for r in await conn.fetch(
            "SELECT key, deprecated, value_type, default_value::text AS default_value, computed_from, site_allowed, "
            "kit_allowed, required_at::text AS required_at, unit, rules::text AS rules, description FROM config_key")}
        regions = {(r["key"], r["region_type"]): r["value"] for r in await conn.fetch(
            "SELECT key, region_type, value::text AS value FROM config_key_region_default")}

        for key, meta in catalogue.items():
            row = _row(meta)
            old = existing.get(key)
            have = {r: json.loads(v) for (k, r), v in regions.items() if k == key}
            region_changed = have != meta.region_defaults
            if old is None:
                await conn.execute(
                    "INSERT INTO config_key (key, value_type, default_value, computed_from, site_allowed, kit_allowed, "
                    "required_at, unit, rules, description) "
                    "VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7::config_scope, $8, $9::jsonb, $10)",
                    key, *row.values())
                result.inserted += 1
            elif region_changed or not all(_same(k, old[k], v) for k, v in row.items()):
                await conn.execute(
                    "UPDATE config_key SET value_type = $2, default_value = $3::jsonb, computed_from = $4, "
                    "site_allowed = $5, kit_allowed = $6, required_at = $7::config_scope, unit = $8, "
                    "rules = $9::jsonb, description = $10, deprecated = false WHERE key = $1",
                    key, *row.values())
                result.updated += 1
            elif old["deprecated"]:
                await conn.execute("UPDATE config_key SET deprecated = false WHERE key = $1", key)
                result.undeprecated += 1
            else:
                result.unchanged += 1

            if region_changed:
                await conn.execute("DELETE FROM config_key_region_default WHERE key = $1", key)
                for region, value in meta.region_defaults.items():
                    await conn.execute("INSERT INTO config_key_region_default (key, region_type, value) "
                                       "VALUES ($1, $2, $3::jsonb)", key, region, json.dumps(value))

        for key, old in existing.items():
            if key not in catalogue and not old["deprecated"]:
                await conn.execute("UPDATE config_key SET deprecated = true WHERE key = $1", key)
                result.deprecated += 1
    return result


def _same(column: str, stored: Any, wanted: Any) -> bool:
    if column in ("default_value", "rules"):
        return (None if stored is None else json.loads(stored)) == (None if wanted is None else json.loads(wanted))
    return stored == wanted


async def _sync_command(database_url: str | None, path: Path) -> SyncResult:
    from ews.common.settings import load_settings

    dsn = database_url or load_settings().active_database_url
    conn = await asyncpg.connect(dsn)
    try:
        return await sync(conn, path)
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ews.common.config")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sync", help="load config/defaults.yaml into config_key (DD110)")
    s.add_argument("--file", type=Path, default=DEFAULTS_FILE)
    s.add_argument("--database-url", help="default: the active database from .env")
    sub.add_parser("check", help="validate config/defaults.yaml only")
    args = ap.parse_args(argv)
    try:
        if args.command == "check":
            print(f"{len(load_catalogue())} keys OK")
            return 0
        result = asyncio.run(_sync_command(args.database_url, args.file))
    except CatalogueError as e:
        print(f"defaults.yaml is invalid: {e}", file=sys.stderr)
        return 2
    print(f"config sync: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
