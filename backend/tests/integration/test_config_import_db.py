"""YAML import against the database: all or nothing, versions only for changed scopes, recipients,
dry run, config.changed and the command line used by start.ps1 -Seed (design/04 §4.6, DD41, DD132)."""
import asyncio
from datetime import datetime, timezone

import asyncpg
import pytest

from ews.common import config, config_import, events, migrations
from ews.common.settings import REPO_ROOT

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
EXAMPLE = (REPO_ROOT / "config" / "example-site.yaml").read_text(encoding="utf-8")
DEMO = (REPO_ROOT / "config" / "demo-site.yaml").read_text(encoding="utf-8")


@pytest.fixture
async def db(schema):
    dsn, name = schema
    migrations.upgrade(dsn, schema=name)
    conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{name},public"})
    await config.sync(conn)
    yield dsn, name, conn
    await conn.close()


async def counts(conn) -> dict[str, int]:
    tables = ("site", "kit", "config_version", "config_value", "recipient", "recipient_hazard", "recipient_zone")
    return {t: await conn.fetchval(f"SELECT count(*) FROM {t}") for t in tables}


async def run(conn, text, **kw):
    return await config_import.import_file(conn, text, now=NOW, reason="test import", **kw)


async def test_dd41_valid_file_stores_site_kit_and_recipients(db):
    """M1.3 check: a valid file → site + kit + recipients stored."""
    _, _, conn = db
    result = await run(conn, EXAMPLE)
    assert result.ok and result.site == "created" and result.kits == {"KIT-01": "created"}
    assert await conn.fetchval("SELECT site_id FROM site") == "abc"
    snap = await config.load_snapshot(conn)
    assert snap.site.version == 1 and snap.value("site_name") == "ABC College"
    assert snap.kits["KIT-01"].version == 1
    assert snap.resolve("elevation_m", "KIT-01") == config.Resolved(30, "kit")
    assert snap.resolve("heat_min_tmax_c", "KIT-01") == config.Resolved(37, "default", region_type="coastal")
    assert await conn.fetchval("SELECT count(DISTINCT reason) FROM config_version WHERE reason = 'test import'") == 1
    r = await conn.fetchrow("SELECT id, label, min_level::text AS min_level, active, version FROM recipient")
    assert (r["label"], r["min_level"], r["active"], r["version"]) == ("Site mailing list", "yellow", True, 1)
    assert r["id"].version == 7  # UUIDv7 (DD22)
    assert await conn.fetchval("SELECT count(*) FROM recipient_hazard WHERE recipient_id = $1", r["id"]) == 3


async def test_dd41_one_invalid_kit_stores_nothing(db):
    """M1.3 check: one invalid kit → nothing stored, every problem reported."""
    _, _, conn = db
    before = await counts(conn)
    bad = DEMO.replace("    wind_red_kmh: 45\n", "    wind_red_kmh: 30\n")
    result = await run(conn, bad)
    assert not result.ok
    assert [(p.field, p.code) for p in result.problems] == [("kits.KIT-02.wind_yellow_kmh", "THRESHOLD_ORDER")]
    assert "(28 < 35 < 30)" in result.problems[0].message
    assert await counts(conn) == before


async def test_invalid_kit_on_an_existing_site_changes_nothing(db):
    _, _, conn = db
    assert (await run(conn, DEMO)).ok
    before = await counts(conn)
    bad = DEMO.replace('label: "Sports department"', 'label: "Sports staff"').replace(
        "exposure: under_trees", "exposure: under_a_tree")
    result = await run(conn, bad)
    assert [(p.field, p.code) for p in result.problems] == [("kits.KIT-03.exposure", "OUT_OF_RANGE")]
    assert await counts(conn) == before
    assert await conn.fetchval("SELECT label FROM recipient WHERE email = 'sports@demo-site.example'") == \
        "Sports department"


async def test_dry_run_stores_nothing(db):
    _, _, conn = db
    before = await counts(conn)
    result = await run(conn, DEMO, dry_run=True)
    assert result.ok and result.dry_run and result.kits == {"KIT-01": "created", "KIT-02": "created",
                                                             "KIT-03": "created"}
    assert await counts(conn) == before


