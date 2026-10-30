"""Resolver and versioned saves against the database: current versions, effective view, reload on
config.changed, optimistic locking (design/04 §4.2, design/03 §3.5.2, design/01 §1.3.3, TST-10, CFG-04)."""
import asyncio
import json
from datetime import datetime, timezone

import asyncpg
import pytest

from ews.common import config, events, migrations
from ews.common.db import create_pool

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


async def save(conn, scope, values, version, kit_no=None) -> int:
    version_id = await conn.fetchval(
        "INSERT INTO config_version (scope, kit_no, version, created_at) VALUES ($1, $2, $3, now()) RETURNING id",
        scope, kit_no, version)
    for key, value in values.items():
        await conn.execute("INSERT INTO config_value (version_id, key, value) VALUES ($1, $2, $3::jsonb)",
                           version_id, key, json.dumps(value))
    return version_id


@pytest.fixture
async def db(schema):
    dsn, name = schema
    migrations.upgrade(dsn, schema=name)
    conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{name},public"})
    await config.sync(conn)
    await conn.execute("INSERT INTO site (site_id, created_at) VALUES ('abc', now())")
    kit1 = await conn.fetchval("INSERT INTO kit (kit_id, created_at) VALUES ('KIT-01', now()) RETURNING kit_no")
    kit2 = await conn.fetchval("INSERT INTO kit (kit_id, created_at) VALUES ('KIT-02', now()) RETURNING kit_no")
    await save(conn, "site", {"site_name": "ABC", "lat": 13.08, "lon": 80.27, "elevation_m": 6,
                              "region_type": "plains"}, 1)
    await save(conn, "site", {"site_name": "ABC College", "lat": 13.08, "lon": 80.27, "elevation_m": 6,
                              "region_type": "coastal", "wind_red_kmh": 58}, 2)
    await save(conn, "kit", {"kit_zone": "Main Block Rooftop", "lat": 13.081, "lon": 80.271, "elevation_m": 30,
                             "exposure": "rooftop"}, 1, kit1)
    await save(conn, "kit", {"kit_zone": "Sports Ground", "lat": 13.079, "lon": 80.269, "exposure": "open_ground",
                             "wind_orange_kmh": 35, "wind_red_kmh": 45}, 1, kit2)
    yield dsn, name, conn
    await conn.close()


async def test_cfg01_load_uses_the_current_versions(db):
    _, _, conn = db
    snap = await config.load_snapshot(conn)
    assert snap.site.version == 2 and snap.site.values["site_name"] == "ABC College"
    assert set(snap.kits) == {"KIT-01", "KIT-02"}
    assert snap.kits["KIT-02"].version_id is not None
    assert snap.resolve("wind_red_kmh", "KIT-02") == config.Resolved(45, "kit")
    assert snap.resolve("wind_red_kmh", "KIT-01") == config.Resolved(58, "site")
    assert snap.resolve("heat_min_tmax_c", "KIT-01") == config.Resolved(37, "default", region_type="coastal")


async def test_kit_without_any_version_resolves_from_the_site(db):
    _, _, conn = db
    await conn.execute("INSERT INTO kit (kit_id, created_at) VALUES ('KIT-03', now())")
    snap = await config.load_snapshot(conn)
    assert snap.kits["KIT-03"] == config.ScopeValues({}, None, None)
    assert snap.resolve("wind_red_kmh", "KIT-03") == config.Resolved(58, "site")


async def test_tst10_effective_view_matches_the_resolver(db):
    """The SQL view covers kit → site → static default; for those keys it must agree with the resolver."""
    _, _, conn = db
    snap = await config.load_snapshot(conn)
    rows = await conn.fetch("SELECT k.kit_id, e.key, e.value::text AS value, e.source "
                            "FROM config_effective_kit e JOIN kit k USING (kit_no)")
    compared = 0
    for r in rows:
        meta = snap.catalogue[r["key"]]
        if meta.region_defaults or meta.computed_from:
            continue  # only the resolver knows these
        resolved = snap.resolve(r["key"], r["kit_id"])
        assert (resolved.value, resolved.source) == (None if r["value"] is None else json.loads(r["value"]),
                                                     r["source"]), (r["kit_id"], r["key"])
        compared += 1
    assert compared > 200


