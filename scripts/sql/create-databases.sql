-- One-time database setup (design/14 §14.1.2 step 3). Run as postgres by scripts/setup-databases.ps1.
-- Safe to run again: existing role and databases are kept, the password is reset to the one in .env.
\set ON_ERROR_STOP on
\getenv ews_password EWS_DB_PASSWORD

SELECT 'CREATE ROLE ews LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ews') \gexec
ALTER ROLE ews PASSWORD :'ews_password';

SELECT format('CREATE DATABASE %I OWNER ews', d)
FROM unnest(ARRAY['ews', 'ews_test', 'ews_demo']) AS d
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = d) \gexec

-- Demo marker (11 §11.3.1, DD95): only ews_demo is a demo database
ALTER DATABASE ews_demo SET ews.is_demo = 'on';

-- TimescaleDB is not a trusted extension, so the extensions are created here as postgres
\c ews
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS citext;
\c ews_test
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS citext;
\c ews_demo
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS citext;
