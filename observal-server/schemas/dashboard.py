import uuid

from pydantic import BaseModel


class McpMetrics(BaseModel):
    listing_id: uuid.UUID
    total_downloads: int
    total_calls: int
    error_count: int
    error_rate: float
    avg_latency_ms: float
    p50_latency_ms: int
    p90_latency_ms: int
    p99_latency_ms: int


class AgentMetrics(BaseModel):
    agent_id: uuid.UUID
    total_interactions: int
    total_downloads: int
    acceptance_rate: float
    avg_tool_calls: float
    avg_latency_ms: float
    # New structured scoring fields
    dimension_averages: dict | None = None
    weakest_dimension: str | None = None
    drift_alert: bool = False


class TimeSeriesPoint(BaseModel):
    date: str
    value: int


class OverviewStats(BaseModel):
    total_mcps: int
    total_agents: int
    total_users: int
    total_tool_calls_today: int
    total_agent_interactions_today: int


class TopItem(BaseModel):
    id: uuid.UUID
    name: str
    value: float


class TopAgentItem(BaseModel):
    id: uuid.UUID
    name: str
    description: str = ""
    owner: str = ""
    version: str = ""
    download_count: int = 0
    average_rating: float | None = None


class LeaderboardItem(TopAgentItem):
    """Same as TopAgentItem — used by the leaderboard endpoint."""
    pass


class TrendPoint(BaseModel):
    date: str
    submissions: int
    users: int


# --- Token usage ---

class TokenByEntity(BaseModel):
    id: str
    name: str
    input: int
    output: int
    total: int
    traces: int


class TokenTimePoint(BaseModel):
    date: str
    input: int
    output: int


class TokenStats(BaseModel):
    total_input: int
    total_output: int
    total_tokens: int
    avg_per_trace: float
    by_agent: list[TokenByEntity]
    by_mcp: list[TokenByEntity]
    over_time: list[TokenTimePoint]


# --- IDE usage ---

class IdeBreakdown(BaseModel):
    ide: str
    traces: int
    avg_latency_ms: float
    error_count: int
    error_rate: float


class IdeUsage(BaseModel):
    ides: list[IdeBreakdown]


# --- Sandbox metrics ---

class SandboxRun(BaseModel):
    span_id: str
    name: str
    exit_code: int | None
    duration_ms: int | None
    memory_mb: float | None
    cpu_ms: int | None
    oom: bool
    timestamp: str


class DateAvg(BaseModel):
    date: str
    avg_cpu: float | None = None
    avg_memory: float | None = None


class SandboxStats(BaseModel):
    total_runs: int
    oom_count: int
    oom_rate: float
    timeout_count: int
    timeout_rate: float
    avg_exit_code: float | None
    recent_runs: list[SandboxRun]
    cpu_over_time: list[DateAvg]
    memory_over_time: list[DateAvg]


# --- GraphRAG metrics ---

class RelevanceBucket(BaseModel):
    bucket: str
    count: int


class GraphRagQuery(BaseModel):
    span_id: str
    name: str
    query_interface: str | None
    entities: int | None
    relationships: int | None
    relevance_score: float | None
    latency_ms: int | None
    timestamp: str


class GraphRagStats(BaseModel):
    total_queries: int
    avg_entities: float | None
    avg_relationships: float | None
    avg_relevance_score: float | None
    avg_embedding_latency_ms: float | None
    relevance_distribution: list[RelevanceBucket]
    recent_queries: list[GraphRagQuery]


# --- RAGAS evaluation ---

class RagasDimensionScore(BaseModel):
    avg: float | None
    count: int


class RagasScores(BaseModel):
    faithfulness: RagasDimensionScore
    answer_relevancy: RagasDimensionScore
    context_precision: RagasDimensionScore
    context_recall: RagasDimensionScore


class RagasSpanResult(BaseModel):
    span_id: str
    trace_id: str
    faithfulness: float
    faithfulness_reason: str
    answer_relevancy: float
    answer_relevancy_reason: str
    context_precision: float
    context_precision_reason: str
    context_recall: float
    context_recall_reason: str


class RagasEvalResponse(BaseModel):
    spans_evaluated: int
    scores: list[RagasSpanResult]
    averages: RagasScores


class RagasEvalRequest(BaseModel):
    graphrag_id: str
    limit: int = 20
    ground_truths: dict[str, str] | None = None


# --- Latency heatmap ---

class LatencyCell(BaseModel):
    name: str
    hour: str
    p50: float
    p90: float
    p99: float


# --- Unannotated traces ---

class UnannotatedTrace(BaseModel):
    trace_id: str
    name: str | None
    session_id: str | None
    ide: str | None
    trace_type: str | None
    start_time: str
