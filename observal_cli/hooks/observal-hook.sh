#!/usr/bin/env bash
# observal-hook.sh — Generic Claude Code hook that forwards the JSON
# payload from stdin to the Observal hooks endpoint.
#
# Silently swallows failures (ECONNREFUSED, timeouts) so that Claude
# Code sessions are never disrupted when the Observal server is offline.

OBSERVAL_HOOKS_URL="${OBSERVAL_HOOKS_URL:-http://localhost:8000/api/v1/otel/hooks}"

curl -sf --max-time 5 -X POST "$OBSERVAL_HOOKS_URL" \
  ${OBSERVAL_USER_ID:+-H "X-Observal-User-Id: $OBSERVAL_USER_ID"} \
  -H "Content-Type: application/json" \
  -d @- >/dev/null 2>&1 || true
