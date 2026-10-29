"""Database access: asyncpg connection pool (design/01 §1.3.2) and the demo-database guard (11 §11.3.1)."""
from __future__ import annotations

import asyncpg

# Machine-time limits (DD117): a query or connect that takes longer than this fails instead of hanging
COMMAND_TIMEOUT_S = 30
CONNECT_TIMEOUT_S = 10


class WrongDatabase(RuntimeError):
    """A demo process found a real database, or a real process found the demo database."""


async def create_pool(dsn: str, *, schema: str | None = None, application_name: str = "ews",
                      min_size: int = 1, max_size: int = 5) -> asyncpg.Pool:
    """Pool for one process; `schema` sets the search path (used by the integration tests)."""
    server_settings = {"application_name": application_name}
    if schema:
        server_settings["search_path"] = f"{schema},public"  # extensions live in public
    return await asyncpg.create_pool(
        dsn, min_size=min_size, max_size=max_size, timeout=CONNECT_TIMEOUT_S,
        command_timeout=COMMAND_TIMEOUT_S, server_settings=server_settings)


async def is_demo_database(conn: asyncpg.Pool | asyncpg.Connection) -> bool:
    """`ews.is_demo` is set to on only for ews_demo (14 §14.1.2); elsewhere it does not exist."""
    return await conn.fetchval("SELECT coalesce(current_setting('ews.is_demo', true), '') = 'on'")


async def check_database_mode(conn: asyncpg.Pool | asyncpg.Connection, clock_mode: str) -> None:
    """Refuse to start against the wrong database (11 §11.3.1, DD95)."""
    demo = await is_demo_database(conn)
    name = await conn.fetchval("SELECT current_database()")
    if clock_mode == "demo" and not demo:
        raise WrongDatabase(f"EWS_CLOCK=demo but {name} is not a demo database (ews.is_demo is not on)")
    if clock_mode != "demo" and demo:
        raise WrongDatabase(f"EWS_CLOCK=real but {name} is the demo database; use DATABASE_URL")


async def _check() -> int:
    """start.ps1 step 3: connection, TimescaleDB, and the right database for the clock mode."""
    from ews.common.settings import load_settings, mask_url

    settings = load_settings()
    try:
        conn = await asyncpg.connect(settings.active_database_url, timeout=CONNECT_TIMEOUT_S)
    except (OSError, asyncpg.PostgresError) as e:
        print(f"cannot connect to {mask_url(settings.active_database_url)}: {e}")
        return 1
    try:
        version = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
        if not version:
            print(f"TimescaleDB extension missing in {await conn.fetchval('SELECT current_database()')} "
                  "(scripts/setup-databases.ps1)")
            return 1
        await check_database_mode(conn, settings.clock_mode)
        print(f"{await conn.fetchval('SELECT current_database()')} OK, TimescaleDB {version}, clock {settings.clock_mode}")
        return 0
    except WrongDatabase as e:
        print(e)
        return 1
    finally:
        await conn.close()


if __name__ == "__main__":
    import asyncio
    import sys

    if sys.argv[1:] != ["check"]:
        sys.exit("usage: python -m ews.common.db check")
    sys.exit(asyncio.run(_check()))
