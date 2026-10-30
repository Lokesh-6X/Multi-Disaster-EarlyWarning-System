"""Readings: firmware history, raw / clean / derived readings, QC flags, kit status, rejected messages.

design/03 §3.5.1 (kit_firmware), §3.6.1, §3.6.3 (DD24, DD123, DP-02, DP-03, DP-12, DP-13); hypertables with the
chunk sizes of §3.14. Continuous aggregates, compression and retention policies come with M2 (DD107).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-30
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLES = """
CREATE TABLE kit_firmware (
  kit_no        smallint NOT NULL REFERENCES kit,
  first_seen_at timestamptz NOT NULL,
  fw            text NOT NULL,
  PRIMARY KEY (kit_no, first_seen_at)
);

CREATE TABLE reading_raw (
  kit_no           smallint NOT NULL REFERENCES kit,
  ts               timestamptz NOT NULL,
  received_at      timestamptz NOT NULL,
  seq              bigint NOT NULL,
  bme_temp_c       real NOT NULL,
  bme_rh_pct       real NOT NULL,
  bme_pressure_hpa real NOT NULL,
  dht_temp_c       real,
  dht_rh_pct       real,
  wind_avg_kmh     real NOT NULL,
  wind_gust_kmh    real NOT NULL,
  wind_dir_deg     real,
  rain_tips        smallint NOT NULL,
  rssi_dbm         smallint,
  uptime_s         integer,
  PRIMARY KEY (kit_no, ts)
);

CREATE TABLE reading_clean (
  kit_no                 smallint NOT NULL REFERENCES kit,
  ts                     timestamptz NOT NULL,
  kit_config_version_id  integer NOT NULL REFERENCES config_version,
  site_config_version_id integer NOT NULL REFERENCES config_version,
  temp_c                 real,
  temp_sensor            temp_sensor,
  rh_pct                 real,
  pressure_msl_hpa       real,
  wind_avg_kmh           real,
  wind_gust_kmh          real,
  wind_dir_deg           real,
  rain_mm                real,
  PRIMARY KEY (kit_no, ts)
);

CREATE TABLE reading_derived (
  kit_no                   smallint NOT NULL REFERENCES kit,
  ts                       timestamptz NOT NULL,
  heat_index_c             real,
  rain_rate_mmh            real,
  rain_1h_mm               real,
  rain_3h_mm               real,
  rain_24h_mm              real,
  pressure_tendency_1h_hpa real,
  pressure_tendency_3h_hpa real,
  gust_trend_15m_kmh       real,
  gust_trend_30m_kmh       real,
  gust_trend_60m_kmh       real,
  temp_change_30m_c        real,
  PRIMARY KEY (kit_no, ts)
);

CREATE TABLE reading_qc_flag (
  kit_no      smallint NOT NULL REFERENCES kit,
  ts          timestamptz NOT NULL,
  measurement measurement NOT NULL,
  check_kind  qc_check NOT NULL,
  severity    qc_severity NOT NULL,
  observed    real,
  detail      text,
  PRIMARY KEY (kit_no, ts, measurement, check_kind)
);

CREATE TABLE kit_status_event (
  kit_no  smallint NOT NULL REFERENCES kit,
  at      timestamptz NOT NULL,
  status  kit_status NOT NULL,
  source  status_source NOT NULL,
  PRIMARY KEY (kit_no, at)
);

CREATE TABLE rejected_message (
  id              bigint GENERATED ALWAYS AS IDENTITY,
  received_at     timestamptz NOT NULL,
  topic           text NOT NULL,
  kit_no          smallint REFERENCES kit,
  reason_code     reject_reason NOT NULL,
  detail          text NOT NULL,
  payload_excerpt text NOT NULL,
  PRIMARY KEY (id)
);
"""

HYPERTABLES = {  # §3.14: partition column ts
    "reading_raw": "7 days",
    "reading_clean": "7 days",
    "reading_derived": "7 days",
    "reading_qc_flag": "30 days",
}

VIEWS = """
CREATE VIEW kit_outage AS
  SELECT kit_no, at AS offline_at, next_at AS online_at, source
  FROM (SELECT kit_no, at, status, source,
               lead(at) OVER (PARTITION BY kit_no ORDER BY at) AS next_at
        FROM kit_status_event) e
  WHERE status = 'offline';
"""


def upgrade() -> None:
    op.execute(TABLES)
    for table, chunk in HYPERTABLES.items():
        op.execute(f"SELECT create_hypertable('{table}', by_range('ts', INTERVAL '{chunk}'))")
    op.execute(VIEWS)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS kit_outage")
    op.execute("DROP TABLE IF EXISTS rejected_message, kit_status_event, reading_qc_flag, reading_derived, "
               "reading_clean, reading_raw, kit_firmware")
