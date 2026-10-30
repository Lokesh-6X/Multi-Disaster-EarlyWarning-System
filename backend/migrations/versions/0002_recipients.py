"""Alert recipient lists: recipient, recipient_hazard, recipient_zone.

design/03 §3.5.3 (D24, WEB-41); filled by the YAML import (design/04 §4.6, DD132) and later the config API.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = """
CREATE TABLE recipient (
  id         uuid PRIMARY KEY,
  email      citext NOT NULL UNIQUE,
  label      text NOT NULL,
  min_level  alert_level NOT NULL DEFAULT 'yellow',
  active     boolean NOT NULL DEFAULT true,
  version    integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL
);

CREATE TABLE recipient_hazard (
  recipient_id uuid NOT NULL REFERENCES recipient ON DELETE CASCADE,
  hazard       hazard NOT NULL,
  PRIMARY KEY (recipient_id, hazard)
);

CREATE TABLE recipient_zone (
  recipient_id uuid NOT NULL REFERENCES recipient ON DELETE CASCADE,
  kit_no       smallint NOT NULL REFERENCES kit,
  PRIMARY KEY (recipient_id, kit_no)
);
"""


def upgrade() -> None:
    op.execute(TABLES)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recipient_zone, recipient_hazard, recipient")
