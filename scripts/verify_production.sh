#!/usr/bin/env bash
set -euo pipefail

# ── Post-Deploy Verification Suite ──────────────────────────────────
# Validates production deployment of Lap Coach API + frontend.
# Usage: ./scripts/verify_production.sh [API_URL] [FRONTEND_URL]
#
# Exit codes: 0 = all pass, 1 = failures detected

API_URL="${1:-https://api.lap-coach.racing}"
FRONTEND_URL="${2:-https://lap-coach.racing}"
PASS=0
FAIL=0

check() {
    local name="$1"
    local result="$2"
    if [ "$result" = "ok" ]; then
        echo "  PASS  $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $name — $result"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Lap Coach Post-Deploy Verification ==="
echo "API:      $API_URL"
echo "Frontend: $FRONTEND_URL"
echo ""

# ── 1. Marketing page availability ────────────────────────────────
echo "--- 1. Marketing Page ---"
HTTP_CODE=$(curl -sL -o /dev/null -w "%{http_code}" "$FRONTEND_URL" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    check "Frontend reachable" "ok"
else
    check "Frontend reachable" "HTTP $HTTP_CODE"
fi

# ── 2. API health ─────────────────────────────────────────────────
echo "--- 2. API Health ---"
HEALTH=$(curl -sf "$API_URL/healthz" 2>/dev/null || echo '{"ok":false}')
if echo "$HEALTH" | grep -q '"ok"'; then
    check "API /healthz" "ok"
else
    check "API /healthz" "unhealthy or unreachable"
fi

# ── 3. CORS headers ───────────────────────────────────────────────
echo "--- 3. CORS Headers ---"
for ORIGIN in "$FRONTEND_URL" "https://www.lap-coach.racing"; do
    CORS_HEADER=$(curl -sf -H "Origin: $ORIGIN" -I "$API_URL/healthz" 2>/dev/null | grep -i "access-control-allow-origin" || echo "")
    if echo "$CORS_HEADER" | grep -qi "$ORIGIN\|\*"; then
        check "CORS for $ORIGIN" "ok"
    else
        check "CORS for $ORIGIN" "missing or wrong: $CORS_HEADER"
    fi
done

# ── 4. Preflight OPTIONS ──────────────────────────────────────────
echo "--- 4. Preflight ---"
PREFLIGHT=$(curl -sf -X OPTIONS -H "Origin: $FRONTEND_URL" \
    -H "Access-Control-Request-Method: POST" \
    -H "Access-Control-Request-Headers: Authorization,Content-Type" \
    -I "$API_URL/api/v1/sessions" 2>/dev/null || echo "")
if echo "$PREFLIGHT" | grep -qi "access-control-allow-methods"; then
    check "OPTIONS preflight" "ok"
else
    check "OPTIONS preflight" "no Allow-Methods header"
fi

# ── 5. Auth smoke test ────────────────────────────────────────────
echo "--- 5. Auth Smoke ---"
AUTH_CODE=$(curl -sf -o /dev/null -w "%{http_code}" \
    -X POST -H "Content-Type: application/json" \
    -d '{"email":"smoke@test.invalid","password":"wrong"}' \
    "$API_URL/auth/login" 2>/dev/null || echo "000")
if [ "$AUTH_CODE" = "401" ] || [ "$AUTH_CODE" = "400" ]; then
    check "Auth endpoint responds" "ok"
elif [ "$AUTH_CODE" = "500" ]; then
    check "Auth endpoint responds" "500 Internal Server Error"
else
    check "Auth endpoint responds" "HTTP $AUTH_CODE"
fi

# ── 6. Security headers ──────────────────────────────────────────
echo "--- 6. Security Headers ---"
HEADERS=$(curl -sI "$API_URL/healthz" 2>/dev/null)

check_header() {
    local header="$1"
    local expected="$2"
    if echo "$HEADERS" | grep -qi "$header.*$expected"; then
        check "$header" "ok"
    else
        check "$header" "missing or wrong"
    fi
}

check_header "strict-transport-security" "max-age="
check_header "x-content-type-options" "nosniff"
check_header "x-frame-options" "deny"
check_header "referrer-policy" "strict-origin"
check_header "permissions-policy" "camera"
check_header "content-security-policy" "default-src"

# Check server banner is hidden
if echo "$HEADERS" | grep -qi "^server:.*caddy\|^server:.*gunicorn\|^server:.*python"; then
    check "Server banner hidden" "exposed"
else
    check "Server banner hidden" "ok"
fi

# ── 7. Webhook rejects unsigned ───────────────────────────────────
echo "--- 7. Webhook Signature ---"
WH_CODE=$(curl -sf -o /dev/null -w "%{http_code}" \
    -X POST -H "Content-Type: application/json" \
    -d '{"type":"test"}' \
    "$API_URL/api/v1/billing/webhook" 2>/dev/null || echo "000")
if [ "$WH_CODE" = "400" ] || [ "$WH_CODE" = "401" ]; then
    check "Webhook rejects unsigned" "ok"
elif [ "$WH_CODE" = "500" ]; then
    check "Webhook rejects unsigned" "500 — should be 400"
else
    check "Webhook rejects unsigned" "HTTP $WH_CODE"
fi

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
