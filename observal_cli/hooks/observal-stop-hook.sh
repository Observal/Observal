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

_py=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

if [ -z "$OBSERVAL_HOOKS_URL" ]; then
  _cfg="$HOME/.observal/config.json"
  if [ -f "$_cfg" ]; then
    _srv=$($_py -c "import json,sys;print(json.load(open('$_cfg')).get('server_url',''))" 2>/dev/null || true)
    if [ -n "$_srv" ]; then
      OBSERVAL_HOOKS_URL="${_srv%/}/api/v1/telemetry/hooks"
    fi
  fi
  if [ -z "$OBSERVAL_HOOKS_URL" ]; then
    echo '{"continue":true}'
    exit 0
  fi
fi
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"

# Parse --agent-name from arguments (set by per-agent frontmatter hooks)
_agent_name=""
while [ $# -gt 0 ]; do
  case "$1" in
    --agent-name) _agent_name="$2"; shift 2 ;;
    *) shift ;;
  esac
done
_effective_agent="${_agent_name:-$OBSERVAL_AGENT_NAME}"

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
FOUND_ASSISTANT=0

# Use process substitution instead of pipe to avoid subshell variable scoping.
# Write files from within the loop — they persist on disk regardless.
# Transcript ends with metadata/attachment entries after the last user message,
# so we skip user messages until we've seen at least one assistant message.
while IFS= read -r line; do
  case "$line" in
    *'"type":"assistant"'*)
      FOUND_ASSISTANT=1
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
      # Only break after we've collected at least one assistant message.
      # Trailing metadata/attachments appear after the last user prompt,
      # so we must skip past them to reach the assistant turn.
      [ "$FOUND_ASSISTANT" = "1" ] && break
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
      --arg agent_name "${_effective_agent:-}" \
      '{
        hook_event_name: "Stop",
        session_id: $session_id,
        tool_name: "assistant_thinking",
        tool_response: $response,
        message_sequence: ($seq | tonumber),
        message_total: ($total | tonumber)
      } + (if $agent_name != "" then {agent_name: $agent_name} else {} end)' | curl -s --max-time 5 -X POST "$OBSERVAL_HOOKS_URL" \
        ${OBSERVAL_USER_ID:+-H "X-Observal-User-Id: $OBSERVAL_USER_ID"} \
        ${OBSERVAL_USERNAME:+-H "X-Observal-Username: $OBSERVAL_USERNAME"} \
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
      --arg agent_name "${_effective_agent:-}" \
      '{
        hook_event_name: "Stop",
        session_id: $session_id,
        tool_name: "assistant_response",
        tool_response: $response,
        message_sequence: ($seq | tonumber),
        message_total: ($total | tonumber)
      } + (if $agent_name != "" then {agent_name: $agent_name} else {} end)' | curl -s --max-time 5 -X POST "$OBSERVAL_HOOKS_URL" \
        ${OBSERVAL_USER_ID:+-H "X-Observal-User-Id: $OBSERVAL_USER_ID"} \
        ${OBSERVAL_USERNAME:+-H "X-Observal-Username: $OBSERVAL_USERNAME"} \
        -H "Content-Type: application/json" \
        -d @- >/dev/null 2>&1 || true
  done
fi

# If we didn't find any text or thinking, that's fine — the turn was
# all tool calls.  The generic hook handles the basic hook_stop event.

# ── Optional: Session Reconciliation ──
# If OBSERVAL_RECONCILE=1, parse the full session JSONL and send enrichment
# data (per-turn tokens, model info, cost) to the server. This runs in
# the background to avoid delaying the hook.
if [ "${OBSERVAL_RECONCILE:-0}" = "1" ] && [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
  _RECONCILE_URL="${OBSERVAL_HOOKS_URL%/hooks}/reconcile"

  # Run in background subshell so it doesn't block
  (
    $_py -c "
import json, sys

lines = open('$TRANSCRIPT_PATH', encoding='utf-8', errors='replace').readlines()
session_id = '$SESSION_ID'

enrichment = {
    'session_id': session_id,
    'total_input_tokens': 0,
    'total_output_tokens': 0,
    'total_cache_read_tokens': 0,
    'total_cache_creation_tokens': 0,
    'models_used': [],
    'primary_model': None,
    'total_cost_usd': 0.0,
    'service_tier': None,
    'conversation_turns': 0,
    'tool_use_count': 0,
    'thinking_turns': 0,
    'stop_reasons': {},
    'completeness_score': 1.0,
    'per_turn': [],
}

models_seen = set()
turn_index = 0

for line in lines:
    line = line.strip()
    if not line:
        continue
    try:
        record = json.loads(line)
    except:
        continue
    if record.get('type') != 'assistant':
        continue

    turn_index += 1
    usage = record.get('usage', {})
    message = record.get('message', {})
    content = message.get('content', [])

    model = record.get('model') or message.get('model')
    stop_reason = record.get('stop_reason') or message.get('stop_reason')
    input_t = usage.get('input_tokens', 0)
    output_t = usage.get('output_tokens', 0)
    cache_read = usage.get('cache_read_input_tokens', 0)
    cache_creation = usage.get('cache_creation_input_tokens', 0)

    has_thinking = False
    tool_uses = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                if block.get('type') == 'thinking':
                    has_thinking = True
                elif block.get('type') == 'tool_use':
                    tool_uses.append(block.get('name', 'unknown'))

    enrichment['total_input_tokens'] += input_t
    enrichment['total_output_tokens'] += output_t
    enrichment['total_cache_read_tokens'] += cache_read
    enrichment['total_cache_creation_tokens'] += cache_creation
    enrichment['tool_use_count'] += len(tool_uses)

    if model:
        models_seen.add(model)
    if has_thinking:
        enrichment['thinking_turns'] += 1
    if stop_reason:
        enrichment['stop_reasons'][stop_reason] = enrichment['stop_reasons'].get(stop_reason, 0) + 1

    enrichment['per_turn'].append({
        'turn_index': turn_index,
        'model': model,
        'stop_reason': stop_reason,
        'input_tokens': input_t,
        'output_tokens': output_t,
        'cache_read_tokens': cache_read,
        'cache_creation_tokens': cache_creation,
        'has_thinking': has_thinking,
        'tool_uses': tool_uses,
    })

enrichment['conversation_turns'] = turn_index
enrichment['models_used'] = sorted(models_seen)
enrichment['primary_model'] = enrichment['models_used'][0] if enrichment['models_used'] else None

json.dump(enrichment, sys.stdout)
" 2>/dev/null | curl -s --max-time 10 -X POST "$_RECONCILE_URL" \
      ${OBSERVAL_USER_ID:+-H "X-Observal-User-Id: $OBSERVAL_USER_ID"} \
      -H "Content-Type: application/json" \
      -d @- >/dev/null 2>&1
  ) &
fi

exit 0