async def test_cache_reloads_on_config_changed(db):
    dsn, name, conn = db
    pool = await create_pool(dsn, schema=name)  # as in a process; `conn` stays free for the saves below
    cache = config.ConfigCache(pool)
    await cache.load()
    assert cache.value("wind_orange_kmh", "KIT-01") == 50

    reloads: asyncio.Queue = asyncio.Queue()
    cache.on_reload(lambda old, new: reloads.put_nowait((old, new)))
    # ConfigCache.follow listens on its own connection; it only needs the database, not the schema
    task = asyncio.create_task(cache.follow(dsn))
    try:
        await asyncio.wait_for(reloads.get(), 5)  # initial reload after LISTEN
        await save(conn, "site", {"site_name": "ABC College", "lat": 13.08, "lon": 80.27, "elevation_m": 6,
                                  "region_type": "coastal", "wind_orange_kmh": 48}, 3)
        await events.notify(conn, "config.changed", {"scope": "site", "version": 3})
        old, new = await asyncio.wait_for(reloads.get(), 5)
        assert old.resolve("wind_orange_kmh", "KIT-01").value == 50
        assert new.resolve("wind_orange_kmh", "KIT-01") == config.Resolved(48, "site")
        assert cache.snapshot is new and cache.snapshot.site.version == 3
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await pool.close()


SITE_V3 = {"site_name": "ABC College", "lat": 13.08, "lon": 80.27, "elevation_m": 6, "region_type": "coastal",
           "wind_red_kmh": 55}


async def test_cfg04_save_creates_the_next_version(db):
    _, _, conn = db
    version_id = await config.save_version(conn, scope="site", values=SITE_V3, base_version=2, created_at=NOW,
                                           reason="lower red wind")
    snap = await config.load_snapshot(conn)
    assert (snap.site.version_id, snap.site.version) == (version_id, 3)
    assert snap.resolve("wind_red_kmh") == config.Resolved(55, "site")
    assert await conn.fetchval("SELECT reason FROM config_version WHERE id = $1", version_id) == "lower red wind"


async def test_cfg04_first_kit_version_and_unknown_kit(db):
    _, _, conn = db
    await conn.execute("INSERT INTO kit (kit_id, created_at) VALUES ('KIT-03', now())")
    await config.save_version(conn, scope="kit", kit_id="KIT-03", values={"kit_zone": "Gate"}, base_version=0,
                              created_at=NOW)
    assert (await config.load_snapshot(conn)).kits["KIT-03"].version == 1
    with pytest.raises(KeyError):
        await config.save_version(conn, scope="kit", kit_id="KIT-99", values={}, base_version=0, created_at=NOW)


async def test_cfg04_outdated_base_version_is_a_conflict(db):
    _, _, conn = db
    for base in (1, 3):  # behind and ahead of the current version 2
        with pytest.raises(config.VersionConflict) as e:
            await config.save_version(conn, scope="site", values=SITE_V3, base_version=base, created_at=NOW)
        assert e.value.current_version == 2


async def test_cfg04_two_saves_on_the_same_version_give_one_conflict(db):
    """TST-13 shape: two admins save on version 2 at the same moment; exactly one wins (unique key)."""
    dsn, name, conn = db
    others = [await asyncpg.connect(dsn, server_settings={"search_path": f"{name},public"}) for _ in range(2)]
    try:
        async def save(c, red):
            async with c.transaction():
                return await config.save_version(c, scope="site", values={**SITE_V3, "wind_red_kmh": red},
                                                 base_version=2, created_at=NOW)
        results = await asyncio.gather(save(others[0], 55), save(others[1], 57), return_exceptions=True)
    finally:
        for c in others:
            await c.close()
    conflicts = [r for r in results if isinstance(r, config.VersionConflict)]
    assert len(conflicts) == 1 and conflicts[0].current_version == 3
    assert await conn.fetchval("SELECT count(*) FROM config_version WHERE scope = 'site'") == 3


def test_snapshot_before_load_is_an_error():
    with pytest.raises(RuntimeError, match="not loaded"):
        config.ConfigCache(None, catalogue={}).snapshot
