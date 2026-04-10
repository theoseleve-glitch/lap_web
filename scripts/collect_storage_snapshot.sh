#!/bin/bash
# Collect storage snapshot via the admin API.
# Run via cron on the VPS: 0 */6 * * * /opt/lap-api/scripts/collect_storage_snapshot.sh
#
# Calls GET /admin/infra/storage?snapshot=1 which saves metrics to
# system_metrics_snapshots for historical trend analysis.

set -euo pipefail

API="http://localhost:8000"
EMAIL="${ADMIN_EMAIL:-theos.eleve@gmail.com}"
PASSWORD="${ADMIN_PASSWORD:-LapAdmin2026!}"

# Login
TOKEN=$(curl -sf -X POST "$API/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['access_token'])")

if [ -z "$TOKEN" ]; then
  echo "$(date -u +%FT%TZ) ERROR: login failed" >&2
  exit 1
fi

# Collect + save snapshot
RESULT=$(curl -sf "$API/api/v1/admin/infra/storage?snapshot=1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Workspace-Id: 65")

echo "$(date -u +%FT%TZ) OK: snapshot saved"
