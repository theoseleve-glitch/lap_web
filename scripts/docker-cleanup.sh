#!/usr/bin/env bash
# Weekly Docker cleanup — remove unused images, containers, volumes.
# Run via cron: 0 4 * * 0 /opt/lap-api/scripts/docker-cleanup.sh >> /var/log/docker-cleanup.log 2>&1
set -euo pipefail

echo "=== Docker cleanup $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Remove stopped containers older than 24h
echo "Removing stopped containers..."
docker container prune -f --filter "until=24h" || true

# Remove dangling images (untagged)
echo "Removing dangling images..."
docker image prune -f || true

# Remove images not used in the last 7 days
echo "Removing unused images (>7 days)..."
docker image prune -a -f --filter "until=168h" || true

# Remove unused volumes (not attached to any container)
echo "Removing unused volumes..."
docker volume prune -f || true

# Remove unused build cache older than 7 days
echo "Removing build cache (>7 days)..."
docker builder prune -f --filter "until=168h" || true

# Report disk usage
echo ""
echo "Current Docker disk usage:"
docker system df
echo ""
echo "=== Cleanup complete ==="
