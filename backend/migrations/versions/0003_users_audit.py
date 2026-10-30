"""Sessions, invite/reset tokens, e-mail preferences (with default rows for every user) and the audit log.

design/03 §3.11 (DD14, WEB-02, WEB-03, WEB-08, WEB-25, DD134), indexes of §3.13. `app_user` itself is in 0001.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-30
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLES = """
CREATE TABLE user_session (
  token_hash  bytea PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES app_user,
  csrf_hash   bytea NOT NULL,
  created_at  timestamptz NOT NULL,
  expires_at  timestamptz NOT NULL,
  ip          inet,
  user_agent  text
);
CREATE INDEX user_session_user ON user_session (user_id);

CREATE TABLE user_token (
  id          uuid PRIMARY KEY,
  token_hash  bytea NOT NULL UNIQUE,
  user_id     uuid NOT NULL REFERENCES app_user,
  purpose     token_purpose NOT NULL,
  created_at  timestamptz NOT NULL,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz,
  revoked_at  timestamptz
);
CREATE UNIQUE INDEX user_token_one_open ON user_token (user_id, purpose)
  WHERE used_at IS NULL AND revoked_at IS NULL;

CREATE TABLE user_alert_preference (
  user_id             uuid PRIMARY KEY REFERENCES app_user,
  enabled             boolean NOT NULL DEFAULT true,
  min_level           alert_level NOT NULL DEFAULT 'yellow',
  maintenance_notices boolean NOT NULL DEFAULT true
);
CREATE TABLE user_alert_hazard (
  user_id uuid NOT NULL REFERENCES app_user,
  hazard  hazard NOT NULL,
  PRIMARY KEY (user_id, hazard)
);
CREATE TABLE user_alert_type (
  user_id uuid NOT NULL REFERENCES app_user,
  type    alert_type NOT NULL,
  PRIMARY KEY (user_id, type)
);

CREATE TABLE audit_entry (
  id          uuid PRIMARY KEY,
  at          timestamptz NOT NULL,
  actor_id    uuid REFERENCES app_user,
  ip          inet,
  action      text NOT NULL,
  entity_type text,
  entity_id   text,
  reason      text
);
CREATE INDEX audit_entry_at ON audit_entry (at DESC);
CREATE INDEX audit_entry_actor ON audit_entry (actor_id, at DESC);
CREATE INDEX audit_entry_entity ON audit_entry (entity_type, entity_id, at DESC);

CREATE TABLE audit_change (
  audit_id  uuid NOT NULL REFERENCES audit_entry ON DELETE CASCADE,
  field     text NOT NULL,
  old_value jsonb,
  new_value jsonb,
  PRIMARY KEY (audit_id, field)
);
"""

# DD134: every new user starts with every alert e-mail (WEB-08); the profile narrows it
TRIGGER = """
CREATE FUNCTION user_default_preferences() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO user_alert_preference (user_id) VALUES (NEW.id);
  INSERT INTO user_alert_hazard SELECT NEW.id, h FROM unnest(enum_range(NULL::hazard)) h;
  INSERT INTO user_alert_type   SELECT NEW.id, t FROM unnest(enum_range(NULL::alert_type)) t;
  RETURN NULL;
END $$;
CREATE TRIGGER app_user_default_preferences AFTER INSERT ON app_user
  FOR EACH ROW EXECUTE FUNCTION user_default_preferences();
"""


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(TRIGGER)
    # users created before this migration get their default rows too
    op.execute("INSERT INTO user_alert_preference (user_id) SELECT id FROM app_user")
    op.execute("INSERT INTO user_alert_hazard SELECT u.id, h FROM app_user u, unnest(enum_range(NULL::hazard)) h")
    op.execute("INSERT INTO user_alert_type SELECT u.id, t FROM app_user u, unnest(enum_range(NULL::alert_type)) t")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS app_user_default_preferences ON app_user")
    op.execute("DROP FUNCTION IF EXISTS user_default_preferences()")
    op.execute("DROP TABLE IF EXISTS audit_change, audit_entry, user_alert_type, user_alert_hazard, "
               "user_alert_preference, user_token, user_session")
