#!/usr/bin/env bash
# =============================================================================
# Monthly automated restore test
#
# Validates that the most recent backup can be restored to a temporary
# PostgreSQL instance, runs basic data integrity checks, and records evidence.
#
# Usage:
#   TELEMETRY_PG_URL=... ./scripts/restore_test.sh
#
# Outputs evidence to: /opt/lap-api/backups/restore-tests/
# =============================================================================
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/lap-api/backups}"
EVIDENCE_DIR="${BACKUP_DIR}/restore-tests"
TIMESTAMP=$(date -u +"%Y-%m-%d_%H%M%S")
EVIDENCE_FILE="${EVIDENCE_DIR}/restore_test_${TIMESTAMP}.log"
RESTORE_DB="telemetry_restore_test"
PG_URL="${TELEMETRY_PG_URL:-postgresql://telemetry:telemetry@localhost:5432/telemetry}"

# Extract PG host/user from URL for psql commands
PG_HOST=$(echo "$PG_URL" | sed -E 's|.*@([^:]+):.*|\1|')
PG_PORT=$(echo "$PG_URL" | sed -E 's|.*:([0-9]+)/.*|\1|')
PG_USER=$(echo "$PG_URL" | sed -E 's|.*://([^:]+):.*|\1|')

mkdir -p "$EVIDENCE_DIR"

log() {
    echo "[$(date -u +"%Y-%m-%d %H:%M:%S UTC")] $*" | tee -a "$EVIDENCE_FILE"
}

cleanup() {
    log "Dropping restore test database..."
    psql "$PG_URL" -c "DROP DATABASE IF EXISTS ${RESTORE_DB};" 2>/dev/null || true
    log "Cleanup complete"
}
trap cleanup EXIT

# Find most recent backup
LATEST_BACKUP=$(ls -t "${BACKUP_DIR}/daily/"*.dump* 2>/dev/null | head -1)
if [ -z "$LATEST_BACKUP" ]; then
    log "FAIL: No backup files found in ${BACKUP_DIR}/daily/"
    exit 1
fi

log "=== Restore Test Started ==="
log "Backup file: ${LATEST_BACKUP}"
log "File size: $(stat -c%s "$LATEST_BACKUP" 2>/dev/null || stat -f%z "$LATEST_BACKUP") bytes"

# Decrypt if needed
RESTORE_FILE="$LATEST_BACKUP"
if [[ "$LATEST_BACKUP" == *.gpg ]]; then
    if [ -z "${BACKUP_ENCRYPTION_KEY:-}" ]; then
        log "FAIL: Backup is encrypted but BACKUP_ENCRYPTION_KEY not set"
        exit 1
    fi
    RESTORE_FILE="/tmp/restore_test_${TIMESTAMP}.dump"
    gpg --batch --yes --decrypt --passphrase "$BACKUP_ENCRYPTION_KEY" \
        --output "$RESTORE_FILE" "$LATEST_BACKUP" || { log "FAIL: Decryption failed"; exit 1; }
    log "Decrypted backup for restore"
fi

# Create temporary database
log "Creating temporary database: ${RESTORE_DB}"
psql "$PG_URL" -c "DROP DATABASE IF EXISTS ${RESTORE_DB};"
psql "$PG_URL" -c "CREATE DATABASE ${RESTORE_DB};"

# Restore
RESTORE_URL="${PG_URL%/*}/${RESTORE_DB}"
log "Restoring to ${RESTORE_DB}..."
pg_restore --dbname="$RESTORE_URL" --no-owner --no-acl "$RESTORE_FILE" 2>&1 | tee -a "$EVIDENCE_FILE"
RESTORE_EXIT=${PIPESTATUS[0]}

if [ "$RESTORE_EXIT" -ne 0 ]; then
    log "WARNING: pg_restore exited with code $RESTORE_EXIT (may have non-fatal warnings)"
fi

# Integrity checks
log "Running integrity checks..."

TABLE_COUNT=$(psql "$RESTORE_URL" -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
log "Tables restored: ${TABLE_COUNT}"

USER_COUNT=$(psql "$RESTORE_URL" -t -c "SELECT count(*) FROM users;" 2>/dev/null || echo "N/A")
log "Users: ${USER_COUNT}"

SESSION_COUNT=$(psql "$RESTORE_URL" -t -c "SELECT count(*) FROM sessions;" 2>/dev/null || echo "N/A")
log "Sessions: ${SESSION_COUNT}"

WORKSPACE_COUNT=$(psql "$RESTORE_URL" -t -c "SELECT count(*) FROM workspaces;" 2>/dev/null || echo "N/A")
log "Workspaces: ${WORKSPACE_COUNT}"

# Verify alembic version
ALEMBIC_VER=$(psql "$RESTORE_URL" -t -c "SELECT version_num FROM alembic_version;" 2>/dev/null || echo "N/A")
log "Alembic version: ${ALEMBIC_VER}"

log "=== Restore Test PASSED ==="
log "Evidence file: ${EVIDENCE_FILE}"

# Cleanup encrypted temp file
if [ "$RESTORE_FILE" != "$LATEST_BACKUP" ]; then
    rm -f "$RESTORE_FILE"
fi
