# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from pydantic import BaseModel, Field, field_validator

MAX_INGEST_TRACES = 1000
MAX_INGEST_SPANS = 1000
MAX_INGEST_SCORES = 1000
MAX_METADATA_ENTRIES = 100
MAX_SHORT_STRING_LENGTH = 512
MAX_TEXT_LENGTH = 1_048_576
MAX_TAGS = 50


def _validate_metadata(value: dict[str, str]) -> dict[str, str]:
    for key, item in value.items():
        if len(str(key)) > MAX_SHORT_STRING_LENGTH:
            raise ValueError(f"metadata keys must be at most {MAX_SHORT_STRING_LENGTH} characters")
        if len(str(item)) > MAX_TEXT_LENGTH:
            raise ValueError(f"metadata values must be at most {MAX_TEXT_LENGTH} characters")
    return value


class TelemetryStatusResponse(BaseModel):
    tool_call_events: int
    agent_interaction_events: int
    status: str


# --- Phase 2: New ingestion schemas ---


class TraceIngest(BaseModel):
    trace_id: str = Field(..., max_length=MAX_SHORT_STRING_LENGTH)
    parent_trace_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    trace_type: str = Field("mcp", max_length=MAX_SHORT_STRING_LENGTH)
    mcp_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    agent_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    session_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    ide: str = Field("", max_length=MAX_SHORT_STRING_LENGTH)
    name: str = Field("", max_length=MAX_SHORT_STRING_LENGTH)
    start_time: str = Field(..., max_length=MAX_SHORT_STRING_LENGTH)
    end_time: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    input: str | None = Field(None, max_length=MAX_TEXT_LENGTH)
    output: str | None = Field(None, max_length=MAX_TEXT_LENGTH)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=MAX_METADATA_ENTRIES)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    tool_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    sandbox_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    graphrag_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    hook_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    skill_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    prompt_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)

    @field_validator("metadata")
    @classmethod
    def metadata_values_are_bounded(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_metadata(value)

    @field_validator("tags")
    @classmethod
    def tags_are_bounded(cls, value: list[str]) -> list[str]:
        for tag in value:
            if len(str(tag)) > MAX_SHORT_STRING_LENGTH:
                raise ValueError(f"tags must be at most {MAX_SHORT_STRING_LENGTH} characters")
        return value


class SpanIngest(BaseModel):
    span_id: str = Field(..., max_length=MAX_SHORT_STRING_LENGTH)
    trace_id: str = Field(..., max_length=MAX_SHORT_STRING_LENGTH)
    parent_span_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    type: str = Field(..., max_length=MAX_SHORT_STRING_LENGTH)
    name: str = Field(..., max_length=MAX_SHORT_STRING_LENGTH)
    method: str = Field("", max_length=MAX_SHORT_STRING_LENGTH)
    input: str | None = Field(None, max_length=MAX_TEXT_LENGTH)
    output: str | None = Field(None, max_length=MAX_TEXT_LENGTH)
    error: str | None = Field(None, max_length=MAX_TEXT_LENGTH)
    start_time: str = Field(..., max_length=MAX_SHORT_STRING_LENGTH)
    end_time: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    latency_ms: int | None = None
    status: str = Field("success", max_length=MAX_SHORT_STRING_LENGTH)
    ide: str = Field("", max_length=MAX_SHORT_STRING_LENGTH)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=MAX_METADATA_ENTRIES)
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
    container_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    exit_code: int | None = None
    network_bytes_in: int | None = None
    network_bytes_out: int | None = None
    disk_read_bytes: int | None = None
    disk_write_bytes: int | None = None
    oom_killed: bool | None = None
    # GraphRAG
    query_interface: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    relevance_score: float | None = None
    chunks_returned: int | None = None
    embedding_latency_ms: int | None = None
    # Hook
    hook_event: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    hook_scope: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    hook_action: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    hook_blocked: bool | None = None
    # Prompt
    variables_provided: int | None = None
    template_tokens: int | None = None
    rendered_tokens: int | None = None

    @field_validator("metadata")
    @classmethod
    def metadata_values_are_bounded(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_metadata(value)


class ScoreIngest(BaseModel):
    score_id: str = Field(..., max_length=MAX_SHORT_STRING_LENGTH)
    trace_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    span_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    mcp_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    agent_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    name: str = Field(..., max_length=MAX_SHORT_STRING_LENGTH)
    source: str = Field("api", max_length=MAX_SHORT_STRING_LENGTH)
    data_type: str = Field("numeric", max_length=MAX_SHORT_STRING_LENGTH)
    value: float
    string_value: str | None = Field(None, max_length=MAX_TEXT_LENGTH)
    comment: str | None = Field(None, max_length=MAX_TEXT_LENGTH)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=MAX_METADATA_ENTRIES)

    @field_validator("metadata")
    @classmethod
    def metadata_values_are_bounded(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_metadata(value)


class IngestBatch(BaseModel):
    traces: list[TraceIngest] = Field(default_factory=list, max_length=MAX_INGEST_TRACES)
    spans: list[SpanIngest] = Field(default_factory=list, max_length=MAX_INGEST_SPANS)
    scores: list[ScoreIngest] = Field(default_factory=list, max_length=MAX_INGEST_SCORES)


class IngestResponse(BaseModel):
    ingested: int
    errors: int
