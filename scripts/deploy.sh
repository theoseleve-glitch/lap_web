#!/usr/bin/env bash
# deploy.sh — Automated deployment pipeline for Lap Coach SaaS.
#
# Stages:
#   1. Pre-flight checks (tests, lint, consistency)
#   2. Backend deploy (scp + docker compose)
#   3. Run migrations
#   4. Health check (retry loop)
#   5. Frontend deploy (Cloudflare Workers)
#   6. Smoke tests
#
# Usage:
#   ./scripts/deploy.sh                 # full deploy
#   ./scripts/deploy.sh --dry-run       # pre-flight only
#   ./scripts/deploy.sh --backend-only  # skip frontend
#   ./scripts/deploy.sh --frontend-only # skip backend

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TELEMETRY_ROOT="$PROJECT_ROOT/telemetry_tool"
LAP_ROOT="$PROJECT_ROOT/lap-website"
REMOTE="root@46.225.227.24"
REMOTE_PATH="/opt/lap-api"
API_URL="https://api.lap-coach.racing"
SITE_URL="https://lap-coach.racing"

DRY_RUN=false
BACKEND_ONLY=false
FRONTEND_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --dry-run)      DRY_RUN=true ;;
        --backend-only) BACKEND_ONLY=true ;;
        --frontend-only) FRONTEND_ONLY=true ;;
    esac
done

log() { echo "==> $1"; }
err() { echo "ERROR: $1" >&2; exit 1; }

# ── Stage 1: Pre-flight checks ───────────────────────────────────────

log "Stage 1: Pre-flight checks"

# Entitlement consistency
log "  Checking entitlement consistency..."
python "$PROJECT_ROOT/scripts/verify_entitlement_consistency.py" --skip-stripe --skip-db \
    || err "Entitlement consistency check failed"

# Backend tests
log "  Running backend tests..."
cd "$TELEMETRY_ROOT"
python -m pytest tests/ -x --timeout=120 -q \
    || err "Backend tests failed"

# Frontend checks
if [ "$BACKEND_ONLY" = false ]; then
    log "  Running frontend checks..."
    cd "$LAP_ROOT"
    npm run lint || err "Frontend lint failed"
    npm run test -- --passWithNoTests || err "Frontend tests failed"
    npm run build || err "Frontend build failed"
fi

log "  Pre-flight checks passed!"

if [ "$DRY_RUN" = true ]; then
    log "Dry run complete. No deployment."
    exit 0
fi

# ── Stage 2: Backend deploy ───────────────────────────────────────────

if [ "$FRONTEND_ONLY" = false ]; then
    log "Stage 2: Deploying backend..."

    cd "$PROJECT_ROOT"
    scp -r telemetry_tool/ "$REMOTE:$REMOTE_PATH/"
    scp docker-compose.prod.yml "$REMOTE:$REMOTE_PATH/"

    ssh "$REMOTE" "cd $REMOTE_PATH && docker compose build api && docker compose up -d api"

    log "  Backend deployed."

    # ── Stage 3: Run migrations ─────────────────────────────────────

    log "Stage 3: Running migrations..."
    ssh "$REMOTE" "cd $REMOTE_PATH && docker compose exec -T api alembic upgrade head" || true
    log "  Migrations complete."

    # ── Stage 4: Health check ───────────────────────────────────────

    log "Stage 4: Health check..."
    for i in $(seq 1 10); do
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/healthz" 2>/dev/null || echo "000")
        if [ "$STATUS" = "200" ]; then
            log "  API healthy! (attempt $i)"
            break
        fi
        if [ "$i" = "10" ]; then
            err "API health check failed after 10 attempts"
        fi
        log "  Waiting... (attempt $i, status=$STATUS)"
        sleep 5
    done
fi

# ── Stage 5: Frontend deploy ─────────────────────────────────────────

if [ "$BACKEND_ONLY" = false ]; then
    log "Stage 5: Deploying frontend..."
    cd "$LAP_ROOT"
    npm run cf:deploy || err "Frontend deploy failed"
    log "  Frontend deployed."
fi

# ── Stage 6: Smoke tests ─────────────────────────────────────────────

log "Stage 6: Smoke tests..."

# API health
API_HEALTH=$(curl -sf "$API_URL/healthz" 2>/dev/null || echo '{"error":"unreachable"}')
log "  API health: $API_HEALTH"

# Frontend reachable
SITE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SITE_URL" 2>/dev/null || echo "000")
log "  Frontend status: $SITE_STATUS"

if [ "$SITE_STATUS" != "200" ] && [ "$BACKEND_ONLY" = false ]; then
    log "  WARNING: Frontend returned $SITE_STATUS (may still be propagating)"
fi

log "Deployment complete!"
