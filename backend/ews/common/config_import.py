"""YAML import of site, kits and recipients (design/04 §4.6, DD41, DD132).

    python -m ews.common.config_import config/example-site.yaml [--dry-run] [--if-no-site]

    result = await import_file(conn, text, now=clock.now(), reason="…")
    result.problems      # [] → stored in one transaction (or, on a dry run, would be)

The whole file is checked first, with the same validator as UI saves (04 §4.4); one problem anywhere
stores nothing. Only scopes that differ from their current version get a new version.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

import asyncpg
import yaml

from ews.common import events
from ews.common.config import ConfigSnapshot, KeyMeta, load_snapshot, save_version
from ews.common.config_validation import Problem, validate
from ews.common.ids import uuid7
from ews.common.logging import get_logger

SECTIONS = ("site", "kits", "recipients", "replace_recipients")
RECIPIENT_FIELDS = ("email", "label", "min_level", "hazards", "zones", "active")
HAZARDS = ("heatwave", "heavy_rain", "high_wind")
ALERT_LEVELS = ("yellow", "orange", "red")
SITE_ID = re.compile(r"^[a-z0-9-]{2,32}$")   # the CHECK on site.site_id (03 §3.5.1)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LABEL_MAX = 100

log = get_logger(__name__)


class ImportFileError(ValueError):
    """The file is not YAML or not a mapping: rejected as a whole (API `400 BAD_REQUEST`)."""


@dataclass(frozen=True)
class Recipient:
    email: str
    label: str
    min_level: str = "yellow"
    hazards: frozenset[str] = frozenset(HAZARDS)
    zones: frozenset[str] = frozenset()      # kit IDs; empty = all zones
    active: bool = True


@dataclass
class ImportResult:
    dry_run: bool
    problems: list[Problem] = field(default_factory=list)
    site: str | None = None                                   # created / updated / unchanged; None = not in file
    kits: dict[str, str] = field(default_factory=dict)        # kit_id → created / updated / unchanged
    recipients: dict[str, str] = field(default_factory=dict)  # email → created / updated / unchanged / deactivated

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def changed(self) -> bool:
        statuses = [self.site, *self.kits.values(), *self.recipients.values()]
        return any(s not in (None, "unchanged") for s in statuses)

    def summary(self) -> str:
        def count(statuses: Any) -> str:
            return ", ".join(f"{n} {s}" for s, n in Counter(statuses).items()) or "none"
        return f"site {self.site or 'not in file'}; kits: {count(self.kits.values())}; " \
               f"recipients: {count(self.recipients.values())}"


def parse(text: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ImportFileError(f"not valid YAML: {e}") from None
    if not isinstance(data, dict):
        raise ImportFileError("the file must be a mapping with site, kits and recipients")
    return data


async def import_file(conn: asyncpg.Connection, text: str, *, now: datetime, reason: str | None = None,
                      created_by: UUID | None = None, dry_run: bool = False,
                      catalogue: Mapping[str, KeyMeta] | None = None) -> ImportResult:
    """Import a site file; all or nothing. Raises ImportFileError for an unreadable file."""
    data = parse(text)
    async with conn.transaction():
        snapshot = await load_snapshot(conn, catalogue)
        stored_site_id = await conn.fetchval("SELECT site_id FROM site")
        plan = ImportPlan(data, snapshot, stored_site_id, await _load_recipients(conn))
        result = ImportResult(dry_run, plan.problems, plan.site_status, plan.kit_status, plan.recipient_status)
        if result.problems or dry_run or not result.changed:
            log.info("config.imported", dry_run=dry_run, problems=len(result.problems), summary=result.summary())
            return result
        await _apply(conn, plan, snapshot, now=now, reason=reason, created_by=created_by)
    log.info("config.imported", dry_run=False, problems=0, summary=result.summary())
    return result


# --- checking the file ------------------------------------------------------------------------

class ImportPlan:
    """Everything the file asks for, its problems, and what would change."""

    def __init__(self, data: Mapping[str, Any], snapshot: ConfigSnapshot, stored_site_id: str | None,
                 existing: Mapping[str, tuple[UUID, Recipient]]):
        self.problems: list[Problem] = []
        self.site_id = stored_site_id
        self.site: dict[str, Any] | None = None
        self.kits: dict[str, dict[str, Any]] = {}
        self.recipients: list[Recipient] = []
        self.site_status: str | None = None
        self.kit_status: dict[str, str] = {}
        self.recipient_status: dict[str, str] = {}
        self.existing = existing

        for name in data:
            if name not in SECTIONS:
                self._problem("UNKNOWN_KEY", str(name), f"{name} is not a section of a site file "
                                                        f"({', '.join(SECTIONS)})")
        self._read_site(data.get("site"), stored_site_id)
        self._read_kits(data.get("kits"))
        self._read_recipients(data.get("recipients"), snapshot)
        replace_all = data.get("replace_recipients", False)
        if not isinstance(replace_all, bool):
            self._problem("TYPE", "replace_recipients", "replace_recipients must be true or false")
            replace_all = False

        # what changes (04 §4.6: unchanged scopes are not touched)
        if self.site is not None:
            if stored_site_id is None:
                self.site_status = "created"
            else:
                self.site_status = "unchanged" if _same(self.site, snapshot.site.values) else "updated"
        for kit_id, values in self.kits.items():
            if kit_id not in snapshot.kits:
                self.kit_status[kit_id] = "created"
            else:
                self.kit_status[kit_id] = "unchanged" if _same(values, snapshot.kits[kit_id].values) else "updated"
        listed = set()
        for r in self.recipients:
            key = r.email.casefold()
            listed.add(key)
            old = existing.get(key)
            self.recipient_status[r.email] = ("created" if old is None else
                                              "unchanged" if replace(old[1], email=r.email) == r else "updated")
        if replace_all:
            for key, (_, old) in existing.items():
                if key not in listed and old.active:
                    self.recipient_status[old.email] = "deactivated"

        if stored_site_id is None and self.site is None and "site" not in data:
            self._problem("REQUIRED", "site", "no site exists yet: the file needs a site section")
        changed_kits = {k: v for k, v in self.kits.items() if self.kit_status[k] != "unchanged"}
        site_changed = self.site_status in ("created", "updated")
        for p in validate(snapshot, site=self.site if site_changed else None, kits=changed_kits,
                          new_kits=[k for k, s in self.kit_status.items() if s == "created"]):
            self.problems.append(replace(p, path=self._locate(p, site_changed)))

    def _problem(self, code: str, path: str, message: str, kit_id: str | None = None) -> None:
        self.problems.append(Problem(code, path.rsplit(".", 1)[-1], message, kit_id, path=path))

    def _locate(self, p: Problem, site_changed: bool) -> str:
        """The file path of a validator problem (DD132)."""
        if p.kit_id is None:
            return f"site.{p.key}"
        if p.kit_id not in self.kits and site_changed and self.site is not None and p.key in self.site:
            return f"site.{p.key}"   # a site value that breaks a kit not in the file
        return f"kits.{p.kit_id}.{p.key}"

    def _read_site(self, section: Any, stored_site_id: str | None) -> None:
        if section is None:
            return
        if not isinstance(section, dict):
            self._problem("TYPE", "site", "site must be a mapping of keys")
            return
        values = dict(section)
        site_id = values.pop("site_id", None)
        if stored_site_id is not None:
            if site_id is not None and site_id != stored_site_id:
                self._problem("SITE_ID_IMMUTABLE", "site.site_id", f"this installation's site is {stored_site_id!r}; "
                                                                   f"the file is for {site_id!r}")
        elif site_id is None:
            self._problem("REQUIRED", "site.site_id", "site_id is required to create the site")
        elif not isinstance(site_id, str) or not SITE_ID.match(site_id):
            self._problem("RULE_VIOLATION", "site.site_id",
                          f"site_id {site_id!r} must be 2–32 lower-case letters, digits or '-'")
        else:
            self.site_id = site_id
        self.site = values

    def _read_kits(self, section: Any) -> None:
        if section is None:
            return
        if not isinstance(section, list):
            self._problem("TYPE", "kits", "kits must be a list")
            return
        for n, entry in enumerate(section):
            if not isinstance(entry, dict):
                self._problem("TYPE", f"kits[{n}]", f"kit {n + 1} must be a mapping of keys")
                continue
            values = dict(entry)
            kit_id = values.pop("kit_id", None)
            if kit_id is None:
                self._problem("REQUIRED", f"kits[{n}].kit_id", f"kit {n + 1} has no kit_id")
            elif not isinstance(kit_id, str):
                self._problem("TYPE", f"kits[{n}].kit_id", f"kit_id {kit_id!r} must be a string")
            elif kit_id in self.kits:
                self._problem("DUPLICATE_KIT_ID", f"kits.{kit_id}.kit_id", f"{kit_id} is listed twice", kit_id)
            else:
                self.kits[kit_id] = values

    def _read_recipients(self, section: Any, snapshot: ConfigSnapshot) -> None:
        if section is None:
            return
        if not isinstance(section, list):
            self._problem("TYPE", "recipients", "recipients must be a list")
            return
        known_kits = set(snapshot.kits) | set(self.kits)
        seen: set[str] = set()
        for n, entry in enumerate(section):
            at = f"recipients[{n}]"
            if not isinstance(entry, dict):
                self._problem("TYPE", at, f"recipient {n + 1} must be a mapping")
                continue
            before = len(self.problems)
            for name in entry:
                if name not in RECIPIENT_FIELDS:
                    self._problem("UNKNOWN_KEY", f"{at}.{name}", f"{name} is not a recipient field "
                                                                 f"({', '.join(RECIPIENT_FIELDS)})")
            email, label = entry.get("email"), entry.get("label")
            if email is None:
                self._problem("REQUIRED", f"{at}.email", f"recipient {n + 1} has no email")
            elif not isinstance(email, str) or not EMAIL.match(email):
                self._problem("OUT_OF_RANGE", f"{at}.email", f"{email!r} is not an email address")
            elif email.casefold() in seen:
                self._problem("RULE_VIOLATION", f"{at}.email", f"{email} is listed twice")
            else:
                seen.add(email.casefold())
            if label is None:
                self._problem("REQUIRED", f"{at}.label", f"recipient {n + 1} has no label")
            elif not isinstance(label, str) or not 1 <= len(label.strip()) <= LABEL_MAX:
                self._problem("OUT_OF_RANGE", f"{at}.label", f"label must be 1–{LABEL_MAX} characters")
            min_level = entry.get("min_level", "yellow")
            if min_level not in ALERT_LEVELS:
                self._problem("OUT_OF_RANGE", f"{at}.min_level",
                              f"min_level must be one of {', '.join(ALERT_LEVELS)}, not {min_level!r}")
            hazards = entry.get("hazards", list(HAZARDS))
            if not isinstance(hazards, list) or not hazards or not all(h in HAZARDS for h in hazards):
                self._problem("OUT_OF_RANGE", f"{at}.hazards",
                              f"hazards must be a non-empty list of {', '.join(HAZARDS)}")
            zones = entry.get("zones", [])
            if not isinstance(zones, list) or not all(isinstance(z, str) for z in zones):
                self._problem("TYPE", f"{at}.zones", "zones must be a list of kit IDs")
            else:
                for z in zones:
                    if z not in known_kits:
                        self._problem("RULE_VIOLATION", f"{at}.zones",
                                      f"zone {z} is not a kit in the file or the database")
            active = entry.get("active", True)
            if not isinstance(active, bool):
                self._problem("TYPE", f"{at}.active", "active must be true or false")
            if len(self.problems) == before:
                self.recipients.append(Recipient(email, label.strip(), min_level, frozenset(hazards),
                                                 frozenset(zones), active))


def _same(new: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """Compared as JSON, so `true` and `1` differ (Python says True == 1)."""
    return json.dumps(dict(new), sort_keys=True) == json.dumps(dict(current), sort_keys=True)


# --- storing ----------------------------------------------------------------------------------

async def _load_recipients(conn: asyncpg.Connection) -> dict[str, tuple[UUID, Recipient]]:
    rows = await conn.fetch(
        "SELECT r.id, r.email::text AS email, r.label, r.min_level::text AS min_level, r.active, "
        "ARRAY(SELECT hazard::text FROM recipient_hazard h WHERE h.recipient_id = r.id) AS hazards, "
        "ARRAY(SELECT k.kit_id FROM recipient_zone z JOIN kit k USING (kit_no) WHERE z.recipient_id = r.id) AS zones "
        "FROM recipient r")
    return {r["email"].casefold(): (r["id"], Recipient(r["email"], r["label"], r["min_level"], frozenset(r["hazards"]),
                                                       frozenset(r["zones"]), r["active"])) for r in rows}


async def _apply(conn: asyncpg.Connection, plan: ImportPlan, snapshot: ConfigSnapshot, *, now: datetime,
                 reason: str | None, created_by: UUID | None) -> None:
    if plan.site_status == "created":
        await conn.execute("INSERT INTO site (site_id, created_at) VALUES ($1, $2)", plan.site_id, now)
    for kit_id, status in plan.kit_status.items():
        if status == "created":
            await conn.execute("INSERT INTO kit (kit_id, created_at) VALUES ($1, $2)", kit_id, now)
    if plan.site_status in ("created", "updated"):
        await save_version(conn, scope="site", values=plan.site, base_version=snapshot.site.version or 0,
                           created_at=now, created_by=created_by, reason=reason)
    for kit_id, status in plan.kit_status.items():
        if status != "unchanged":
            current = snapshot.kits.get(kit_id)
            await save_version(conn, scope="kit", kit_id=kit_id, values=plan.kits[kit_id],
                               base_version=(current.version if current else None) or 0,
                               created_at=now, created_by=created_by, reason=reason)

    kit_nos = {r["kit_id"]: r["kit_no"] for r in await conn.fetch("SELECT kit_id, kit_no FROM kit")}
    for r in plan.recipients:
        status = plan.recipient_status[r.email]
        if status == "unchanged":
            continue
        if status == "created":
            recipient_id = uuid7()
            await conn.execute(
                "INSERT INTO recipient (id, email, label, min_level, active, version, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4::alert_level, $5, 1, $6, $6)",
                recipient_id, r.email, r.label, r.min_level, r.active, now)
        else:
            recipient_id = plan.existing[r.email.casefold()][0]
            await conn.execute(
                "UPDATE recipient SET email = $2, label = $3, min_level = $4::alert_level, active = $5, "
                "version = version + 1, updated_at = $6 WHERE id = $1",
                recipient_id, r.email, r.label, r.min_level, r.active, now)
            await conn.execute("DELETE FROM recipient_hazard WHERE recipient_id = $1", recipient_id)
            await conn.execute("DELETE FROM recipient_zone WHERE recipient_id = $1", recipient_id)
        await conn.executemany("INSERT INTO recipient_hazard (recipient_id, hazard) VALUES ($1, $2::hazard)",
                               [(recipient_id, h) for h in sorted(r.hazards)])
        await conn.executemany("INSERT INTO recipient_zone (recipient_id, kit_no) VALUES ($1, $2)",
                               [(recipient_id, kit_nos[z]) for z in sorted(r.zones)])
    for email, status in plan.recipient_status.items():
        if status == "deactivated":
            await conn.execute("UPDATE recipient SET active = false, version = version + 1, updated_at = $2 "
                               "WHERE id = $1", plan.existing[email.casefold()][0], now)

    await events.notify(conn, "config.changed", {
        "source": "import",
        "site": plan.site_status in ("created", "updated"),
        "kits": sorted(k for k, s in plan.kit_status.items() if s != "unchanged"),
        "recipients": any(s != "unchanged" for s in plan.recipient_status.values()),
    })


# --- command line (start.ps1 -Seed) -----------------------------------------------------------

async def _import_command(path: Path, *, dry_run: bool, if_no_site: bool, reason: str | None,
                          database_url: str | None) -> int:
    from ews.common.settings import load_settings

    conn = await asyncpg.connect(database_url or load_settings().active_database_url)
    try:
        if if_no_site:
            site_id = await conn.fetchval("SELECT site_id FROM site")
            if site_id is not None:
                print(f"site {site_id!r} already exists; {path.name} not imported")
                return 0
        result = await import_file(conn, path.read_text(encoding="utf-8"), now=datetime.now(UTC),
                                   reason=reason or f"YAML import of {path.name}", dry_run=dry_run)
    finally:
        await conn.close()
    if result.problems:
        print(f"{path.name}: {len(result.problems)} problem(s), nothing stored:", file=sys.stderr)
        for p in result.problems:
            print(f"  {p.field}: {p.code} - {p.message}", file=sys.stderr)
        return 1
    print(f"{path.name}{' (dry run, nothing stored)' if dry_run else ''}: {result.summary()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ews.common.config_import",
                                 description="Import site, kits and recipients from YAML (design/04 §4.6)")
    ap.add_argument("file", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="validate and show what would change; store nothing")
    ap.add_argument("--if-no-site", action="store_true", help="do nothing when a site already exists (start.ps1 -Seed)")
    ap.add_argument("--reason", help="stored with every new config version")
    ap.add_argument("--database-url", help="default: the active database from .env")
    args = ap.parse_args(argv)
    try:
        return asyncio.run(_import_command(args.file, dry_run=args.dry_run, if_no_site=args.if_no_site,
                                           reason=args.reason, database_url=args.database_url))
    except (ImportFileError, OSError) as e:
        print(f"{args.file}: {e}", file=sys.stderr)
        return 2
    except asyncpg.UndefinedTableError as e:
        print(f"the database is not migrated ({e}): run alembic upgrade head first (start.ps1 does)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
