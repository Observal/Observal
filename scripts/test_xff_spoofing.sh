#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Yash Gadgil <yashgadgil08@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

# SEC-003 integration test: verify that X-Forwarded-For spoofing
# cannot bypass rate limiting.
#
# Run against a live docker-compose stack:
#   docker compose -f docker/docker-compose.yml up -d
#   bash scripts/test_xff_spoofing.sh
#
# Before the fix (--forwarded-allow-ips "*"):
#   All requests return 401 — rate limit bypassed via XFF rotation.
#
# After the fix (--proxy-headers removed, TrustedProxyMiddleware added):
#   Requests 6+ return 429 — rate limiter sees the real IP regardless of XFF.

set -euo pipefail

BASE_URL="${1:-http://localhost}"
ENDPOINT="$BASE_URL/api/v1/auth/login"
RATE_LIMIT=5        # the login endpoint allows 5/minute
TOTAL_REQUESTS=8    # send more than the limit to trigger 429

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # no color

echo ""
echo "======================================"
echo " SEC-003: XFF Spoofing Rate Limit Test"
echo "======================================"
echo ""
echo "Target:   $ENDPOINT"
echo "Limit:    $RATE_LIMIT/minute"
echo "Requests: $TOTAL_REQUESTS (with rotating X-Forwarded-For)"
echo ""

# Check that the endpoint is reachable (/health is exposed through nginx;
# /readyz is only available in the dev nginx config).
if ! curl -sf -o /dev/null "$BASE_URL/health" 2>/dev/null; then
    echo -e "${RED}ERROR: Server not reachable at $BASE_URL${NC}"
    echo "Start the stack first: docker compose -f docker/docker-compose.yml up -d"
    exit 1
fi

# Send requests with a different spoofed XFF on each one.
# If the rate limiter is fooled, every request gets a unique "client IP"
# and none of them hit the 5/minute cap.
got_429=false
results=()

for i in $(seq 1 "$TOTAL_REQUESTS"); do
    code=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "$ENDPOINT" \
        -H "Content-Type: application/json" \
        -H "X-Forwarded-For: 99.99.99.$i" \
        -d '{"email":"xff-test@example.com","password":"wrong"}')
    results+=("$code")
    if [ "$code" = "429" ]; then
        got_429=true
    fi
    echo "  Request $i  →  HTTP $code  (XFF: 99.99.99.$i)"
done

echo ""
echo "--------------------------------------"

if $got_429; then
    echo -e "${GREEN}PASS${NC}: Rate limiter returned 429 despite XFF rotation."
    echo "XFF spoofing does NOT bypass rate limiting."
    exit 0
else
    echo -e "${RED}FAIL${NC}: All $TOTAL_REQUESTS requests returned without rate limiting."
    echo "XFF spoofing bypasses the rate limiter — the attacker can rotate"
    echo "X-Forwarded-For to get unlimited login attempts."
    exit 1
fi
