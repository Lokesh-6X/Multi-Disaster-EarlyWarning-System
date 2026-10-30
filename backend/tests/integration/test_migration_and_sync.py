"""First migration and the settings-catalogue sync (design/03 §3.4–3.5, §3.11, design/04 §4.7, DD110)."""
import asyncpg
import pytest
import yaml

from ews.common import config, migrations

pytestmark = pytest.mark.integration

TABLES = {"site", "kit", "config_key", "config_key_region_default", "config_version", "config_value",
          "app_user", "process_heartbeat", "alembic_version", "recipient", "recipient_hazard", "recipient_zone",
          "user_session", "user_token", "user_alert_preference", "user_alert_hazard", "user_alert_type",
          "audit_entry", "audit_change", "kit_firmware", "reading_raw", "reading_clean", "reading_derived",
          "reading_qc_flag", "kit_status_event", "rejected_message"}


async def test_upgrade_head_on_empty_schema(schema):
    dsn, name = schema
    migrations.upgrade(dsn, schema=name)
    conn = await asyncpg.connect(dsn)
    try:
        tables = {r["table_name"] for r in await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = $1 AND table_type = 'BASE TABLE'", name)}
        assert TABLES <= tables
        enums = {r["typname"] for r in await conn.fetch(
            "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
            "WHERE n.nspname = $1 AND t.typtype = 'e'", name)}
        assert len(enums) == 30 and {"alert_level", "config_scope", "onboarding_step_kind"} <= enums
        # enum order = severity (03 §3.1): level >= 'orange' works
        assert await conn.fetchval(f"SELECT 'red'::{name}.alert_level > 'orange'::{name}.alert_level")
        views = {r["table_name"] for r in await conn.fetch(
            "SELECT table_name FROM information_schema.views WHERE table_schema = $1", name)}
        assert {"config_current", "config_effective_kit"} <= views
    finally:
        await conn.close()


async def test_site_has_exactly_one_row(schema):
    dsn, name = schema
    migrations.upgrade(dsn, schema=name)
    conn = await asyncpg.connect(dsn, server_settings={"search_path": name})
    try:
        await conn.execute("INSERT INTO site (site_id, created_at) VALUES ('abc', now())")
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute("INSERT INTO site (site_id, created_at) VALUES ('xyz', now())")
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("INSERT INTO site (id, site_id, created_at) VALUES (2, 'xyz', now())")
    finally:
        await conn.close()


async def test_config_version_optimistic_locking(schema):
    """CFG-04: two saves based on the same version: the second one fails on the unique constraint."""
    dsn, name = schema
    migrations.upgrade(dsn, schema=name)
    conn = await asyncpg.connect(dsn, server_settings={"search_path": name})
    try:
        await conn.execute("INSERT INTO config_version (scope, version, created_at) VALUES ('site', 1, now())")
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute("INSERT INTO config_version (scope, version, created_at) VALUES ('site', 1, now())")
    finally:
        await conn.close()


async def test_sync_loads_catalogue_and_is_idempotent(schema):
    """DD110: sync loads ~130 keys; running it twice changes nothing."""
    dsn, name = schema
    migrations.upgrade(dsn, schema=name)
    conn = await asyncpg.connect(dsn, server_settings={"search_path": name})
    try:
        first = await config.sync(conn)
        n = await conn.fetchval("SELECT count(*) FROM config_key")
        assert 120 <= n <= 140 and first.inserted == n and first.deprecated == 0
        assert await conn.fetchval("SELECT count(*) FROM config_key_region_default") == 7 * 3
        row = await conn.fetchrow("SELECT * FROM config_key WHERE key = 'lat'")
        assert row["site_allowed"] and row["kit_allowed"] and row["required_at"] == "site"
        assert row["default_value"] is None

        second = await config.sync(conn)
        assert (second.inserted, second.updated, second.deprecated, second.undeprecated) == (0, 0, 0, 0)
        assert second.unchanged == n
    finally:
        await conn.close()


async def test_removed_key_becomes_deprecated_and_comes_back(schema, tmp_path):
    """04 §4.7: a key removed from defaults.yaml is marked deprecated, never deleted."""
    dsn, name = schema
    migrations.upgrade(dsn, schema=name)
    full = yaml.safe_load(config.DEFAULTS_FILE.read_text(encoding="utf-8"))
    smaller = {k: v for k, v in full.items() if k != "qc_wind_max_kmh"}
    path = tmp_path / "defaults.yaml"
    path.write_text(yaml.safe_dump(smaller, allow_unicode=True), encoding="utf-8")
    conn = await asyncpg.connect(dsn, server_settings={"search_path": name})
    try:
        await config.sync(conn)
        # an old config version references the key
        version_id = await conn.fetchval(
            "INSERT INTO config_version (scope, version, created_at) VALUES ('site', 1, now()) RETURNING id")
        await conn.execute("INSERT INTO config_value VALUES ($1, 'qc_wind_max_kmh', '180')", version_id)

        result = await config.sync(conn, path)
        assert result.deprecated == 1
        row = await conn.fetchrow("SELECT deprecated FROM config_key WHERE key = 'qc_wind_max_kmh'")
        assert row["deprecated"] is True
        assert await conn.fetchval("SELECT count(*) FROM config_value WHERE key = 'qc_wind_max_kmh'") == 1

        back = await config.sync(conn)
        assert back.undeprecated == 1
        assert await conn.fetchval("SELECT deprecated FROM config_key WHERE key = 'qc_wind_max_kmh'") is False
    finally:
        await conn.close()


async def test_changed_default_is_updated(schema, tmp_path):
    dsn, name = schema
    migrations.upgrade(dsn, schema=name)
    full = yaml.safe_load(config.DEFAULTS_FILE.read_text(encoding="utf-8"))
    full["wind_red_kmh"]["default"] = 60
    path = tmp_path / "defaults.yaml"
    path.write_text(yaml.safe_dump(full, allow_unicode=True), encoding="utf-8")
    conn = await asyncpg.connect(dsn, server_settings={"search_path": name})
    try:
        await config.sync(conn)
        result = await config.sync(conn, path)
        assert result.updated == 1
        assert await conn.fetchval("SELECT default_value FROM config_key WHERE key = 'wind_red_kmh'") == "60"
    finally:
        await conn.close()
