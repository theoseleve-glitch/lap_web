#!/usr/bin/env bash
# Safe database migration rollback with verification.
# Usage: ./scripts/db-rollback.sh [steps]
#   steps: number of migrations to roll back (default: 1)
set -euo pipefail

STEPS="${1:-1}"

echo "=== Database Migration Rollback ==="
echo "Rolling back ${STEPS} migration(s)"
echo ""

# Show current state
echo "Current migration:"
alembic current 2>&1 || { echo "ERROR: Cannot determine current migration. Is the DB reachable?" >&2; exit 1; }
echo ""

# Show what will be rolled back
echo "Migration history (recent ${STEPS}):"
alembic history --verbose -r "-${STEPS}:current" 2>&1 || true
echo ""

# Safety check
read -p "Proceed with rollback? (y/N): " CONFIRM
if [[ "${CONFIRM}" != "y" && "${CONFIRM}" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

# Perform rollback
echo ""
echo "Rolling back..."
alembic downgrade "-${STEPS}"

echo ""
echo "New current migration:"
alembic current

echo ""
echo "=== Rollback complete ==="
echo "Verify the application works correctly before deploying."
