"""Integration tests run against the ews_test database (design/12), each in its own schema."""
import secrets
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from ews.common.settings import load_settings


def ews_test_url() -> str:
    """DATABASE_URL from .env with the database name replaced by ews_test."""
    parts = urlsplit(load_settings().database_url)
    return urlunsplit(parts._replace(path="/ews_test"))


def demo_database_url() -> str:
    return load_settings().demo_database_url


@pytest.fixture(scope="session", autouse=True)
def clean_test_database():
    """12 §12.2: ews_test starts from scratch each run. Test schemas also search `public` (for the
    extensions), so anything migrated there by hand is removed first."""
    import asyncio

    from ews.common import migrations

    dsn = ews_test_url()

    async def migrated() -> bool:
        conn = await asyncpg.connect(dsn)
        try:
            return await conn.fetchval("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        finally:
            await conn.close()

    if asyncio.run(migrated()):
        migrations.downgrade(dsn)


@pytest.fixture
async def schema():
    """A fresh schema, dropped after the test; returns (dsn, schema name)."""
    dsn = ews_test_url()
    name = "it_" + secrets.token_hex(4)
    conn = await asyncpg.connect(dsn)
    await conn.execute(f"CREATE SCHEMA {name}")
    await conn.close()
    yield dsn, name
    conn = await asyncpg.connect(dsn)
    await conn.execute(f"DROP SCHEMA {name} CASCADE")
    await conn.close()
