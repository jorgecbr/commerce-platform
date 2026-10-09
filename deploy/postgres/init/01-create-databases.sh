#!/usr/bin/env bash
#
# Runs once, when the postgres container initialises its data directory.
#
# Each service owns its database. inventory-service never reads the orders
# tables: the two agree on Kafka events, which is the only contract between
# them. Sharing one database would make that boundary a convention rather
# than a guarantee.
#
# A third database exists for the test suite, so integration tests can create
# and drop schema without touching development data.
#
# `orders` is created by the entrypoint from POSTGRES_DB, so it is not listed
# here. Each database is created only if it is missing, which keeps the script
# safe to re-run against an existing volume.

set -euo pipefail

for database in inventory orders_test; do
    if psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        --tuples-only --no-align --command "SELECT 1 FROM pg_database WHERE datname = '${database}'" \
        | grep -q 1
    then
        echo "Database ${database} already exists, skipping."
    else
        echo "Creating database ${database}."
        createdb --username "$POSTGRES_USER" --owner "$POSTGRES_USER" "$database"
    fi
done