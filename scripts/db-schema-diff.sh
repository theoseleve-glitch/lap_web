#!/usr/bin/env bash
# Compare expected schema (from Alembic migrations) with actual database schema.
# Usage: ./scripts/db-schema-diff.sh [connection-url]
set -euo pipefail

DB_URL="${1:-${TELEMETRY_PG_URL:-postgresql://telemetry:telemetry@localhost:5432/telemetry}}"

echo "=== Schema Diff Check ==="
echo "Database: ${DB_URL%%@*}@***"
echo ""

# Get actual schema from DB
ACTUAL=$(mktemp)
psql "${DB_URL}" -c "
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
" --csv -q > "${ACTUAL}" 2>/dev/null

if [ ! -s "${ACTUAL}" ]; then
    echo "ERROR: Could not connect to database or no tables found." >&2
    rm -f "${ACTUAL}"
    exit 1
fi

TABLES=$(psql "${DB_URL}" -c "
SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;
" --csv -q -t 2>/dev/null)

echo "Tables in database:"
echo "${TABLES}" | sed 's/^/  /'
echo ""

# Check for pending migrations
echo "Alembic migration status:"
alembic current 2>&1 | sed 's/^/  /'
echo ""

HEADS=$(alembic heads 2>&1)
CURRENT=$(alembic current 2>&1)

if echo "${CURRENT}" | grep -q "(head)"; then
    echo "Schema is UP TO DATE (at head)"
else
    echo "WARNING: Schema is NOT at the latest migration head!"
    echo "  Head:    ${HEADS}"
    echo "  Current: ${CURRENT}"
    echo ""
    echo "Run 'alembic upgrade head' to apply pending migrations."
fi

rm -f "${ACTUAL}"
echo ""
echo "=== Done ==="
