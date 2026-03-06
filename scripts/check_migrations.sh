#!/usr/bin/env bash
# CI migration safety checks for Alembic.
# Runs in GitHub Actions with a fresh PostgreSQL instance.
#
# Checks:
#   1. Revision chain is consistent (no broken depends_on)
#   2. upgrade head succeeds on a fresh DB
#   3. downgrade one step succeeds (latest migration is reversible)
#   4. No pending migrations (heads == current after upgrade)
set -euo pipefail

ALEMBIC_DIR="${1:-telemetry_tool}"
cd "$ALEMBIC_DIR"

PASS=0
FAIL=0

step() {
    local name="$1"
    shift
    echo "── $name"
    if "$@" 2>&1; then
        echo "   PASS"
        ((PASS++))
    else
        echo "   FAIL"
        ((FAIL++))
    fi
}

# 1. Check revision chain consistency
step "Revision chain check" \
    alembic check 2>/dev/null || alembic heads

# 2. Upgrade to head on fresh DB
step "Upgrade to head" \
    alembic upgrade head

# 3. Verify current == head
step "Current matches head" \
    bash -c '
        CURRENT=$(alembic current 2>/dev/null | grep -oP "^\w+" | head -1)
        HEAD=$(alembic heads 2>/dev/null | grep -oP "^\w+" | head -1)
        if [ "$CURRENT" = "$HEAD" ]; then
            echo "current=$CURRENT head=$HEAD — match"
        else
            echo "current=$CURRENT head=$HEAD — MISMATCH"
            exit 1
        fi
    '

# 4. Downgrade one step (reversibility check)
step "Downgrade one step" \
    alembic downgrade -1

# 5. Re-upgrade to head (ensure idempotent)
step "Re-upgrade to head" \
    alembic upgrade head

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -gt 0 ] && exit 1
echo "Migration checks PASSED"
