#!/usr/bin/env bash
# Rollback to previous Docker image.
# Usage: ./scripts/rollback.sh [staging|production]
set -euo pipefail

ENV="${1:-production}"

case "$ENV" in
  staging)
    COMPOSE_FILE="docker-compose.staging.yml"
    ;;
  production)
    COMPOSE_FILE="docker-compose.prod.yml"
    ;;
  *)
    echo "Usage: rollback.sh [staging|production]"
    exit 1
    ;;
esac

echo "Rolling back $ENV to previous image..."

# Swap images
docker tag lap-api_api:previous lap-api_api:latest 2>/dev/null || {
    echo "ERROR: No previous image found. Cannot rollback."
    exit 1
}

# Restart services with previous image
docker compose -f "$COMPOSE_FILE" up -d api celery-pipeline celery-default celery-beat

# Wait and verify
sleep 5
if curl -sf http://localhost:5000/healthz > /dev/null; then
    echo "Rollback successful — $ENV is healthy"
else
    echo "WARNING: Rollback deployed but healthz failed"
    exit 1
fi
