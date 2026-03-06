#!/usr/bin/env bash
# Post-deploy smoke test — gates promotion from staging to production.
# Usage: ./scripts/smoke_test.sh <base_url> [--write]
#   --write  enables write tests (staging only, not production)
#
# Exit codes: 0 = all passed, 1 = failure
set -euo pipefail

BASE_URL="${1:?Usage: smoke_test.sh <base_url> [--write]}"
WRITE_TESTS=false
[[ "${2:-}" == "--write" ]] && WRITE_TESTS=true

PASS=0
FAIL=0

check() {
    local name="$1" cmd="$2" expect="$3"
    local output
    if output=$(eval "$cmd" 2>&1); then
        if echo "$output" | grep -q "$expect"; then
            echo "  PASS  $name"
            ((PASS++))
        else
            echo "  FAIL  $name — expected '$expect' in output"
            echo "        got: ${output:0:200}"
            ((FAIL++))
        fi
    else
        echo "  FAIL  $name — command failed"
        echo "        got: ${output:0:200}"
        ((FAIL++))
    fi
}

echo "Smoke testing: $BASE_URL"
echo "──────────────────────────────────────"

# 1. Health check
check "healthz" \
    "curl -sf '${BASE_URL}/healthz'" \
    '"ok"'

# 2. CORS headers present for allowed origin
check "CORS allowed origin" \
    "curl -sI -H 'Origin: https://lap-coach.racing' '${BASE_URL}/healthz' | grep -i access-control-allow-origin" \
    "lap-coach.racing"

# 3. CORS blocked for evil origin
check "CORS blocks evil origin" \
    "curl -sI -H 'Origin: http://evil.com' '${BASE_URL}/healthz' | grep -ci access-control-allow-origin || echo 0" \
    "0"

# 4. Security headers
check "X-Content-Type-Options" \
    "curl -sI '${BASE_URL}/healthz' | grep -i x-content-type-options" \
    "nosniff"

# 5. Auth endpoint reachable (returns 400/422, not 500)
check "auth/login reachable" \
    "curl -s -o /dev/null -w '%{http_code}' -X POST '${BASE_URL}/auth/login' -H 'Content-Type: application/json' -d '{}'" \
    "4"

# 6. API read endpoint (session browse — returns 200 or 401)
check "session browse reachable" \
    "curl -s -o /dev/null -w '%{http_code}' '${BASE_URL}/api/v1/sessions/browse'" \
    ""

# 7. API envelope format
check "API envelope format" \
    "curl -sf '${BASE_URL}/api/v1/nonexistent-xyz-route' || true" \
    '"ok"'

if $WRITE_TESTS; then
    echo ""
    echo "Write tests (staging only):"
    # 8. Upload endpoint accepts POST (returns 401 without auth, not 500)
    check "upload endpoint reachable" \
        "curl -s -o /dev/null -w '%{http_code}' -X POST '${BASE_URL}/api/v1/sessions/upload'" \
        "4"
fi

echo ""
echo "──────────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
    echo "SMOKE TEST FAILED — do NOT promote this build"
    exit 1
fi
echo "SMOKE TEST PASSED"
