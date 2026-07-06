# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Session parsing domain.

Both CLI-side (observal_cli/sessions/) and server-side
(observal-server/services/session_parsers/) produce the same normalized
SessionEvent format for the trace viewer.

Normalized SessionEvent schema (dict):
    timestamp: str       ISO-8601 timestamp
    type: str            "user" | "assistant" | "tool_use" | "tool_result" | "thinking" | "error" | "system"
    content: str         Display text (may be truncated)
    role: str            "user" | "assistant" | "system" | "tool"
    tool_name: str       Tool name (for tool_use/tool_result types)
    tool_id: str         Tool use ID for pairing requests with results
    model: str           Model name (for assistant messages)
    tokens: dict         {"input": int, "output": int} token counts
    metadata: dict       harness-specific extra fields
"""
