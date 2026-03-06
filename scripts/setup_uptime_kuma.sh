#!/usr/bin/env bash
# =============================================================================
# Uptime Kuma monitor setup via API
#
# Run after Uptime Kuma is deployed (docker-compose.monitoring.yml).
# Requires: UPTIME_KUMA_URL, UPTIME_KUMA_USERNAME, UPTIME_KUMA_PASSWORD
#
# Monitors:
#   1. Frontend root (HTTPS)
#   2. API /healthz (HTTPS)
#   3. API authenticated journey (keyword check)
#   4. API lightweight compute (keyword check)
# =============================================================================
set -euo pipefail

KUMA_URL="${UPTIME_KUMA_URL:-http://localhost:3001}"

echo "=== Uptime Kuma Monitor Setup ==="
echo "URL: ${KUMA_URL}"
echo ""
echo "After Uptime Kuma is running, configure these monitors manually"
echo "via the web UI at ${KUMA_URL}:"
echo ""
echo "1. [HTTP(s)] Frontend Root"
echo "   URL: https://lap-coach.racing"
echo "   Interval: 60s"
echo "   Expected status: 200"
echo ""
echo "2. [HTTP(s)] API Health"
echo "   URL: https://api.lap-coach.racing/healthz"
echo "   Interval: 30s"
echo "   Expected status: 200"
echo "   Keyword: \"ok\""
echo ""
echo "3. [HTTP(s)] API Session List (Auth)"
echo "   URL: https://api.lap-coach.racing/api/v1/sessions"
echo "   Interval: 120s"
echo "   Headers: Authorization: Bearer \${MONITORING_TOKEN}"
echo "   Expected status: 200"
echo "   Keyword: \"ok\""
echo ""
echo "4. [HTTP(s)] API Scores (Compute)"
echo "   URL: https://api.lap-coach.racing/api/v1/sessions/1/scores"
echo "   Interval: 300s"
echo "   Headers: Authorization: Bearer \${MONITORING_TOKEN}"
echo "   Expected status: 200 or 404"
echo ""
echo "5. [HTTP(s)] Grafana Dashboard"
echo "   URL: https://grafana.lap-coach.racing/api/health"
echo "   Interval: 60s"
echo "   Expected status: 200"
echo ""
echo "Alert routing:"
echo "  - Configure Discord/Slack webhook in Uptime Kuma notifications"
echo "  - Set alert after 3 consecutive failures"
echo ""
echo "=== Done ==="
