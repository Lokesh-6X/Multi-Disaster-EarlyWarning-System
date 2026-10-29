-- Week-1 check 1 (M0.3, DD113, analysis/05 §5.3) and part of check-setup.ps1 (design/14 §14.1.3).
-- Proves the TimescaleDB features the schema relies on (design/03 §3.6.2, §3.14) on this install:
--   1 hypertable on time   2 continuous aggregate with materialized_only = false
--   3 compression policy   4 retention policy   5 integer hypertable with set_integer_now_func
-- Runs as role ews in ews_test, inside its own schema, and drops everything at the end.
-- Prints "TIMESCALE CHECK OK" on success; any failure stops the script (ON_ERROR_STOP).
\set ON_ERROR_STOP on
\set QUIET on
SET client_min_messages = warning;

DROP SCHEMA IF EXISTS tscheck CASCADE;
CREATE SCHEMA tscheck;

SELECT 'TimescaleDB ' || extversion || ', license ' || current_setting('timescaledb.license') AS info
FROM pg_extension WHERE extname = 'timescaledb' \gset
\echo :info

-- 1 Hypertable on time (like reading_clean: ts, 7-day chunks)
CREATE TABLE tscheck.reading (
    kit_no  smallint    NOT NULL,
    ts      timestamptz NOT NULL,
    temp_c  real,
    rain_mm real,
    PRIMARY KEY (kit_no, ts)
);
SELECT create_hypertable('tscheck.reading', by_range('ts', INTERVAL '7 days')) \gset
INSERT INTO tscheck.reading
SELECT 1, g, 20 + random() * 10, 0
FROM generate_series(now() - INTERVAL '30 days', now(), INTERVAL '10 minutes') AS g;
\echo '1 hypertable                          OK'

-- 2 Continuous aggregate with real-time part (like reading_15m)
CREATE MATERIALIZED VIEW tscheck.reading_15m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT kit_no, time_bucket('15 minutes', ts) AS bucket, avg(temp_c) AS temp_c, count(*) AS n_readings
FROM tscheck.reading
GROUP BY kit_no, bucket
WITH NO DATA;
SELECT add_continuous_aggregate_policy('tscheck.reading_15m',
    start_offset      => INTERVAL '3 hours',
    end_offset        => INTERVAL '2 minutes',
    schedule_interval => INTERVAL '1 minute') \gset
-- Nothing is materialized yet, so rows can only come from the real-time part
DO $$
BEGIN
    IF (SELECT count(*) FROM tscheck.reading_15m) = 0 THEN
        RAISE EXCEPTION 'continuous aggregate returned no rows: materialized_only = false is not working';
    END IF;
END $$;
\echo '2 continuous aggregate (real-time)    OK'

-- 3 Compression: settings, policy, and one chunk really compressed
ALTER TABLE tscheck.reading SET (timescaledb.compress,
    timescaledb.compress_segmentby = 'kit_no',
    timescaledb.compress_orderby   = 'ts DESC');
SELECT add_compression_policy('tscheck.reading', compress_after => INTERVAL '7 days') \gset
SELECT count(compress_chunk(c)) AS compressed
FROM show_chunks('tscheck.reading', older_than => now() - INTERVAL '14 days') AS c \gset
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM timescaledb_information.chunks
                   WHERE hypertable_schema = 'tscheck' AND hypertable_name = 'reading' AND is_compressed) THEN
        RAISE EXCEPTION 'no chunk was compressed';
    END IF;
    -- 30 days of 10-minute rows = 4 320 (+1 for the inclusive end); all must still be readable
    IF (SELECT count(*) FROM tscheck.reading) <> 4321 THEN
        RAISE EXCEPTION 'compressed rows are not readable';
    END IF;
END $$;
-- Compression on the continuous aggregate too (reading_15m: 30 days)
ALTER MATERIALIZED VIEW tscheck.reading_15m SET (timescaledb.compress = true);
SELECT add_compression_policy('tscheck.reading_15m', compress_after => INTERVAL '30 days') \gset
\echo '3 compression policy (+ chunk, cagg)  OK'

-- 4 Retention policy (like reading_derived: 180 days)
SELECT add_retention_policy('tscheck.reading', drop_after => INTERVAL '180 days') \gset
\echo '4 retention policy                    OK'

-- 5 Integer hypertable on run_id with an integer-now function (like forecast_value)
CREATE TABLE tscheck.run (id integer PRIMARY KEY);
INSERT INTO tscheck.run SELECT generate_series(1, 2000);
CREATE TABLE tscheck.forecast_value (
    run_id      integer     NOT NULL,
    kit_no      smallint    NOT NULL,
    target_time timestamptz NOT NULL,
    p50         real,
    PRIMARY KEY (run_id, kit_no, target_time)
);
SELECT create_hypertable('tscheck.forecast_value', by_range('run_id', 672)) \gset
CREATE FUNCTION tscheck.latest_run_id() RETURNS integer LANGUAGE sql STABLE AS
    $$ SELECT coalesce(max(id), 0) FROM tscheck.run $$;
SELECT set_integer_now_func('tscheck.forecast_value', 'tscheck.latest_run_id') \gset
INSERT INTO tscheck.forecast_value
SELECT r, 1, now() + make_interval(hours => h), 25
FROM generate_series(1, 2000) AS r, generate_series(1, 3) AS h;
ALTER TABLE tscheck.forecast_value SET (timescaledb.compress,
    timescaledb.compress_segmentby = 'kit_no',
    timescaledb.compress_orderby   = 'target_time');
SELECT add_compression_policy('tscheck.forecast_value', compress_after => 192) \gset
SELECT add_retention_policy('tscheck.forecast_value', drop_after => 38400) \gset
\echo '5 integer hypertable + integer now    OK'

-- All policies registered as background jobs
SELECT count(*) AS jobs FROM timescaledb_information.jobs WHERE hypertable_schema = 'tscheck' \gset
\echo 'background jobs created:' :jobs

-- Clean up; the jobs must disappear with their tables
DROP SCHEMA tscheck CASCADE;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM timescaledb_information.jobs WHERE hypertable_schema = 'tscheck') THEN
        RAISE EXCEPTION 'jobs left behind after drop';
    END IF;
END $$;
\echo 'dropped                               OK'
\echo 'TIMESCALE CHECK OK'
