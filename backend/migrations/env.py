"""Alembic environment: migrations are plain SQL (design/03 §3.1), run online with psycopg."""
from alembic import context
from sqlalchemy import create_engine, text

from ews.common.migrations import sqlalchemy_url

config = context.config
x = context.get_x_argument(as_dictionary=True)
url = config.attributes.get("url") or x.get("url")
schema = config.attributes.get("schema") or x.get("schema")

if not url:
    from ews.common.settings import load_settings

    url = load_settings().active_database_url

# Extensions (citext, timescaledb) live in public, so it stays on the path after the target schema
connect_args = {"options": f"-c search_path={schema},public"} if schema else {}
engine = create_engine(sqlalchemy_url(url), connect_args=connect_args)

with engine.connect() as connection:
    context.configure(connection=connection, version_table_schema=schema, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
    connection.commit()
engine.dispose()
