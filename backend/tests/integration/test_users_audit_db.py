"""Users, sessions, tokens, preferences and audit tables (design/03 §3.11, DD134; WEB-02, WEB-08, WEB-25)."""
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from ews.common import migrations
from ews.common.ids import uuid7

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
async def conn(schema):
    dsn, name = schema
    migrations.upgrade(dsn, schema=name)
    conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{name},public"})
    yield conn
    await conn.close()


async def add_user(conn, email="op@abc.example", state="invited", role="operator"):
    user_id = uuid7()
    await conn.execute("INSERT INTO app_user (id, email, name, role, state, password_hash, created_at) "
                       "VALUES ($1, $2, 'Op', $3, $4, $5, $6)", user_id, email, role, state,
                       None if state == "invited" else "argon2-hash", NOW)
    return user_id


async def test_web08_creating_a_user_creates_its_default_preferences(conn):
    """M1.5 check (DD134)."""
    user_id = await add_user(conn)
    pref = await conn.fetchrow("SELECT enabled, min_level::text AS min_level, maintenance_notices "
                               "FROM user_alert_preference WHERE user_id = $1", user_id)
    assert dict(pref) == {"enabled": True, "min_level": "yellow", "maintenance_notices": True}
    hazards = await conn.fetch("SELECT hazard::text FROM user_alert_hazard WHERE user_id = $1 ORDER BY 1", user_id)
    types = await conn.fetch("SELECT type::text FROM user_alert_type WHERE user_id = $1 ORDER BY 1", user_id)
    assert [r[0] for r in hazards] == ["heatwave", "heavy_rain", "high_wind"]
    assert [r[0] for r in types] == ["live", "warning", "watch"]


async def test_every_user_gets_its_own_rows(conn):
    a = await add_user(conn, "a@abc.example")
    b = await add_user(conn, "b@abc.example", state="active", role="admin")
    rows = await conn.fetch("SELECT user_id, count(*) FROM user_alert_hazard GROUP BY user_id")
    assert {r["user_id"]: r["count"] for r in rows} == {a: 3, b: 3}


async def test_users_existing_before_the_migration_get_defaults(schema):
    dsn, name = schema
    migrations.upgrade(dsn, revision="0002", schema=name)
    conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{name},public"})
    try:
        user_id = await add_user(conn)
        migrations.upgrade(dsn, schema=name)
        assert await conn.fetchval("SELECT count(*) FROM user_alert_type WHERE user_id = $1", user_id) == 3
        assert await conn.fetchval("SELECT enabled FROM user_alert_preference WHERE user_id = $1", user_id)
    finally:
        await conn.close()


async def test_web02_only_one_open_token_per_purpose(conn):
    user_id = await add_user(conn)

    async def token(revoked=None):
        await conn.execute("INSERT INTO user_token (id, token_hash, user_id, purpose, created_at, expires_at, "
                           "revoked_at) VALUES ($1, $2, $3, 'invite', $4, $5, $6)",
                           uuid7(), uuid7().bytes, user_id, NOW, NOW + timedelta(hours=48), revoked)

    await token(revoked=NOW)      # a revoked one does not count
    await token()
    with pytest.raises(asyncpg.UniqueViolationError):
        await token()


async def test_web25_audit_entry_with_changes(conn):
    actor = await add_user(conn, state="active", role="admin")
    audit_id = uuid7()
    await conn.execute("INSERT INTO audit_entry (id, at, actor_id, ip, action, entity_type, entity_id, reason) "
                       "VALUES ($1, $2, $3, '127.0.0.1', 'config.kit.update', 'kit', 'KIT-02', 'local risk')",
                       audit_id, NOW, actor)
    await conn.executemany("INSERT INTO audit_change (audit_id, field, old_value, new_value) "
                           "VALUES ($1, $2, $3::jsonb, $4::jsonb)",
                           [(audit_id, "wind_orange_kmh", "50", "35"), (audit_id, "wind_red_kmh", None, "45")])
    rows = await conn.fetch("SELECT field, old_value::text, new_value::text FROM audit_change ORDER BY field")
    assert [tuple(r) for r in rows] == [("wind_orange_kmh", "50", "35"), ("wind_red_kmh", None, "45")]


async def test_downgrade_and_upgrade_again(schema):
    dsn, name = schema
    migrations.upgrade(dsn, schema=name)
    migrations.downgrade(dsn, revision="0002", schema=name)
    migrations.upgrade(dsn, schema=name)
