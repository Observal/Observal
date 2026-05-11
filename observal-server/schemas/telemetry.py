# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from pydantic import BaseModel


class TelemetryStatusResponse(BaseModel):
    tool_call_events: int
    agent_interaction_events: int
    status: str


# --- Phase 2: New ingestion schemas ---


class TraceIngest(BaseModel):
    trace_id: str
    parent_trace_id: str | None = None
    trace_type: str = "mcp"
    mcp_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    ide: str = ""
    name: str = ""
    start_time: str
    end_time: str | None = None
    input: str | None = None
    output: str | None = None
    metadata: dict[str, str] = {}
    tags: list[str] = []
    tool_id: str | None = None
    sandbox_id: str | None = None
    graphrag_id: str | None = None
    hook_id: str | None = None
    skill_id: str | None = None
    prompt_id: str | None = None


class SpanIngest(BaseModel):
    span_id: str
    trace_id: str
    parent_span_id: str | None = None
    type: str
    name: str
    method: str = ""
    input: str | None = None
    output: str | None = None
    error: str | None = None
    start_time: str
    end_time: str | None = None
    latency_ms: int | None = None
    status: str = "success"
    ide: str = ""
    metadata: dict[str, str] = {}
    token_count_input: int | None = None
    token_count_output: int | None = None
    token_count_total: int | None = None
    cost: float | None = None
    cpu_ms: int | None = None
    memory_mb: float | None = None
    hop_count: int | None = None
    entities_retrieved: int | None = None
    relationships_used: int | None = None
    retry_count: int | None = None
    tools_available: int | None = None
    tool_schema_valid: bool | None = None
    # Sandbox
    container_id: str | None = None
    exit_code: int | None = None
    network_bytes_in: int | None = None
    network_bytes_out: int | None = None
    disk_read_bytes: int | None = None
    disk_write_bytes: int | None = None
    oom_killed: bool | None = None
    # GraphRAG
    query_interface: str | None = None
    relevance_score: float | None = None
    chunks_returned: int | None = None
    embedding_latency_ms: int | None = None
    # Hook
    hook_event: str | None = None
    hook_scope: str | None = None
    hook_action: str | None = None
    hook_blocked: bool | None = None
    # Prompt
    variables_provided: int | None = None
    template_tokens: int | None = None
    rendered_tokens: int | None = None


class ScoreIngest(BaseModel):
    score_id: str
    trace_id: str | None = None
    span_id: str | None = None
    mcp_id: str | None = None
    agent_id: str | None = None
    name: str
    source: str = "api"
    data_type: str = "numeric"
    value: float
    string_value: str | None = None
    comment: str | None = None
    metadata: dict[str, str] = {}


class IngestBatch(BaseModel):
    traces: list[TraceIngest] = []
    spans: list[SpanIngest] = []
    scores: list[ScoreIngest] = []


class IngestResponse(BaseModel):
    ingested: int
    errors: int
