#!/usr/bin/env bash
# =============================================================================
# PostgreSQL backup script with verification, encryption, and retention tiers.
#
# Runs daily via cron or Docker entrypoint.
# Produces: daily (7d), weekly-Sunday (4w), monthly-1st (12m) backups.
#
# Required env vars:
#   TELEMETRY_PG_URL   — PostgreSQL connection string
#   BACKUP_ENCRYPTION_KEY — GPG symmetric passphrase (optional; skips encryption if unset)
#
# Optional env vars:
#   BACKUP_DIR         — Local backup directory (default: /opt/lap-api/backups)
#   S3_BUCKET          — S3-compatible bucket for off-site copies (skips if unset)
#   S3_ENDPOINT        — S3 endpoint URL (for Hetzner Object Storage, etc.)
#   AWS_ACCESS_KEY_ID  — S3 credentials
#   AWS_SECRET_ACCESS_KEY — S3 credentials
# =============================================================================
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/lap-api/backups}"
TIMESTAMP=$(date -u +"%Y-%m-%d_%H%M%S")
DAY_OF_WEEK=$(date -u +"%u")   # 1=Monday .. 7=Sunday
DAY_OF_MONTH=$(date -u +"%d")

# Parse PG connection string for pg_dump
PG_URL="${TELEMETRY_PG_URL:-postgresql://telemetry:telemetry@localhost:5432/telemetry}"

DUMP_FILE="${BACKUP_DIR}/daily/telemetry_${TIMESTAMP}.dump"
LOG_FILE="${BACKUP_DIR}/backup.log"

log() {
    echo "[$(date -u +"%Y-%m-%d %H:%M:%S UTC")] $*" | tee -a "$LOG_FILE"
}

die() {
    log "FATAL: $*"
    exit 1
}

# ---------------------------------------------------------------------------
# 1. Ensure directories exist
# ---------------------------------------------------------------------------
mkdir -p "${BACKUP_DIR}/daily"
mkdir -p "${BACKUP_DIR}/weekly"
mkdir -p "${BACKUP_DIR}/monthly"

log "=== Backup started ==="

# ---------------------------------------------------------------------------
# 2. Create backup
# ---------------------------------------------------------------------------
log "Creating pg_dump → ${DUMP_FILE}"
pg_dump "$PG_URL" --format=custom --compress=6 --file="$DUMP_FILE" \
    || die "pg_dump failed"

DUMP_SIZE=$(stat -c%s "$DUMP_FILE" 2>/dev/null || stat -f%z "$DUMP_FILE" 2>/dev/null)
log "Dump created: $(( DUMP_SIZE / 1024 / 1024 )) MB"

# ---------------------------------------------------------------------------
# 3. Verify backup (pg_restore --list)
# ---------------------------------------------------------------------------
log "Verifying backup integrity..."
pg_restore --list "$DUMP_FILE" > /dev/null 2>&1 \
    || die "Backup verification failed — pg_restore --list returned error"
log "Backup verified: TOC is valid"

# ---------------------------------------------------------------------------
# 4. Encrypt (optional)
# ---------------------------------------------------------------------------
FINAL_FILE="$DUMP_FILE"
if [ -n "${BACKUP_ENCRYPTION_KEY:-}" ]; then
    log "Encrypting backup..."
    gpg --batch --yes --symmetric --cipher-algo AES256 \
        --passphrase "$BACKUP_ENCRYPTION_KEY" \
        --output "${DUMP_FILE}.gpg" "$DUMP_FILE" \
        || die "Encryption failed"
    rm -f "$DUMP_FILE"
    FINAL_FILE="${DUMP_FILE}.gpg"
    log "Encrypted → ${FINAL_FILE}"
else
    log "BACKUP_ENCRYPTION_KEY not set — skipping encryption"
fi

# ---------------------------------------------------------------------------
# 5. Retention tier copies
# ---------------------------------------------------------------------------

# Weekly (Sunday = day 7)
if [ "$DAY_OF_WEEK" = "7" ]; then
    cp "$FINAL_FILE" "${BACKUP_DIR}/weekly/$(basename "$FINAL_FILE")"
    log "Copied to weekly tier"
fi

# Monthly (1st of month)
if [ "$DAY_OF_MONTH" = "01" ]; then
    cp "$FINAL_FILE" "${BACKUP_DIR}/monthly/$(basename "$FINAL_FILE")"
    log "Copied to monthly tier"
fi

# ---------------------------------------------------------------------------
# 6. Off-site copy (S3-compatible)
# ---------------------------------------------------------------------------
if [ -n "${S3_BUCKET:-}" ]; then
    S3_DEST="s3://${S3_BUCKET}/backups/daily/$(basename "$FINAL_FILE")"
    log "Uploading to ${S3_DEST} ..."

    S3_ARGS=""
    if [ -n "${S3_ENDPOINT:-}" ]; then
        S3_ARGS="--endpoint-url ${S3_ENDPOINT}"
    fi

    aws s3 cp "$FINAL_FILE" "$S3_DEST" $S3_ARGS \
        || log "WARNING: S3 upload failed (non-fatal)"

    if [ "$DAY_OF_WEEK" = "7" ]; then
        aws s3 cp "$FINAL_FILE" "s3://${S3_BUCKET}/backups/weekly/$(basename "$FINAL_FILE")" $S3_ARGS 2>/dev/null || true
    fi
    if [ "$DAY_OF_MONTH" = "01" ]; then
        aws s3 cp "$FINAL_FILE" "s3://${S3_BUCKET}/backups/monthly/$(basename "$FINAL_FILE")" $S3_ARGS 2>/dev/null || true
    fi

    log "Off-site upload complete"
else
    log "S3_BUCKET not set — skipping off-site copy"
fi

# ---------------------------------------------------------------------------
# 7. Cleanup old backups (retention)
# ---------------------------------------------------------------------------
log "Cleaning old backups..."

# Daily: keep 7 days
find "${BACKUP_DIR}/daily" -type f -mtime +7 -delete 2>/dev/null && \
    log "Pruned daily backups older than 7 days" || true

# Weekly: keep 4 weeks (28 days)
find "${BACKUP_DIR}/weekly" -type f -mtime +28 -delete 2>/dev/null && \
    log "Pruned weekly backups older than 28 days" || true

# Monthly: keep 12 months (365 days)
find "${BACKUP_DIR}/monthly" -type f -mtime +365 -delete 2>/dev/null && \
    log "Pruned monthly backups older than 365 days" || true

# S3 lifecycle rules handle remote retention (configure in S3 console)

# ---------------------------------------------------------------------------
# 8. Summary
# ---------------------------------------------------------------------------
FINAL_SIZE=$(stat -c%s "$FINAL_FILE" 2>/dev/null || stat -f%z "$FINAL_FILE" 2>/dev/null)
log "=== Backup complete: $(basename "$FINAL_FILE") ($(( FINAL_SIZE / 1024 / 1024 )) MB) ==="
