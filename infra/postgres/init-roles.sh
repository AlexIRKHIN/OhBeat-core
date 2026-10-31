#!/bin/sh
# Runs once, when the PostgreSQL data volume is created.
# Creates the database and three roles (ASSUMPTION: GAP-5):
#   DB_OWNER_USER - owns the schema, runs migrations and seeds;
#   ohbeat_app    - NOLOGIN role from schema.sql, all table privileges are granted to it;
#   DB_APP_USER   - login user of Core API, member of ohbeat_app.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
    CREATE ROLE ${DB_OWNER_USER} LOGIN PASSWORD '${DB_OWNER_PASSWORD}' CREATEDB;
    CREATE ROLE ohbeat_app NOLOGIN;
    CREATE ROLE ${DB_APP_USER} LOGIN PASSWORD '${DB_APP_PASSWORD}' IN ROLE ohbeat_app;
    CREATE DATABASE ${DB_NAME} OWNER ${DB_OWNER_USER};
SQL
