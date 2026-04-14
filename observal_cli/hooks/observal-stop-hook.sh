#!/usr/bin/env bash
# observal-stop-hook.sh — Claude Code Stop hook that captures assistant
# text responses AND thinking/reasoning from the current turn and sends
# them to Observal.
#
# The hook receives JSON on stdin with session_id, transcript_path, etc.
# It reads the transcript JSONL backwards, collecting each assistant
# message as a separate event with sequence metadata, then POSTs them
# individually to the hooks endpoint. This allows the UI to interleave
# assistant "thinking" text between tool calls.
#
# IMPORTANT: No `set -eu` — we must never exit early and always reach
# the final exit 0 so Claude Code doesn't see a hook failure.

OBSERVAL_HOOKS_URL="${OBSERVAL_HOOKS_URL:-http://localhost:8000/api/v1/otel/hooks}"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"

# Read hook payload from stdin
PAYLOAD=$(cat)

SESSION_ID=$(echo "$PAYLOAD" | jq -r '.session_id // ""' 2>/dev/null)
TRANSCRIPT_PATH=$(echo "$PAYLOAD" | jq -r '.transcript_path // ""' 2>/dev/null)

if [ -z "$SESSION_ID" ] || [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
  exit 0
fi

# Collect assistant messages from the current turn (bottom-up until user msg).
# Each assistant message becomes a separate event with a sequence number.
# We also capture thinking blocks separately.
TMPDIR_WORK=$(mktemp -d)
trap 'rm -rf "$TMPDIR_WORK"' EXIT

MSG_COUNT=0
THINK_COUNT=0

# Use process substitution instead of pipe to avoid subshell variable scoping.
# Write files from within the loop — they persist on disk regardless.
while IFS= read -r line; do
  case "$line" in
    *'"type":"assistant"'*)
      # Extract text blocks
      TEXT=$(echo "$line" | jq -r \
        '[.message.content[]? | select(.type == "text") | .text] | join("\n")' 2>/dev/null || true)
      if [ -n "$TEXT" ]; then
        MSG_COUNT=$((MSG_COUNT + 1))
        printf '%s' "$TEXT" > "$TMPDIR_WORK/msg_$MSG_COUNT"
      fi

      # Extract thinking blocks (reasoning/chain-of-thought)
      THINKING=$(echo "$line" | jq -r \
        '[.message.content[]? | select(.type == "thinking") | .thinking] | join("\n")' 2>/dev/null || true)
      if [ -n "$THINKING" ]; then
        THINK_COUNT=$((THINK_COUNT + 1))
        printf '%s' "$THINKING" > "$TMPDIR_WORK/think_$THINK_COUNT"
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
done < <(tac "$TRANSCRIPT_PATH" 2>/dev/null || true)

# ── Send thinking blocks first (in chronological order) ──
THINK_FILES=$(ls "$TMPDIR_WORK"/think_* 2>/dev/null | sort -t_ -k2 -n -r || true)
if [ -n "$THINK_FILES" ]; then
  THINK_TOTAL=$(echo "$THINK_FILES" | wc -l | tr -d ' ')
  TSEQ=0
  for f in $THINK_FILES; do
    TSEQ=$((TSEQ + 1))
    THINK_TEXT=$(cat "$f")
    # Truncate to 64KB
    THINK_TEXT=$(echo "$THINK_TEXT" | head -c 65536)

    jq -n \
      --arg session_id "$SESSION_ID" \
      --arg response "$THINK_TEXT" \
      --arg seq "$TSEQ" \
      --arg total "$THINK_TOTAL" \
      '{
        hook_event_name: "Stop",
        session_id: $session_id,
        tool_name: "assistant_thinking",
        tool_response: $response,
        message_sequence: ($seq | tonumber),
        message_total: ($total | tonumber)
      }' | curl -s --max-time 5 -X POST "$OBSERVAL_HOOKS_URL" \
        ${OBSERVAL_USER_ID:+-H "X-Observal-User-Id: $OBSERVAL_USER_ID"} \
        -H "Content-Type: application/json" \
        -d @- >/dev/null 2>&1 || true
  done
fi

# ── Send text response blocks (in chronological order) ──
MSG_FILES=$(ls "$TMPDIR_WORK"/msg_* 2>/dev/null | sort -t_ -k2 -n -r || true)
if [ -n "$MSG_FILES" ]; then
  MSG_TOTAL=$(echo "$MSG_FILES" | wc -l | tr -d ' ')
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
      --arg total "$MSG_TOTAL" \
      '{
        hook_event_name: "Stop",
        session_id: $session_id,
        tool_name: "assistant_response",
        tool_response: $response,
        message_sequence: ($seq | tonumber),
        message_total: ($total | tonumber)
      }' | curl -s --max-time 5 -X POST "$OBSERVAL_HOOKS_URL" \
        ${OBSERVAL_USER_ID:+-H "X-Observal-User-Id: $OBSERVAL_USER_ID"} \
        -H "Content-Type: application/json" \
        -d @- >/dev/null 2>&1 || true
  done
fi

# If we didn't find any text or thinking, that's fine — the turn was
# all tool calls.  The generic hook handles the basic hook_stop event.

exit 0
