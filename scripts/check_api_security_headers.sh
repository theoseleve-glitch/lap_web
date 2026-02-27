#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <api-base-url> [path]" >&2
  exit 64
fi

api_base_url="${1%/}"
path="${2:-/healthz}"
url="${api_base_url}${path}"

headers="$(curl --silent --show-error --location --head "$url")"
headers_lc="$(printf '%s\n' "$headers" | tr '[:upper:]' '[:lower:]')"

assert_contains() {
  local needle="$1"
  local message="$2"
  if ! grep -Fq "$needle" <<<"$headers_lc"; then
    echo "[FAIL] $message" >&2
    echo "Expected to find: $needle" >&2
    echo "--- Response headers ---" >&2
    printf '%s\n' "$headers" >&2
    exit 1
  fi
  echo "[PASS] $message"
}

assert_not_contains() {
  local needle="$1"
  local message="$2"
  if grep -Fq "$needle" <<<"$headers_lc"; then
    echo "[FAIL] $message" >&2
    echo "Unexpected header fragment found: $needle" >&2
    echo "--- Response headers ---" >&2
    printf '%s\n' "$headers" >&2
    exit 1
  fi
  echo "[PASS] $message"
}

assert_contains "strict-transport-security: max-age=31536000; includesubdomains" "HSTS is present"
assert_contains "x-content-type-options: nosniff" "X-Content-Type-Options is present"
assert_contains "x-frame-options: deny" "X-Frame-Options is present"
assert_contains "referrer-policy: strict-origin-when-cross-origin" "Referrer-Policy matches frontend"
assert_contains "permissions-policy: camera=(), microphone=(), geolocation=()" "Permissions-Policy is locked down"
assert_contains "content-security-policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'" "API CSP enforces JSON-only posture"
assert_not_contains "server:" "Server banner is hidden"

echo "Security header regression check passed for $url"
