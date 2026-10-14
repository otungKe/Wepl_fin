-- The database roles (ADR-0027). Run once per database server, and again
-- after creating a database, as the database administrator:
--
--   psql -v db=wepl -f scripts/database_roles.sql
--
-- wepl_owner    owns the schema and runs migrations. Its credentials stay
--               with WEPL operations, never on the application servers.
-- wepl_runtime  holds what the application may do (granted by the tenancy
--               migration 0003). It cannot log in.
-- wepl_app      the application's login. A member of wepl_runtime; owns
--               nothing.
--
-- None is a superuser or BYPASSRLS, so row-level security binds all three
-- (ADR-0009). Set passwords separately, e.g. ALTER ROLE wepl_owner PASSWORD '…'.
-- Safe to run again: it creates only what is missing.
\set ON_ERROR_STOP on

SELECT 'CREATE ROLE wepl_owner LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'wepl_owner') \gexec
SELECT 'CREATE ROLE wepl_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'wepl_runtime') \gexec
SELECT 'CREATE ROLE wepl_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'wepl_app') \gexec

-- Before ADR-0027 the application's login created databases and owned them.
ALTER ROLE wepl_app NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
GRANT wepl_runtime TO wepl_app;
SELECT 'REVOKE wepl_owner FROM wepl_app' WHERE pg_has_role('wepl_app', 'wepl_owner', 'MEMBER') \gexec

SELECT format('CREATE DATABASE %I OWNER wepl_owner', :'db')
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db') \gexec
ALTER DATABASE :"db" OWNER TO wepl_owner;

\connect :"db"
-- A database migrated before ADR-0027 belongs to wepl_app: hand every object
-- in it to the owner. The next migrate then grants wepl_runtime its share.
REASSIGN OWNED BY wepl_app TO wepl_owner;
