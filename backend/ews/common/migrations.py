"""Run Alembic migrations from code (start.ps1 step 3, tests)."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[2]


def sqlalchemy_url(url: str) -> str:
    """postgresql://… (asyncpg style, as in .env) -> postgresql+psycopg://… for Alembic."""
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    raise ValueError("database URL must start with postgresql://")


def alembic_config(url: str | None = None, schema: str | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["url"] = url
    cfg.attributes["schema"] = schema
    return cfg


def upgrade(url: str | None = None, revision: str = "head", schema: str | None = None) -> None:
    command.upgrade(alembic_config(url, schema), revision)


def downgrade(url: str | None = None, revision: str = "base", schema: str | None = None) -> None:
    command.downgrade(alembic_config(url, schema), revision)
