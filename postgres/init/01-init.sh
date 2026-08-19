#!/bin/bash
# Runs once, on first initialisation of the Postgres data volume.
# Creates the Superset metadata DB, the application DB, and the read-only
# role Superset uses to query application data.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
    CREATE DATABASE ${POSTGRES_SUPERSET_DB};
    CREATE DATABASE ${POSTGRES_APP_DB};
    CREATE ROLE ${SUPERSET_RO_USER} WITH LOGIN PASSWORD '${SUPERSET_RO_PASSWORD}';
SQL

# Superset may read the application DB, but must never write to it.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_APP_DB" <<-SQL
    GRANT CONNECT ON DATABASE ${POSTGRES_APP_DB} TO ${SUPERSET_RO_USER};
    GRANT USAGE ON SCHEMA public TO ${SUPERSET_RO_USER};
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${SUPERSET_RO_USER};
    -- Tables created later (by Alembic) must also be readable.
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT ON TABLES TO ${SUPERSET_RO_USER};
SQL

echo "init: created ${POSTGRES_SUPERSET_DB}, ${POSTGRES_APP_DB}, role ${SUPERSET_RO_USER}"
