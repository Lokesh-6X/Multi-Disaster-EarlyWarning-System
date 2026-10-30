"""Settings catalogue (design/04 §4.3, §4.7), its sync into the database (DD110) and the resolver (04 §4.2).

    python -m ews.common.config sync      # start.ps1 runs this after `alembic upgrade head`

`config/defaults.yaml` is the source; `config_key` and `config_key_region_default` mirror it so the API can
serve the schema and foreign keys reject unknown keys. A key removed from the file is marked `deprecated`,
never deleted (old config versions reference it).

The resolver is the only implementation of kit → site → onboarding → region default → default (DD38):

    cache = ConfigCache(pool)
    await cache.load()
    cache.resolve("wind_orange_kmh", "KIT-02")     # Resolved(value=35, source='kit')
    asyncio.create_task(cache.follow(dsn))         # reload on config.changed (01 §1.3.3)
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

import asyncpg
import yaml

from ews.common import events
from ews.common.logging import get_logger
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


# --- resolution (04 §4.2, DD38) ----------------------------------------------------------------

SOURCES = ("kit", "site", "onboarding", "default")
log = get_logger(__name__)


@dataclass(frozen=True)
class Resolved:
    value: Any                       # None only for a key with no default that nobody has set
    source: str                      # one of SOURCES (CFG-06)
    region_type: str | None = None   # set when a region default was used


@dataclass(frozen=True)
class ScopeValues:
    """The values set at one level in its current version."""
    values: Mapping[str, Any] = field(default_factory=dict)
    version_id: int | None = None    # config_version.id, stored with every clean reading (DD123)
    version: int | None = None       # version number within the scope (CFG-04)


@dataclass(frozen=True)
class ConfigSnapshot:
    """Everything needed to resolve any key for the site or any kit; pure, no database."""
    catalogue: Mapping[str, KeyMeta] = field(repr=False)
    site: ScopeValues = field(default_factory=ScopeValues)
    kits: Mapping[str, ScopeValues] = field(default_factory=dict)
    onboarding: Mapping[str, Any] = field(default_factory=dict)   # computed_from name → value (M3.1)

    @property
    def region_type(self) -> str | None:
        return self.site.values.get("region_type")

    def resolve(self, key: str, kit: str | None = None) -> Resolved:
        meta = self.catalogue.get(key)
        if meta is None:
            raise KeyError(f"unknown config key {key!r}")
        if kit is not None:
            if kit not in self.kits:
                raise KeyError(f"unknown kit {kit!r}")
            kit_values = self.kits[kit].values
            if meta.kit_allowed and key in kit_values:
                return Resolved(kit_values[key], "kit")
        if meta.site_allowed and key in self.site.values:
            return Resolved(self.site.values[key], "site")
        if meta.computed_from and meta.computed_from in self.onboarding:
            return Resolved(self.onboarding[meta.computed_from], "onboarding")
        region = self.region_type
        if meta.region_defaults and region in meta.region_defaults:
            return Resolved(meta.region_defaults[region], "default", region_type=region)
        return Resolved(meta.default, "default")

    def value(self, key: str, kit: str | None = None) -> Any:
        return self.resolve(key, kit).value

    def effective(self, kit: str | None = None) -> dict[str, Resolved]:
        """Every key for the site (kit=None) or one kit, as `GET /config/effective` shows it."""
        return {key: self.resolve(key, kit) for key in self.catalogue}


async def load_snapshot(conn: asyncpg.Connection | asyncpg.Pool,
                        catalogue: Mapping[str, KeyMeta] | None = None) -> ConfigSnapshot:
    """Current site and kit versions from the database (03 §3.5.2)."""
    rows = await conn.fetch(
        "SELECT c.scope::text AS scope, k.kit_id, c.id, c.version, v.key, v.value::text AS value "
        "FROM config_current c LEFT JOIN kit k ON k.kit_no = c.kit_no "
        "LEFT JOIN config_value v ON v.version_id = c.id")
    values: dict[str | None, dict[str, Any]] = {r["kit_id"]: {} for r in await conn.fetch("SELECT kit_id FROM kit")}
    versions: dict[str | None, tuple[int, int]] = {}
    for r in rows:
        scope = r["kit_id"] if r["scope"] == "kit" else None
        versions[scope] = (r["id"], r["version"])
        values.setdefault(scope, {})
        if r["key"] is not None:
            values[scope][r["key"]] = json.loads(r["value"])

    def scope_values(scope: str | None) -> ScopeValues:
        version_id, version = versions.get(scope, (None, None))
        return ScopeValues(values.get(scope, {}), version_id, version)

    return ConfigSnapshot(
        catalogue=catalogue if catalogue is not None else load_catalogue(),
        site=scope_values(None),
        kits={kit: scope_values(kit) for kit in values if kit is not None})


class VersionConflict(Exception):
    """The save was based on an outdated version (CFG-04): API `409 CONFIG_VERSION_CONFLICT`."""

    def __init__(self, scope: str, kit_id: str | None, base_version: int, current_version: int | None):
        self.current_version = current_version
        where = kit_id or "site"
        super().__init__(f"{where} config: saved on version {base_version}, current is {current_version}")


async def save_version(conn: asyncpg.Connection, *, scope: str, values: Mapping[str, Any], base_version: int,
                       created_at: Any, kit_id: str | None = None, created_by: Any = None,
                       reason: str | None = None) -> int:
    """Store `values` (validated, the full set for the level) as version base_version + 1; returns its id.

    base_version 0 = the first version of the scope. No locks: if someone else already saved
    base_version + 1, the unique key fails and this raises VersionConflict (03 §3.5.2).
    The kit row must exist. Run inside the caller's transaction when several scopes are saved together.
    """
    kit_no = None
    if scope == "kit":
        kit_no = await conn.fetchval("SELECT kit_no FROM kit WHERE kit_id = $1", kit_id)
        if kit_no is None:
            raise KeyError(f"unknown kit {kit_id!r}")
    current = await conn.fetchval("SELECT max(version) FROM config_version WHERE scope = $1 "
                                  "AND kit_no IS NOT DISTINCT FROM $2", scope, kit_no)
    if (current or 0) != base_version:
        raise VersionConflict(scope, kit_id, base_version, current)
    try:
        async with conn.transaction():  # a savepoint when the caller already has a transaction
            version_id = await conn.fetchval(
                "INSERT INTO config_version (scope, kit_no, version, created_at, created_by, reason) "
                "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
                scope, kit_no, base_version + 1, created_at, created_by, reason)
            await conn.executemany(
                "INSERT INTO config_value (version_id, key, value) VALUES ($1, $2, $3::jsonb)",
                [(version_id, key, json.dumps(value)) for key, value in values.items()])
    except asyncpg.UniqueViolationError:
        current = await conn.fetchval("SELECT max(version) FROM config_version WHERE scope = $1 "
                                      "AND kit_no IS NOT DISTINCT FROM $2", scope, kit_no)
        raise VersionConflict(scope, kit_id, base_version, current) from None
    return version_id


ReloadHook = Callable[[ConfigSnapshot | None, ConfigSnapshot], Awaitable[None] | None]


class ConfigCache:
    """A process's resolved configuration: loaded once, reloaded on `config.changed` (01 §1.3.3).

    Hooks get (old, new) after each reload; `alerts` uses this for `threshold_changed` (AL-16).
    A failed reload keeps the last snapshot (04 §4.4).
    """

    def __init__(self, conn: asyncpg.Pool | asyncpg.Connection, catalogue: Mapping[str, KeyMeta] | None = None):
        self._conn = conn
        self._catalogue = catalogue if catalogue is not None else load_catalogue()
        self._snapshot: ConfigSnapshot | None = None
        self._hooks: list[ReloadHook] = []

    @property
    def snapshot(self) -> ConfigSnapshot:
        if self._snapshot is None:
            raise RuntimeError("configuration not loaded yet: await ConfigCache.load() first")
        return self._snapshot

    def on_reload(self, hook: ReloadHook) -> None:
        self._hooks.append(hook)

    def resolve(self, key: str, kit: str | None = None) -> Resolved:
        return self.snapshot.resolve(key, kit)

    def value(self, key: str, kit: str | None = None) -> Any:
        return self.snapshot.value(key, kit)

    async def load(self) -> ConfigSnapshot:
        old, new = self._snapshot, await load_snapshot(self._conn, self._catalogue)
        self._snapshot = new
        log.info("config.reloaded", site_version=new.site.version, kits=len(new.kits))
        for hook in self._hooks:
            result = hook(old, new)
            if inspect.isawaitable(result):
                await result
        return new

    async def follow(self, dsn: str) -> None:
        """Run forever: reload on every `config.changed`. Cancel the task to stop."""
        async with events.listen(dsn, types={"config.changed"}) as inbox:
            await self._reload_quietly()  # a change between load() and LISTEN is not missed
            while True:
                await inbox.get()
                while not inbox.empty():  # several saves at once → one reload
                    inbox.get_nowait()
                await self._reload_quietly()

    async def _reload_quietly(self) -> None:
        try:
            await self.load()
        except (OSError, asyncpg.PostgresError) as e:
            log.warning("config.reload_failed", error_detail=f"{type(e).__name__}: {e}")


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