async def test_reimport_touches_only_changed_scopes(db):
    _, _, conn = db
    await run(conn, DEMO)
    again = await run(conn, DEMO)
    assert again.ok and not again.changed and again.site == "unchanged"
    changed = DEMO.replace("wind_red_kmh: 45", "wind_red_kmh: 44").replace(
        'label: "Sports department"', 'label: "Sports staff"')
    result = await run(conn, changed)
    assert result.kits == {"KIT-01": "unchanged", "KIT-02": "updated", "KIT-03": "unchanged"}
    assert result.recipients == {"all@demo-site.example": "unchanged", "sports@demo-site.example": "updated"}
    snap = await config.load_snapshot(conn)
    assert (snap.site.version, snap.kits["KIT-01"].version, snap.kits["KIT-02"].version) == (1, 1, 2)
    assert await conn.fetchval("SELECT version FROM recipient WHERE email = 'sports@demo-site.example'") == 2


async def test_recipient_zones_and_replace(db):
    _, _, conn = db
    await run(conn, DEMO)
    zones = await conn.fetch("SELECT k.kit_id FROM recipient_zone z JOIN kit k USING (kit_no) "
                             "JOIN recipient r ON r.id = z.recipient_id WHERE r.email = 'sports@demo-site.example'")
    assert [z["kit_id"] for z in zones] == ["KIT-02"]
    only_all = ("recipients:\n  - email: ALL@demo-site.example\n    label: Everyone\n"
                "replace_recipients: true\n")
    result = await run(conn, only_all)
    assert result.ok
    assert result.recipients == {"ALL@demo-site.example": "updated", "sports@demo-site.example": "deactivated"}
    rows = {r["email"]: r for r in await conn.fetch("SELECT email::text, label, active FROM recipient")}
    assert rows["sports@demo-site.example"]["active"] is False
    assert rows["ALL@demo-site.example"]["label"] == "Everyone"
    assert await conn.fetchval("SELECT count(*) FROM recipient") == 2  # never deleted


async def test_dd132_file_of_another_site_is_refused(db):
    _, _, conn = db
    await run(conn, EXAMPLE)
    before = await counts(conn)
    result = await run(conn, DEMO)
    assert ("site.site_id", "SITE_ID_IMMUTABLE") in {(p.field, p.code) for p in result.problems}
    assert await counts(conn) == before


async def test_import_sends_config_changed(db):
    dsn, name, conn = db
    async with events.listen(dsn, types={"config.changed"}) as inbox:
        await run(conn, EXAMPLE)
        event = await asyncio.wait_for(inbox.get(), 5)
    assert event.payload == {"source": "import", "site": True, "kits": ["KIT-01"], "recipients": True}


async def test_cli_seed_imports_only_when_no_site_exists(db, tmp_path, capsys):
    dsn, name, conn = db
    url = f"{dsn}{'&' if '?' in dsn else '?'}options=-csearch_path%3D{name},public"
    file = tmp_path / "site.yaml"
    file.write_text(EXAMPLE, encoding="utf-8")
    args = [str(file), "--if-no-site", "--database-url", url]
    assert await asyncio.to_thread(config_import.main, ["--dry-run", *args]) == 0
    assert await conn.fetchval("SELECT count(*) FROM site") == 0
    assert await asyncio.to_thread(config_import.main, args) == 0
    assert await conn.fetchval("SELECT site_id FROM site") == "abc"
    assert await asyncio.to_thread(config_import.main, args) == 0
    assert "already exists" in capsys.readouterr().out
    file.write_text(EXAMPLE.replace("site_id: abc", "site_id: demo"), encoding="utf-8")
    assert await asyncio.to_thread(config_import.main, [str(file), "--database-url", url]) == 1
    file.write_text("site: [", encoding="utf-8")
    assert await asyncio.to_thread(config_import.main, [str(file), "--database-url", url]) == 2
