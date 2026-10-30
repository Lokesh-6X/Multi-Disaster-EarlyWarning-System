"""Reading tables, hypertables and the kit_outage view (design/03 §3.6, §3.14, DD24, DD123; DP-02, DP-13)."""
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from ews.common import migrations

pytestmark = pytest.mark.integration
T = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
HYPERTABLES = {"reading_raw": timedelta(days=7), "reading_clean": timedelta(days=7),
               "reading_derived": timedelta(days=7), "reading_qc_flag": timedelta(days=30)}


@pytest.fixture
async def db(schema):
    dsn, name = schema
    migrations.upgrade(dsn, schema=name)
    conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{name},public"})
    kit_no = await conn.fetchval("INSERT INTO kit (kit_id, created_at) VALUES ('KIT-01', $1) RETURNING kit_no", T)
    yield dsn, name, conn, kit_no
    await conn.close()


async def test_hypertables_and_chunk_sizes(db):
    _, name, conn, _ = db
    rows = await conn.fetch(
        "SELECT hypertable_name, time_interval FROM timescaledb_information.dimensions "
        "WHERE hypertable_schema = $1 AND column_name = 'ts'", name)
    assert {r["hypertable_name"]: r["time_interval"] for r in rows} == HYPERTABLES


async def test_dp02_one_raw_row_per_kit_and_time(db):
    _, _, conn, kit_no = db
    insert = ("INSERT INTO reading_raw (kit_no, ts, received_at, seq, bme_temp_c, bme_rh_pct, bme_pressure_hpa, "
              "wind_avg_kmh, wind_gust_kmh, rain_tips) VALUES ($1, $2, $2, $3, 30, 60, 1008, 5, 9, 0) "
              "ON CONFLICT DO NOTHING")
    await conn.execute(insert, kit_no, T, 1)
    await conn.execute(insert, kit_no, T, 2)
    assert await conn.fetchval("SELECT seq FROM reading_raw") == 1


async def test_dd123_clean_reading_records_both_config_versions(db):
    _, _, conn, kit_no = db
    site_v = await conn.fetchval("INSERT INTO config_version (scope, version, created_at) "
                                 "VALUES ('site', 1, $1) RETURNING id", T)
    kit_v = await conn.fetchval("INSERT INTO config_version (scope, kit_no, version, created_at) "
                                "VALUES ('kit', $1, 1, $2) RETURNING id", kit_no, T)
    await conn.execute("INSERT INTO reading_clean (kit_no, ts, kit_config_version_id, site_config_version_id, "
                       "temp_c, temp_sensor) VALUES ($1, $2, $3, $4, 30.1, 'bme280')", kit_no, T, kit_v, site_v)
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await conn.execute("INSERT INTO reading_clean (kit_no, ts, kit_config_version_id, site_config_version_id) "
                           "VALUES ($1, $2, 999, $3)", kit_no, T + timedelta(minutes=1), site_v)


async def test_dp13_kit_outage_view(db):
    _, _, conn, kit_no = db
    events = [(T, "online", "status_topic"), (T + timedelta(minutes=10), "offline", "status_topic"),
              (T + timedelta(minutes=25), "online", "reading_resumed"),
              (T + timedelta(hours=2), "offline", "no_data_timeout")]
    await conn.executemany("INSERT INTO kit_status_event (kit_no, at, status, source) VALUES ($1, $2, $3, $4)",
                           [(kit_no, *e) for e in events])
    rows = await conn.fetch("SELECT offline_at, online_at, source::text FROM kit_outage ORDER BY offline_at")
    assert [tuple(r) for r in rows] == [(T + timedelta(minutes=10), T + timedelta(minutes=25), "status_topic"),
                                        (T + timedelta(hours=2), None, "no_data_timeout")]


async def test_dp12_rejected_message_without_a_known_kit(db):
    _, _, conn, _ = db
    await conn.execute("INSERT INTO rejected_message (received_at, topic, reason_code, detail, payload_excerpt) "
                       "VALUES ($1, 'sites/abc/kits/KIT-99/readings', 'unknown_kit', 'KIT-99 is not configured', "
                       "'{}')", T)
    assert await conn.fetchval("SELECT kit_no FROM rejected_message") is None


async def test_upgrade_downgrade_one_and_upgrade_again(schema):
    """M1.6 check: upgrade head, downgrade -1, upgrade again on ews_test."""
    dsn, name = schema
    migrations.upgrade(dsn, schema=name)
    migrations.downgrade(dsn, revision="-1", schema=name)
    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval("SELECT to_regclass($1)", f"{name}.reading_raw") is None
        migrations.upgrade(dsn, schema=name)
        assert await conn.fetchval("SELECT to_regclass($1)", f"{name}.reading_raw") is not None
    finally:
        await conn.close()
