"""Foundations: extensions, all enum types, site, kit, configuration, users, process heartbeat.

design/03 §3.4 (types), §3.5.1 (site, kit), §3.5.2 (configuration, DD23), §3.11 (app_user), §3.12
(process_heartbeat). Later migrations add the other tables.

Revision ID: 0001
Revises:
Create Date: 2026-10-30
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TYPES = """
CREATE TYPE user_role          AS ENUM ('operator', 'admin');
CREATE TYPE user_state         AS ENUM ('invited', 'active', 'deactivated');
CREATE TYPE token_purpose      AS ENUM ('invite', 'password_reset');
CREATE TYPE config_scope       AS ENUM ('site', 'kit');
CREATE TYPE kit_status         AS ENUM ('online', 'offline');
CREATE TYPE status_source      AS ENUM ('status_topic', 'no_data_timeout', 'reading_resumed');
CREATE TYPE measurement        AS ENUM ('temp_c', 'rh_pct', 'pressure_hpa', 'wind_avg_kmh',
                                        'wind_gust_kmh', 'wind_dir_deg', 'rain_mm');
CREATE TYPE temp_sensor        AS ENUM ('bme280', 'dht11');
CREATE TYPE qc_check           AS ENUM ('range', 'spike', 'stuck', 'cross_sensor',
                                        'neighbour', 'external');
CREATE TYPE reject_reason      AS ENUM ('bad_topic', 'wrong_site', 'unknown_kit', 'kit_disabled', 'not_json',
                                        'too_large', 'missing_field', 'unknown_field', 'wrong_type',
                                        'invalid_value', 'kit_id_mismatch', 'ts_out_of_window',
                                        'conflicting_duplicate', 'bad_status_payload');
CREATE TYPE qc_severity        AS ENUM ('suspicious', 'faulty');
CREATE TYPE forecast_variable  AS ENUM ('temp_c', 'rh_pct', 'wind_gust_kmh', 'rain_mm', 'pressure_msl_hpa');
CREATE TYPE run_status         AS ENUM ('running', 'completed', 'failed');
CREATE TYPE model_kind         AS ENUM ('tft', 'event_classifier', 'lightgbm_baseline',
                                        'chronos_bolt', 'persistence', 'climatology', 'open_meteo');
CREATE TYPE hazard             AS ENUM ('heatwave', 'heavy_rain', 'high_wind');
CREATE TYPE alert_type         AS ENUM ('watch', 'warning', 'live');
CREATE TYPE alert_level        AS ENUM ('yellow', 'orange', 'red');
CREATE TYPE alert_source       AS ENUM ('forecast', 'live', 'manual');
CREATE TYPE alert_status       AS ENUM ('active', 'cancelled', 'cleared');
CREATE TYPE scope_kind         AS ENUM ('kit', 'site');
CREATE TYPE alert_change_kind  AS ENUM ('created', 'upgraded', 'downgraded', 'updated', 'cancelled', 'cleared',
                                        'taken_over', 'suppressed', 'unsuppressed', 'suppression_overridden',
                                        'suppression_expired', 'threshold_changed', 'advice_updated');
CREATE TYPE alert_trigger      AS ENUM ('forecast', 'sustained', 'squall', 'manual', 'system');
CREATE TYPE suppression_end    AS ENUM ('expired', 'unsuppressed', 'overridden', 'alert_closed');
CREATE TYPE command_kind       AS ENUM ('suppress', 'unsuppress', 'manual_raise', 'manual_clear');
CREATE TYPE command_status     AS ENUM ('pending', 'applied', 'rejected');
CREATE TYPE email_kind         AS ENUM ('alert', 'maintenance', 'invite', 'password_reset');
CREATE TYPE email_status       AS ENUM ('queued', 'sending', 'sent', 'failed', 'skipped');
CREATE TYPE attempt_outcome    AS ENUM ('sent', 'temporary_failure', 'permanent_failure');
CREATE TYPE job_state          AS ENUM ('pending', 'running', 'completed', 'failed');
CREATE TYPE onboarding_step_kind AS ENUM ('download_history', 'compute_normals', 'generate_labels',
                                          'find_top_events', 'backtest', 'report');
"""

TABLES = """
CREATE TABLE site (
  id          smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  site_id     text NOT NULL UNIQUE CHECK (site_id ~ '^[a-z0-9-]{2,32}$'),
  created_at  timestamptz NOT NULL,
  locked_at   timestamptz
);

