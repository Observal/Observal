#!/usr/bin/env bash
# observal-stop-hook.sh — Claude Code Stop hook that captures assistant
# text responses from the current turn and sends them to Observal.
#
# The hook receives JSON on stdin with session_id, transcript_path, etc.
# It reads the transcript JSONL backwards, collecting each assistant
# message as a separate event with sequence metadata, then POSTs them
# individually to the hooks endpoint. This allows the UI to interleave
# assistant "thinking" text between tool calls.

set -eu
# NOTE: no pipefail — tac|while causes SIGPIPE when while breaks early

OBSERVAL_HOOKS_URL="${OBSERVAL_HOOKS_URL:-http://localhost:8000/api/v1/otel/hooks}"

# Read hook payload from stdin
PAYLOAD=$(cat)

SESSION_ID=$(echo "$PAYLOAD" | jq -r '.session_id // ""')
TRANSCRIPT_PATH=$(echo "$PAYLOAD" | jq -r '.transcript_path // ""')

if [ -z "$SESSION_ID" ] || [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
  exit 0
fi

# Collect assistant messages from the current turn (bottom-up until user msg).
# Each assistant message becomes a separate event with a sequence number.
TMPDIR_WORK=$(mktemp -d)
trap 'rm -rf "$TMPDIR_WORK"' EXIT

MSG_COUNT=0

(tac "$TRANSCRIPT_PATH" || true) | while IFS= read -r line; do
  case "$line" in
    *'"type":"assistant"'*)
      TEXT=$(echo "$line" | jq -r \
        '[.message.content[]? | select(.type == "text") | .text] | join("\n")' 2>/dev/null)
      if [ -n "$TEXT" ]; then
        MSG_COUNT=$((MSG_COUNT + 1))
        printf '%s' "$TEXT" > "$TMPDIR_WORK/msg_$MSG_COUNT"
      fi
      ;;
    *'"type":"user"'*|*'"type":"human"'*)
      # Hit a user message — this is the turn boundary, stop collecting
      break
      ;;
    *)
      # Skip system/tool_result/other non-assistant lines
      continue
      ;;
  esac
done

# Check if we collected anything
MSG_FILES=$(ls "$TMPDIR_WORK"/msg_* 2>/dev/null | sort -t_ -k2 -n -r || true)
if [ -z "$MSG_FILES" ]; then
  exit 0
fi

# Count total messages
TOTAL=$(echo "$MSG_FILES" | wc -l | tr -d ' ')

# Send each message as a separate event (in chronological order — reverse of collection)
SEQ=0
for f in $MSG_FILES; do
  SEQ=$((SEQ + 1))
  MSG_TEXT=$(cat "$f")

  # Truncate to 64KB
  MSG_TEXT=$(echo "$MSG_TEXT" | head -c 65536)

  jq -n \
    --arg session_id "$SESSION_ID" \
    --arg response "$MSG_TEXT" \
    --arg seq "$SEQ" \
    --arg total "$TOTAL" \
    '{
      hook_event_name: "Stop",
      session_id: $session_id,
      tool_name: "assistant_response",
      tool_response: $response,
      message_sequence: ($seq | tonumber),
      message_total: ($total | tonumber)
    }' | curl -s --max-time 5 -X POST "$OBSERVAL_HOOKS_URL" \
      -H "Content-Type: application/json" \
      -d @- >/dev/null 2>&1
done

exit 0
