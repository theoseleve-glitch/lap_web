#!/bin/bash
# Daily retention cleanup — removes raw upload files for demo-tier sessions
# older than 30 days. Runs inside the API container so it has the volume
# mounted and DB access.
#
# Cron: 0 3 * * * /opt/lap-api/scripts/retention_cleanup.sh
#
# Copies the Python script into the container on each run (survives
# container rebuilds). The container doesn't bundle this script in the
# image intentionally — cleanup logic lives in /opt/lap-api/scripts/ on
# the host so it can be updated without a rebuild.

set -euo pipefail

cd /opt/lap-api

# Copy script into container (no-op if already there and unchanged)
docker cp scripts/retention_cleanup.py lap-api-api-1:/opt/retention_cleanup.py

# Run it
docker compose -f docker-compose.prod.yml exec -T -u root api \
  python /opt/retention_cleanup.py 2>&1