CREATE TABLE kit (
  kit_no      smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kit_id      text NOT NULL UNIQUE CHECK (kit_id ~ '^[A-Za-z0-9_-]{1,32}$'),
  created_at  timestamptz NOT NULL
);

CREATE TABLE app_user (
  id              uuid PRIMARY KEY,
  email           citext NOT NULL UNIQUE,
  name            text NOT NULL,
  role            user_role NOT NULL,
  state           user_state NOT NULL,
  password_hash   text,
  failed_logins   smallint NOT NULL DEFAULT 0,
  locked_until    timestamptz,
  created_at      timestamptz NOT NULL,
  last_login_at   timestamptz,
  CHECK ((state = 'invited') = (password_hash IS NULL))
);

CREATE TABLE config_key (
  key           text PRIMARY KEY,
  deprecated    boolean NOT NULL DEFAULT false,
  value_type    text NOT NULL CHECK (value_type IN ('number', 'integer', 'string', 'boolean', 'integer_list')),
  default_value jsonb,
  computed_from text,
  site_allowed  boolean NOT NULL,
  kit_allowed   boolean NOT NULL,
  required_at   config_scope,
  unit          text,
  rules         jsonb NOT NULL DEFAULT '{}',
  description   text NOT NULL
);

CREATE TABLE config_key_region_default (
  key         text NOT NULL REFERENCES config_key ON DELETE CASCADE,
  region_type text NOT NULL CHECK (region_type IN ('plains', 'coastal', 'hilly')),
  value       jsonb NOT NULL,
  PRIMARY KEY (key, region_type)
);

CREATE TABLE config_version (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope       config_scope NOT NULL,
  kit_no      smallint REFERENCES kit,
  version     integer NOT NULL CHECK (version >= 1),
  created_at  timestamptz NOT NULL,
  created_by  uuid REFERENCES app_user,
  reason      text,
  CHECK ((scope = 'kit') = (kit_no IS NOT NULL)),
  UNIQUE NULLS NOT DISTINCT (scope, kit_no, version)
);

CREATE TABLE config_value (
  version_id  integer NOT NULL REFERENCES config_version ON DELETE CASCADE,
  key         text NOT NULL REFERENCES config_key,
  value       jsonb NOT NULL CHECK (jsonb_typeof(value) IN ('number', 'string', 'boolean', 'array')),
  PRIMARY KEY (version_id, key)
);

CREATE TABLE process_heartbeat (
  name         text PRIMARY KEY,
  pid          integer NOT NULL,
  started_at   timestamptz NOT NULL,
  last_beat_at timestamptz NOT NULL,
  version      text NOT NULL
);
"""

VIEWS = """
CREATE VIEW config_current AS
  SELECT DISTINCT ON (scope, kit_no) id, scope, kit_no, version
  FROM config_version ORDER BY scope, kit_no, version DESC;

CREATE VIEW config_effective_kit AS
  SELECT k.kit_no, ck.key,
         COALESCE(kv.value, sv.value, ck.default_value) AS value,
         CASE WHEN kv.value IS NOT NULL THEN 'kit'
              WHEN sv.value IS NOT NULL THEN 'site' ELSE 'default' END AS source
  FROM kit k
  CROSS JOIN config_key ck
  LEFT JOIN config_current kc ON kc.scope = 'kit' AND kc.kit_no = k.kit_no
  LEFT JOIN config_value  kv ON kv.version_id = kc.id AND kv.key = ck.key
  LEFT JOIN config_current sc ON sc.scope = 'site'
  LEFT JOIN config_value  sv ON sv.version_id = sc.id AND sv.key = ck.key;
"""


def upgrade() -> None:
    # Created by scripts/setup-databases.ps1 as postgres (TimescaleDB needs a superuser); no-op here
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute(TYPES)
    op.execute(TABLES)
    op.execute(VIEWS)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS config_effective_kit, config_current")
    op.execute("DROP TABLE IF EXISTS process_heartbeat, config_value, config_version, config_key_region_default, "
               "config_key, app_user, kit, site")
    for line in TYPES.split(";"):
        if "CREATE TYPE" in line:
            op.execute(f"DROP TYPE IF EXISTS {line.split()[2]}")
