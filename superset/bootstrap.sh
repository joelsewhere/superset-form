#!/bin/bash
# One-shot initialisation for Superset. Safe to re-run: every step is
# idempotent, so `docker compose up` on an existing volume is a no-op.
set -euo pipefail

echo "==> Upgrading Superset metadata database"
superset db upgrade

echo "==> Creating admin user (ignored if it already exists)"
superset fab create-admin \
    --username "${SUPERSET_ADMIN_USERNAME}" \
    --firstname Admin \
    --lastname User \
    --email "${SUPERSET_ADMIN_EMAIL}" \
    --password "${SUPERSET_ADMIN_PASSWORD}" || true

echo "==> Initialising roles and permissions"
superset init

echo "==> Registering the application database connection"
# Superset reads application data through a SELECT-only role. Re-running
# this updates the existing connection rather than creating a duplicate.
superset set-database-uri \
    --database_name "FrontFlow" \
    --uri "${APP_DB_URI}" || \
    echo "    (set-database-uri unavailable in this version; add the connection via the UI)"

echo "==> Superset bootstrap complete"
