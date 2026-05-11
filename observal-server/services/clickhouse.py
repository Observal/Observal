import json
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import settings

logger = structlog.get_logger(__name__)


async def _invalidate_cache():
    """Best-effort cache invalidation after ClickHouse writes."""
    try:
        from services.cache import invalidate_all

        await invalidate_all()
    except Exception:
        pass


_parsed = urlparse(settings.CLICKHOUSE_URL.replace("clickhouse://", "http://"))
CLICKHOUSE_HTTP = f"http://{_parsed.hostname}:{_parsed.port or 8123}"
CLICKHOUSE_DB = _parsed.path.strip("/") or "default"
CLICKHOUSE_USER = _parsed.username or "default"
CLICKHOUSE_PASSWORD = _parsed.password or ""

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=settings.CLICKHOUSE_TIMEOUT,
            limits=httpx.Limits(
                max_connections=settings.CLICKHOUSE_MAX_CONNECTIONS,
                max_keepalive_connections=settings.CLICKHOUSE_MAX_KEEPALIVE,
            ),
        )
    return _client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
    reraise=True,
)
async def _query(sql: str, params: dict | None = None, *, data: str | None = None):
    """Execute a ClickHouse query via HTTP.

    Args:
        sql: The SQL statement.  Use ``{name:Type}`` placeholders for
            parameterized queries.
        params: Parameter dict - keys **must** use the ``param_`` prefix
            (e.g. ``{"param_pid": "default"}``).
        data: Optional body content appended after the SQL, separated by a
            newline.  Used for ``INSERT ... FORMAT JSONEachRow`` where each
            line in *data* is a JSON object.
    """
    client = _get_client()
    query_params = {
        "database": CLICKHOUSE_DB,
        "user": CLICKHOUSE_USER,
        "password": CLICKHOUSE_PASSWORD,
    }
    # Inject admin-configured resource overrides (e.g. max_memory_usage)
    if _resource_overrides:
        query_params.update(_resource_overrides)
    if params:
        query_params.update(params)
    body = f"{sql}\n{data}" if data else sql
    return await client.post(CLICKHOUSE_HTTP, content=body, params=query_params)


async def clickhouse_health() -> bool:
    """Check ClickHouse connectivity. Returns True if healthy."""
    try:
        resp = await _query("SELECT 1")
        return resp.status_code == 200
    except Exception:
        return False


INIT_SQL = [
    # New telemetry tables (Phase 1)
    """CREATE TABLE IF NOT EXISTS traces (
        trace_id        String,
        parent_trace_id Nullable(String),
        project_id      String,
        mcp_id          Nullable(String),
        agent_id        Nullable(String),
        user_id         String,
        session_id      Nullable(String),
        ide             LowCardinality(String),
        environment     LowCardinality(String) DEFAULT 'default',
        start_time      DateTime64(3),
        end_time        Nullable(DateTime64(3)),
        trace_type      LowCardinality(String) DEFAULT 'mcp',
        name            String DEFAULT '',
        metadata        Map(LowCardinality(String), String),
        tags            Array(String),
        input           Nullable(String) CODEC(ZSTD(3)),
        output          Nullable(String) CODEC(ZSTD(3)),
        created_at      DateTime64(3) DEFAULT now(),
        event_ts        DateTime64(3),
        is_deleted      UInt8 DEFAULT 0,
        INDEX idx_trace_id trace_id TYPE bloom_filter(0.001) GRANULARITY 1,
        INDEX idx_parent_trace_id parent_trace_id TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_project_id project_id TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_mcp_id mcp_id TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_agent_id agent_id TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_user_id user_id TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_session_id session_id TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_trace_type trace_type TYPE bloom_filter(0.01) GRANULARITY 1
    ) ENGINE = ReplacingMergeTree(event_ts, is_deleted)
    PARTITION BY toYYYYMM(start_time)
    PRIMARY KEY (project_id, user_id, toDate(start_time))
    ORDER BY (project_id, user_id, toDate(start_time), trace_id)""",
    """CREATE TABLE IF NOT EXISTS spans (
        span_id                 String,
        trace_id                String,
        parent_span_id          Nullable(String),
        project_id              String,
        mcp_id                  Nullable(String),
        agent_id                Nullable(String),
        user_id                 String,
        type                    LowCardinality(String),
        name                    String,
        method                  String DEFAULT '',
        input                   Nullable(String) CODEC(ZSTD(3)),
        output                  Nullable(String) CODEC(ZSTD(3)),
        error                   Nullable(String) CODEC(ZSTD(3)),
        start_time              DateTime64(3),
        end_time                Nullable(DateTime64(3)),
        latency_ms              Nullable(UInt32),
        status                  LowCardinality(String) DEFAULT 'success',
        level                   LowCardinality(String) DEFAULT 'DEFAULT',
        token_count_input       Nullable(UInt32),
        token_count_output      Nullable(UInt32),
        token_count_total       Nullable(UInt32),
        cost                    Nullable(Float64),
        cpu_ms                  Nullable(UInt32),
        memory_mb               Nullable(Float32),
        hop_count               Nullable(UInt8),
        entities_retrieved      Nullable(UInt16),
        relationships_used      Nullable(UInt16),
        retry_count             Nullable(UInt8),
        tools_available         Nullable(UInt16),
        tool_schema_valid       Nullable(UInt8),
        ide                     LowCardinality(String) DEFAULT '',
        environment             LowCardinality(String) DEFAULT 'default',
        metadata                Map(LowCardinality(String), String),
        created_at              DateTime64(3) DEFAULT now(),
        event_ts                DateTime64(3),
        is_deleted              UInt8 DEFAULT 0,
        INDEX idx_span_id span_id TYPE bloom_filter(0.001) GRANULARITY 1,
        INDEX idx_trace_id trace_id TYPE bloom_filter(0.001) GRANULARITY 1,
        INDEX idx_project_id project_id TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_name name TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_type type TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_status status TYPE bloom_filter(0.01) GRANULARITY 1
    ) ENGINE = ReplacingMergeTree(event_ts, is_deleted)
    PARTITION BY toYYYYMM(start_time)
    PRIMARY KEY (project_id, user_id, type, toDate(start_time))
    ORDER BY (project_id, user_id, type, toDate(start_time), span_id)""",
    """CREATE TABLE IF NOT EXISTS scores (
        score_id        String,
        trace_id        Nullable(String),
        span_id         Nullable(String),
        project_id      String,
        mcp_id          Nullable(String),
        agent_id        Nullable(String),
        user_id         String,
        name            String,
        source          LowCardinality(String),
        data_type       LowCardinality(String),
        value           Float64,
        string_value    Nullable(String),
        comment         Nullable(String) CODEC(ZSTD(1)),
        eval_template_id Nullable(String),
        eval_config_id  Nullable(String),
        eval_run_id     Nullable(String),
        environment     LowCardinality(String) DEFAULT 'default',
        metadata        Map(LowCardinality(String), String),
        timestamp       DateTime64(3),
        created_at      DateTime64(3) DEFAULT now(),
        event_ts        DateTime64(3),
        is_deleted      UInt8 DEFAULT 0,
        INDEX idx_score_id score_id TYPE bloom_filter(0.001) GRANULARITY 1,
        INDEX idx_trace_id trace_id TYPE bloom_filter(0.001) GRANULARITY 1,
        INDEX idx_span_id span_id TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_project_id project_id TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_name name TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_source source TYPE bloom_filter(0.01) GRANULARITY 1
    ) ENGINE = ReplacingMergeTree(event_ts, is_deleted)
    PARTITION BY toYYYYMM(timestamp)
    PRIMARY KEY (project_id, user_id, toDate(timestamp), name)
    ORDER BY (project_id, user_id, toDate(timestamp), name, score_id)""",
    # Registry expansion: new span columns
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS container_id Nullable(String)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS exit_code Nullable(Int16)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS network_bytes_in Nullable(UInt64)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS network_bytes_out Nullable(UInt64)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS disk_read_bytes Nullable(UInt64)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS disk_write_bytes Nullable(UInt64)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS oom_killed Nullable(UInt8)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS query_interface Nullable(String)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS relevance_score Nullable(Float32)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS chunks_returned Nullable(UInt16)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS embedding_latency_ms Nullable(UInt32)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS hook_event Nullable(String)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS hook_scope Nullable(String)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS hook_action Nullable(String)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS hook_blocked Nullable(UInt8)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS variables_provided Nullable(UInt8)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS template_tokens Nullable(UInt32)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS rendered_tokens Nullable(UInt32)""",
    # Registry expansion: new trace columns
    """ALTER TABLE traces ADD COLUMN IF NOT EXISTS tool_id Nullable(String)""",
    """ALTER TABLE traces ADD COLUMN IF NOT EXISTS sandbox_id Nullable(String)""",
    """ALTER TABLE traces ADD COLUMN IF NOT EXISTS graphrag_id Nullable(String)""",
    """ALTER TABLE traces ADD COLUMN IF NOT EXISTS hook_id Nullable(String)""",
    """ALTER TABLE traces ADD COLUMN IF NOT EXISTS skill_id Nullable(String)""",
    """ALTER TABLE traces ADD COLUMN IF NOT EXISTS prompt_id Nullable(String)""",
    # Agent versioning: track which version produced telemetry
    """ALTER TABLE traces ADD COLUMN IF NOT EXISTS agent_version Nullable(String)""",
    """ALTER TABLE spans ADD COLUMN IF NOT EXISTS agent_version Nullable(String)""",
    """ALTER TABLE scores ADD COLUMN IF NOT EXISTS agent_version Nullable(String)""",
    # Bloom filter indexes for agent_version point lookups
    """ALTER TABLE traces ADD INDEX IF NOT EXISTS idx_agent_version agent_version TYPE bloom_filter(0.01) GRANULARITY 1""",
    """ALTER TABLE spans ADD INDEX IF NOT EXISTS idx_agent_version agent_version TYPE bloom_filter(0.01) GRANULARITY 1""",
    """ALTER TABLE scores ADD INDEX IF NOT EXISTS idx_agent_version agent_version TYPE bloom_filter(0.01) GRANULARITY 1""",
    # Security events table (SIEM integration — SOC 2 / ISO 27001)
    """CREATE TABLE IF NOT EXISTS security_events (
        event_id    UUID,
        timestamp   DateTime64(3, 'UTC'),
        event_type  LowCardinality(String),
        severity    LowCardinality(String),
        actor_id    String DEFAULT '',
        actor_email String DEFAULT '',
        actor_role  LowCardinality(String) DEFAULT '',
        target_id   String DEFAULT '',
        target_type LowCardinality(String) DEFAULT '',
        outcome     LowCardinality(String),
        source_ip   String DEFAULT '',
        user_agent  String DEFAULT '',
        detail      String DEFAULT '',
        org_id      String DEFAULT '',
        INDEX idx_event_type event_type TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_severity severity TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_actor_id actor_id TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_outcome outcome TYPE bloom_filter(0.01) GRANULARITY 1
    ) ENGINE = MergeTree()
    TTL toDateTime(timestamp) + INTERVAL 730 DAY
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (event_type, severity, timestamp)""",
    # Audit log table (enterprise compliance — SOC 2 / ISO 27001)
    """CREATE TABLE IF NOT EXISTS audit_log (
        event_id    UUID,
        timestamp   DateTime64(3, 'UTC'),
        actor_id    String,
        actor_email String,
        actor_role  LowCardinality(String),
        action      LowCardinality(String),
        resource_type LowCardinality(String),
        resource_id String DEFAULT '',
        resource_name String DEFAULT '',
        http_method LowCardinality(String) DEFAULT '',
        http_path   String DEFAULT '',
        status_code UInt16 DEFAULT 0,
        ip_address  String DEFAULT '',
        user_agent  String DEFAULT '',
        detail      String DEFAULT '',
        INDEX idx_actor_id actor_id TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_action action TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_resource_type resource_type TYPE bloom_filter(0.01) GRANULARITY 1
    ) ENGINE = MergeTree()
    TTL toDateTime(timestamp) + INTERVAL 730 DAY
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (action, resource_type, timestamp)""",
    # Webhook delivery tracking
    """CREATE TABLE IF NOT EXISTS webhook_deliveries (
        delivery_id     UUID,
        event_id        UUID,
        alert_rule_id   UUID,
        attempt_number  UInt8,
        timestamp       DateTime64(3, 'UTC'),
        webhook_url     String,
        status_code     Nullable(UInt16),
        delivery_status LowCardinality(String),
        error           Nullable(String),
        duration_ms     Float32,
        payload_size    UInt32
    ) ENGINE = MergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (alert_rule_id, timestamp)""",
    # Session events: stores parsed JSONL transcript lines from IDE sessions.
    # Replaces hook-based telemetry with direct session file ingestion.
    """CREATE TABLE IF NOT EXISTS session_events (
        session_id      String,
        project_id      String,
        user_id         String,
        agent_id        Nullable(String),
        agent_version   Nullable(String),
        layer_hash      Nullable(String),
        ide             LowCardinality(String),
        line_offset     UInt32,
        line_hash       String DEFAULT '' CODEC(ZSTD(1)),
        event_type      LowCardinality(String),
        timestamp       DateTime64(3, 'UTC'),
        uuid            Nullable(String),
        parent_uuid     Nullable(String),
        tool_name       Nullable(String),
        tool_id         Nullable(String),
        content_preview String CODEC(ZSTD(1)),
        content_length  UInt32,
        raw_line        String CODEC(ZSTD(3)),
        ingested_at     DateTime64(3, 'UTC') DEFAULT now(),
        credits         Float64 DEFAULT 0,
        parent_session_id Nullable(String),
        INDEX idx_se_session_id session_id TYPE bloom_filter(0.001) GRANULARITY 1,
        INDEX idx_se_project_id project_id TYPE bloom_filter(0.01) GRANULARITY 1,
        -- set(20) is more precise than bloom_filter for low-cardinality LowCardinality columns;
        -- event_type has ~10-20 distinct values so set membership is O(1) with no false positives.
        INDEX idx_se_event_type event_type TYPE set(20) GRANULARITY 1,
        INDEX idx_se_line_hash line_hash TYPE bloom_filter(0.001) GRANULARITY 1
    ) ENGINE = ReplacingMergeTree(ingested_at)
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (project_id, session_id, line_offset)""",
    # otel_logs: previously created by the OTEL collector.
    # Now managed by the API since the collector is removed.
    """CREATE TABLE IF NOT EXISTS otel_logs (
        Timestamp       DateTime64(9) CODEC(Delta, ZSTD(1)),
        TraceId         String CODEC(ZSTD(1)),
        SpanId          String CODEC(ZSTD(1)),
        TraceFlags      UInt32 CODEC(ZSTD(1)),
        SeverityText    LowCardinality(String) CODEC(ZSTD(1)),
        SeverityNumber  Int32 CODEC(ZSTD(1)),
        ServiceName     LowCardinality(String) CODEC(ZSTD(1)),
        Body            String CODEC(ZSTD(1)),
        ResourceSchemaUrl   String CODEC(ZSTD(1)),
        ResourceAttributes  Map(LowCardinality(String), String) CODEC(ZSTD(1)),
        ScopeSchemaUrl  String CODEC(ZSTD(1)),
        ScopeName       String CODEC(ZSTD(1)),
        ScopeVersion    String CODEC(ZSTD(1)),
        ScopeAttributes Map(LowCardinality(String), String) CODEC(ZSTD(1)),
        LogAttributes   Map(LowCardinality(String), String) CODEC(ZSTD(1)),
        INDEX idx_trace_id TraceId TYPE bloom_filter(0.001) GRANULARITY 1,
        INDEX idx_res_attr_key mapKeys(ResourceAttributes) TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_res_attr_value mapValues(ResourceAttributes) TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_log_attr_key mapKeys(LogAttributes) TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_log_attr_value mapValues(LogAttributes) TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_body Body TYPE tokenbf_v1(32768, 3, 0) GRANULARITY 1
    ) ENGINE = MergeTree()
    PARTITION BY toDate(Timestamp)
    ORDER BY (ServiceName, SeverityText, toUnixTimestamp(Timestamp), TraceId)""",
    # Subagent attribution: link subagent sessions to their parent session
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS parent_session_id Nullable(String)""",
    # set(0) on parent_session_id: the column is sparse (most rows NULL) and queried
    # only by equality. bloom_filter loses probability mass to NULLs on Nullable columns;
    # set(0) is exact-match with unlimited cardinality — ideal for sparse equality lookups.
    """ALTER TABLE session_events ADD INDEX IF NOT EXISTS idx_se_parent_session_id parent_session_id TYPE set(0) GRANULARITY 1""",
    # Materialized token / model columns — extract at ingest, avoid JSONExtract at query time.
    # Default 0 / '' so existing rows remain queryable without rewriting.
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS input_tokens Int32 DEFAULT 0""",
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS output_tokens Int32 DEFAULT 0""",
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS cache_read_tokens Int32 DEFAULT 0""",
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS cache_write_tokens Int32 DEFAULT 0""",
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS model LowCardinality(String) DEFAULT ''""",
    # raw_line size guard — 1 when the original line exceeded RAW_LINE_MAX_BYTES and was truncated.
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS raw_line_truncated UInt8 DEFAULT 0""",
    # Pre-aggregated session stats — AggregatingMergeTree table + materialized view.
    #
    # Fires on every INSERT block into session_events and maintains running sums/min/max
    # per (project_id, session_id) so that the session list query and insights metrics
    # can read a tiny aggregate table instead of scanning session_events FINAL with
    # JSONExtract on every row.  Benchmark: ClickHouse Bluesky blog shows pre-aggregated
    # MVs reduce 44-second full scans to 6 ms (7,000x speedup at 4B rows).
    #
    # SimpleAggregateFunction: no -State/-Merge suffix needed.  Insert raw partial values;
    # ClickHouse applies the aggregate function on merge.  Correctness relies on the
    # dedup check in session_ingest.py (offset + hash) preventing duplicate rows.
    """CREATE TABLE IF NOT EXISTS session_stats_agg (
        project_id          String,
        session_id          String,
        agent_id            LowCardinality(String) DEFAULT '',
        user_id             String                 DEFAULT '',
        parent_session_id   String                 DEFAULT '',
        ide                 LowCardinality(String) DEFAULT '',
        first_event_time    SimpleAggregateFunction(min,     DateTime64(3, 'UTC')),
        last_event_time     SimpleAggregateFunction(max,     DateTime64(3, 'UTC')),
        event_count         SimpleAggregateFunction(sum,     Int64),
        prompt_count        SimpleAggregateFunction(sum,     Int64),
        tool_call_count     SimpleAggregateFunction(sum,     Int64),
        tool_result_count   SimpleAggregateFunction(sum,     Int64),
        input_tokens        SimpleAggregateFunction(sum,     Int64),
        output_tokens       SimpleAggregateFunction(sum,     Int64),
        cache_read_tokens   SimpleAggregateFunction(sum,     Int64),
        cache_write_tokens  SimpleAggregateFunction(sum,     Int64),
        total_credits       SimpleAggregateFunction(sum,     Float64),
        model               SimpleAggregateFunction(anyLast, String),
        INDEX idx_ssa_user_id  user_id  TYPE bloom_filter(0.01) GRANULARITY 1,
        INDEX idx_ssa_agent_id agent_id TYPE bloom_filter(0.01) GRANULARITY 1
    ) ENGINE = AggregatingMergeTree()
    ORDER BY (project_id, session_id)""",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS session_stats_mv
    TO session_stats_agg AS
    SELECT
        project_id,
        session_id,
        anyIf(agent_id, agent_id IS NOT NULL AND agent_id != '') AS agent_id,
        anyIf(user_id, user_id != '')                            AS user_id,
        anyIf(coalesce(parent_session_id, ''), parent_session_id IS NOT NULL AND parent_session_id != '') AS parent_session_id,
        anyIf(ide, ide != '')                                    AS ide,
        min(timestamp)                        AS first_event_time,
        max(timestamp)                        AS last_event_time,
        count()                               AS event_count,
        countIf(event_type = 'user_prompt')   AS prompt_count,
        countIf(event_type = 'tool_call')     AS tool_call_count,
        countIf(event_type = 'tool_result')   AS tool_result_count,
        sum(input_tokens)                     AS input_tokens,
        sum(output_tokens)                    AS output_tokens,
        sum(cache_read_tokens)                AS cache_read_tokens,
        sum(cache_write_tokens)               AS cache_write_tokens,
        sum(credits)                          AS total_credits,
        anyLastIf(model, model != '')         AS model
    FROM session_events
    GROUP BY project_id, session_id""",
    # Null out raw_line blobs older than 30 days to cap storage.
    # Row metadata (input_tokens, output_tokens, model, content_preview,
    # tool_name, event_type, timestamps) is retained indefinitely.
    # The TTL fires on background merge; existing data is not immediately affected.
    # Row-level TTL (set via admin retention_days) is independent and deletes entire rows.
    # Source: clickhouse.com/docs/guides/developer/ttl — column TTL expression pattern.
    """ALTER TABLE session_events MODIFY COLUMN raw_line String TTL timestamp + INTERVAL 30 DAY""",
    # Migrate event_type skip index from bloom_filter -> set(20).
    # LowCardinality(String) with ~10-20 distinct values is a perfect fit for set:
    # exact membership check, zero false positives, cheaper to build than bloom_filter.
    # bloom_filter on low-cardinality columns wastes probability mass and adds write overhead.
    # NOTE: ADD INDEX IF NOT EXISTS is a no-op if the index already exists (by name),
    # so the DROP only runs once effectively. MATERIALIZE INDEX is handled conditionally
    # in init_clickhouse() to avoid re-indexing on every restart.
    """ALTER TABLE session_events ADD INDEX IF NOT EXISTS idx_se_event_type event_type TYPE set(20) GRANULARITY 1""",
    # Migrate parent_session_id skip index from bloom_filter -> set(0).
    # Nullable column where most rows are NULL; bloom_filter on Nullable spreads
    # probability mass across NULL entries causing elevated false-positive rates.
    # set(0) stores exact values per block with no size cap — correct for equality
    # lookups like WHERE parent_session_id = {sid} used in subagent fetches.
    """ALTER TABLE session_events ADD INDEX IF NOT EXISTS idx_se_parent_session_id parent_session_id TYPE set(0) GRANULARITY 1""",
    # Projection for queries that don't need raw_line (the heavy ZSTD(3) blob column).
    # Stores session metadata ordered by (session_id, line_offset) so CH can use a
    # tight primary key scan without reading raw_line at all. CH picks this projection
    # automatically when raw_line is absent from the SELECT list.
    # Trades ~1x storage for the projected columns against I/O savings on repeated reads.
    """ALTER TABLE session_events ADD PROJECTION IF NOT EXISTS proj_session_view (
        SELECT
            session_id, line_offset, timestamp, event_type, content_preview,
            tool_name, tool_id, uuid, parent_uuid, content_length,
            ide, credits, ingested_at, raw_line_truncated,
            input_tokens, output_tokens, model
        ORDER BY (session_id, line_offset)
    )""",
    # NOTE: MATERIALIZE PROJECTION is handled conditionally in init_clickhouse()
    # to avoid creating a new mutation on every server restart.
]


# ── Resource tuning ───────────────────────────────────────
# Maps enterprise_config keys to ClickHouse SET-able settings.
# Only whitelisted settings are accepted to avoid SQL injection.
RESOURCE_SETTINGS_MAP: dict[str, tuple[str, type]] = {
    "resource.max_query_memory_mb": ("max_memory_usage", int),
    "resource.group_by_spill_mb": ("max_bytes_before_external_group_by", int),
    "resource.sort_spill_mb": ("max_bytes_before_external_sort", int),
    "resource.join_memory_mb": ("max_bytes_in_join", int),
}

# Per-query overrides injected into every HTTP request.
# Populated from enterprise_config on startup and when admin clicks "Apply".
_resource_overrides: dict[str, str] = {}


async def apply_resource_settings(overrides: dict[str, str] | None = None):
    """Load resource tuning settings and inject them into every ClickHouse query.

    ClickHouse's HTTP API accepts settings as query parameters (e.g.
    ``?max_memory_usage=300000000``).  This sidesteps the XML-user
    readonly limitation: no ALTER USER needed, settings apply per-request.

    Reads from enterprise_config (Postgres) unless *overrides* is supplied.
    """
    global _resource_overrides
    resource_values: dict[str, str] = {}

    if overrides is not None:
        resource_values = overrides
    else:
        try:
            from sqlalchemy import select

            from database import async_session
            from models.enterprise_config import EnterpriseConfig

            async with async_session() as db:
                result = await db.execute(select(EnterpriseConfig).where(EnterpriseConfig.key.like("resource.%")))
                for cfg in result.scalars().all():
                    resource_values[cfg.key] = cfg.value
        except Exception as e:
            logger.debug("Could not read resource settings from DB: %s", e)

    if not resource_values:
        return

    new_overrides: dict[str, str] = {}
    for config_key, (ch_setting, cast) in RESOURCE_SETTINGS_MAP.items():
        raw = resource_values.get(config_key)
        if raw is None:
            continue
        try:
            mb = cast(raw)
            if mb <= 0:
                continue
            new_overrides[ch_setting] = str(mb * 1_000_000)
        except (ValueError, TypeError):
            logger.warning("Invalid resource setting %s=%s, skipping", config_key, raw)

    _resource_overrides = new_overrides
    logger.info("ClickHouse resource overrides loaded: %s", new_overrides)


async def _materialize_if_needed():
    """Conditionally materialize projection and indexes on session_events.

    Only runs MATERIALIZE commands when parts exist that lack the projection
    or indexes.  This avoids creating a new mutation entry on every server
    restart (which would otherwise cause write amplification and mutation
    queue buildup in ClickHouse).
    """
    # Materialize projection if any active parts lack it
    try:
        r = await _query(
            "SELECT count() AS cnt FROM system.parts "
            "WHERE table = 'session_events' AND database = currentDatabase() "
            "AND active AND NOT has(projections, 'proj_session_view') "
            "FORMAT JSON"
        )
        if r.status_code == 200:
            data = r.json().get("data", [{}])
            if int(data[0].get("cnt", 0)) > 0:
                await _query("ALTER TABLE session_events MATERIALIZE PROJECTION proj_session_view")
                logger.info("Materialized proj_session_view projection")
    except Exception as e:
        logger.warning("materialize_projection_check_failed", error=str(e))

    # Materialize indexes if they were newly added (parts lack them)
    for idx_name in ("idx_se_event_type", "idx_se_parent_session_id"):
        try:
            r = await _query(
                "SELECT count() AS cnt FROM system.parts "
                "WHERE table = 'session_events' AND database = currentDatabase() "
                f"AND active AND NOT has(data_skipping_indices, '{idx_name}') "
                "FORMAT JSON"
            )
            if r.status_code == 200:
                data = r.json().get("data", [{}])
                if int(data[0].get("cnt", 0)) > 0:
                    await _query(f"ALTER TABLE session_events MATERIALIZE INDEX {idx_name}")
                    logger.info("Materialized index %s", idx_name)
        except Exception as e:
            logger.warning("materialize_index_check_failed", index=idx_name, error=str(e))


async def init_clickhouse():
    """Create ClickHouse tables if they don't exist and configure retention.

    Raises on unreachable server so startup fails fast.
    """
    # Verify ClickHouse is reachable before running DDL
    if not await clickhouse_health():
        raise RuntimeError(f"ClickHouse unreachable at {CLICKHOUSE_HTTP}")

    for stmt in INIT_SQL:
        try:
            await _query(stmt)
        except Exception as e:
            logger.warning("clickhouse_init_failed", error=str(e))

    # Conditionally materialize projection and indexes — only runs once,
    # avoids creating new mutations / losing index data on every restart.
    await _materialize_if_needed()

    # Apply admin-configured resource tuning from enterprise_config
    await apply_resource_settings()

    # Apply data retention TTL if configured
    retention_days = settings.DATA_RETENTION_DAYS
    if retention_days > 0:
        ttl_stmts = [
            f"ALTER TABLE traces MODIFY TTL toDate(start_time) + INTERVAL {retention_days} DAY",
            f"ALTER TABLE spans MODIFY TTL toDate(start_time) + INTERVAL {retention_days} DAY",
            f"ALTER TABLE scores MODIFY TTL toDate(timestamp) + INTERVAL {retention_days} DAY",
            f"ALTER TABLE otel_logs MODIFY TTL toDate(Timestamp) + INTERVAL {retention_days} DAY",
            f"ALTER TABLE session_events MODIFY TTL toDate(timestamp) + INTERVAL {retention_days} DAY",
        ]
        applied = 0
        for stmt in ttl_stmts:
            try:
                await _query(stmt)
                applied += 1
            except Exception as e:
                logger.warning("clickhouse_ttl_failed", error=str(e))
        if applied == len(ttl_stmts):
            logger.info("ClickHouse retention set to %d days", retention_days)
        else:
            logger.warning("ClickHouse retention partially applied: %d/%d tables", applied, len(ttl_stmts))
    else:
        logger.info("ClickHouse data retention disabled (DATA_RETENTION_DAYS=0)")


def _now_ms() -> str:
    """Current UTC timestamp as ISO string with millisecond precision."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _normalize_ts(value: str | None) -> str | None:
    """Normalize a timestamp string for ClickHouse DateTime64 compatibility.

    ClickHouse JSONEachRow cannot parse ISO 8601 ``T``/``Z`` separators,
    so we convert ``2026-04-21T07:35:00Z`` -> ``2026-04-21 07:35:00.000``.
    """
    if value is None:
        return None
    v = value.replace("T", " ").rstrip("Z")
    if "." not in v:
        v += ".000"
    return v


async def insert_traces(traces: list[dict]):
    """Batch insert traces into ClickHouse using JSONEachRow."""
    if not traces:
        return
    event_ts = _now_ms()
    lines = []
    for t in traces:
        row = {
            "trace_id": t["trace_id"],
            "parent_trace_id": t.get("parent_trace_id"),
            "project_id": t["project_id"],
            "mcp_id": t.get("mcp_id"),
            "agent_id": t.get("agent_id"),
            "user_id": t["user_id"],
            "session_id": t.get("session_id"),
            "ide": t.get("ide", ""),
            "environment": t.get("environment", "default"),
            "start_time": _normalize_ts(t["start_time"]),
            "end_time": _normalize_ts(t.get("end_time")),
            "trace_type": t.get("trace_type", "mcp"),
            "name": t.get("name", ""),
            "metadata": t.get("metadata", {}),
            "tags": t.get("tags", []),
            "input": t.get("input"),
            "output": t.get("output"),
            "event_ts": event_ts,
            "is_deleted": 0,
            "tool_id": t.get("tool_id"),
            "sandbox_id": t.get("sandbox_id"),
            "graphrag_id": t.get("graphrag_id"),
            "hook_id": t.get("hook_id"),
            "skill_id": t.get("skill_id"),
            "prompt_id": t.get("prompt_id"),
            "agent_version": t.get("agent_version"),
        }
        lines.append(json.dumps(row, default=str))
    sql = (
        "INSERT INTO traces (trace_id, parent_trace_id, project_id, mcp_id, agent_id, "
        "user_id, session_id, ide, environment, start_time, end_time, trace_type, name, "
        "metadata, tags, input, output, event_ts, is_deleted, "
        "tool_id, sandbox_id, graphrag_id, hook_id, skill_id, prompt_id, "
        "agent_version) FORMAT JSONEachRow"
    )
    try:
        r = await _query(sql, data="\n".join(lines))
        r.raise_for_status()
        await _invalidate_cache()
    except Exception as e:
        logger.error("clickhouse_insert_traces_failed", error=str(e))
        raise


async def insert_spans(spans: list[dict]):
    """Batch insert spans into ClickHouse using JSONEachRow."""
    if not spans:
        return
    event_ts = _now_ms()
    lines = []
    for s in spans:
        row = {
            "span_id": s["span_id"],
            "trace_id": s["trace_id"],
            "parent_span_id": s.get("parent_span_id"),
            "project_id": s["project_id"],
            "mcp_id": s.get("mcp_id"),
            "agent_id": s.get("agent_id"),
            "user_id": s["user_id"],
            "type": s["type"],
            "name": s["name"],
            "method": s.get("method", ""),
            "input": s.get("input"),
            "output": s.get("output"),
            "error": s.get("error"),
            "start_time": _normalize_ts(s["start_time"]),
            "end_time": _normalize_ts(s.get("end_time")),
            "latency_ms": s.get("latency_ms"),
            "status": s.get("status", "success"),
            "level": s.get("level", "DEFAULT"),
            "token_count_input": s.get("token_count_input"),
            "token_count_output": s.get("token_count_output"),
            "token_count_total": s.get("token_count_total"),
            "cost": s.get("cost"),
            "cpu_ms": s.get("cpu_ms"),
            "memory_mb": s.get("memory_mb"),
            "hop_count": s.get("hop_count"),
            "entities_retrieved": s.get("entities_retrieved"),
            "relationships_used": s.get("relationships_used"),
            "retry_count": s.get("retry_count"),
            "tools_available": s.get("tools_available"),
            "tool_schema_valid": s.get("tool_schema_valid"),
            "ide": s.get("ide", ""),
            "environment": s.get("environment", "default"),
            "metadata": s.get("metadata", {}),
            "event_ts": event_ts,
            "is_deleted": 0,
            "container_id": s.get("container_id"),
            "exit_code": s.get("exit_code"),
            "network_bytes_in": s.get("network_bytes_in"),
            "network_bytes_out": s.get("network_bytes_out"),
            "disk_read_bytes": s.get("disk_read_bytes"),
            "disk_write_bytes": s.get("disk_write_bytes"),
            "oom_killed": s.get("oom_killed"),
            "query_interface": s.get("query_interface"),
            "relevance_score": s.get("relevance_score"),
            "chunks_returned": s.get("chunks_returned"),
            "embedding_latency_ms": s.get("embedding_latency_ms"),
            "hook_event": s.get("hook_event"),
            "hook_scope": s.get("hook_scope"),
            "hook_action": s.get("hook_action"),
            "hook_blocked": s.get("hook_blocked"),
            "variables_provided": s.get("variables_provided"),
            "template_tokens": s.get("template_tokens"),
            "rendered_tokens": s.get("rendered_tokens"),
            "agent_version": s.get("agent_version"),
        }
        lines.append(json.dumps(row, default=str))
    sql = (
        "INSERT INTO spans (span_id, trace_id, parent_span_id, project_id, mcp_id, "
        "agent_id, user_id, type, name, method, input, output, error, start_time, "
        "end_time, latency_ms, status, level, token_count_input, token_count_output, "
        "token_count_total, cost, cpu_ms, memory_mb, hop_count, entities_retrieved, "
        "relationships_used, retry_count, tools_available, tool_schema_valid, ide, "
        "environment, metadata, event_ts, is_deleted, "
        "container_id, exit_code, network_bytes_in, network_bytes_out, "
        "disk_read_bytes, disk_write_bytes, oom_killed, query_interface, "
        "relevance_score, chunks_returned, embedding_latency_ms, "
        "hook_event, hook_scope, hook_action, hook_blocked, "
        "variables_provided, template_tokens, rendered_tokens, "
        "agent_version) FORMAT JSONEachRow"
    )
    try:
        r = await _query(sql, data="\n".join(lines))
        r.raise_for_status()
        await _invalidate_cache()
    except Exception as e:
        logger.error("clickhouse_insert_spans_failed", error=str(e))
        raise


async def insert_scores(scores: list[dict]):
    """Batch insert scores into ClickHouse using JSONEachRow."""
    if not scores:
        return
    event_ts = _now_ms()
    lines = []
    for sc in scores:
        row = {
            "score_id": sc["score_id"],
            "trace_id": sc.get("trace_id"),
            "span_id": sc.get("span_id"),
            "project_id": sc["project_id"],
            "mcp_id": sc.get("mcp_id"),
            "agent_id": sc.get("agent_id"),
            "user_id": sc["user_id"],
            "name": sc["name"],
            "source": sc.get("source", "api"),
            "data_type": sc.get("data_type", "numeric"),
            "value": sc.get("value", 0),
            "string_value": sc.get("string_value"),
            "comment": sc.get("comment"),
            "eval_template_id": sc.get("eval_template_id"),
            "eval_config_id": sc.get("eval_config_id"),
            "eval_run_id": sc.get("eval_run_id"),
            "environment": sc.get("environment", "default"),
            "metadata": sc.get("metadata", {}),
            "timestamp": _normalize_ts(sc["timestamp"]),
            "event_ts": event_ts,
            "is_deleted": 0,
            "agent_version": sc.get("agent_version"),
        }
        lines.append(json.dumps(row, default=str))
    sql = (
        "INSERT INTO scores (score_id, trace_id, span_id, project_id, mcp_id, agent_id, "
        "user_id, name, source, data_type, value, string_value, comment, "
        "eval_template_id, eval_config_id, eval_run_id, environment, metadata, "
        "timestamp, event_ts, is_deleted, agent_version) FORMAT JSONEachRow"
    )
    try:
        r = await _query(sql, data="\n".join(lines))
        r.raise_for_status()
        await _invalidate_cache()
    except Exception as e:
        logger.error("clickhouse_insert_scores_failed", error=str(e))
        raise


async def insert_otel_logs(rows: list[dict]):
    """Batch insert rows into the otel_logs table (OTEL Collector schema).

    Each row must have: Timestamp, Body, LogAttributes (dict), ServiceName,
    SeverityText, SeverityNumber.  Optional: TraceId, SpanId.
    """
    if not rows:
        return
    lines = []
    for r in rows:
        line = {
            "Timestamp": _normalize_ts(r["Timestamp"]),
            "Body": r.get("Body", ""),
            "LogAttributes": r.get("LogAttributes", {}),
            "ServiceName": r.get("ServiceName", ""),
            "SeverityText": r.get("SeverityText", "INFO"),
            "SeverityNumber": r.get("SeverityNumber", 9),
            "TraceId": r.get("TraceId", ""),
            "SpanId": r.get("SpanId", ""),
        }
        lines.append(json.dumps(line, default=str))
    sql = (
        "INSERT INTO otel_logs (Timestamp, Body, LogAttributes, ServiceName, "
        "SeverityText, SeverityNumber, TraceId, SpanId) FORMAT JSONEachRow"
    )
    try:
        r = await _query(sql, data="\n".join(lines))
        r.raise_for_status()
        await _invalidate_cache()
    except Exception as e:
        logger.error("clickhouse_insert_otel_logs_failed", error=str(e))
        raise


async def query_recent_events(minutes: int = 60) -> dict:
    """Get event counts from the last N minutes from the active telemetry tables."""
    minutes = int(minutes)
    tool_count = 0
    agent_count = 0

    try:
        r = await _query(
            "SELECT count() as cnt FROM spans "
            "WHERE start_time > now() - INTERVAL {minutes:UInt32} MINUTE "
            "AND is_deleted = 0 "
            "FORMAT JSON",
            {"param_minutes": str(minutes)},
        )
        if r.status_code == 200:
            tool_count = int(r.json().get("data", [{}])[0].get("cnt", 0))
    except Exception as e:
        logger.warning("clickhouse_query_spans_failed", error=str(e))

    try:
        r = await _query(
            "SELECT count() as cnt FROM traces "
            "WHERE start_time > now() - INTERVAL {minutes:UInt32} MINUTE "
            "AND is_deleted = 0 "
            "FORMAT JSON",
            {"param_minutes": str(minutes)},
        )
        if r.status_code == 200:
            agent_count = int(r.json().get("data", [{}])[0].get("cnt", 0))
    except Exception as e:
        logger.warning("clickhouse_query_traces_failed", error=str(e))

    return {"tool_call_events": tool_count, "agent_interaction_events": agent_count}


# --- Query functions for new tables ---


async def query_traces(
    project_id: str,
    *,
    trace_type: str | None = None,
    mcp_id: str | None = None,
    agent_id: str | None = None,
    user_id: str | None = None,
    agent_version: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Query traces with optional filters."""
    conditions = ["project_id = {pid:String}", "is_deleted = 0"]
    params: dict[str, str] = {"param_pid": project_id}
    if trace_type:
        conditions.append("trace_type = {tt:String}")
        params["param_tt"] = trace_type
    if mcp_id:
        conditions.append("mcp_id = {mid:String}")
        params["param_mid"] = mcp_id
    if agent_id:
        conditions.append("agent_id = {aid:String}")
        params["param_aid"] = agent_id
    if user_id:
        conditions.append("user_id = {uid:String}")
        params["param_uid"] = user_id
    if agent_version:
        conditions.append("agent_version = {av:String}")
        params["param_av"] = agent_version
    where = " AND ".join(conditions)
    sql = (
        f"SELECT * FROM traces FINAL WHERE {where} "
        f"ORDER BY start_time DESC LIMIT {int(limit)} OFFSET {int(offset)} FORMAT JSON"
    )
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("clickhouse_query_traces_failed", error=str(e))
        return []


async def query_trace_by_id(project_id: str, trace_id: str, *, user_id: str | None = None) -> dict | None:
    """Get a single trace by ID, optionally scoped to a user."""
    conditions = [
        "project_id = {pid:String}",
        "trace_id = {tid:String}",
        "is_deleted = 0",
    ]
    params: dict[str, str] = {"param_pid": project_id, "param_tid": trace_id}
    if user_id:
        conditions.append("user_id = {uid:String}")
        params["param_uid"] = user_id
    where = " AND ".join(conditions)
    sql = f"SELECT * FROM traces FINAL WHERE {where} LIMIT 1 FORMAT JSON"
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data[0] if data else None
    except Exception as e:
        logger.error("clickhouse_query_trace_by_id_failed", error=str(e))
        return None


async def query_spans(
    project_id: str,
    trace_id: str,
    *,
    span_type: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Query spans for a trace with optional filters."""
    conditions = [
        "project_id = {pid:String}",
        "trace_id = {tid:String}",
        "is_deleted = 0",
    ]
    params: dict[str, str] = {"param_pid": project_id, "param_tid": trace_id}
    if span_type:
        conditions.append("type = {st:String}")
        params["param_st"] = span_type
    if status:
        conditions.append("status = {status:String}")
        params["param_status"] = status
    where = " AND ".join(conditions)
    sql = f"SELECT * FROM spans FINAL WHERE {where} ORDER BY start_time ASC LIMIT {int(limit)} FORMAT JSON"
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("clickhouse_query_spans_failed", error=str(e))
        return []


async def query_span_by_id(project_id: str, span_id: str, *, user_id: str | None = None) -> dict | None:
    """Get a single span by ID, optionally scoped to a user."""
    conditions = [
        "project_id = {pid:String}",
        "span_id = {sid:String}",
        "is_deleted = 0",
    ]
    params: dict[str, str] = {"param_pid": project_id, "param_sid": span_id}
    if user_id:
        conditions.append("user_id = {uid:String}")
        params["param_uid"] = user_id
    where = " AND ".join(conditions)
    sql = f"SELECT * FROM spans FINAL WHERE {where} LIMIT 1 FORMAT JSON"
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data[0] if data else None
    except Exception as e:
        logger.error("clickhouse_query_span_by_id_failed", error=str(e))
        return None


async def query_shim_spans_for_window(
    user_id: str,
    start_time: str,
    end_time: str,
) -> list[dict]:
    """Fetch shim spans from the spans table that overlap a time window.

    Used for query-time side-load: when shim data has no session_id
    (because OBSERVAL_SESSION_ID wasn't set in the MCP server env),
    we fetch spans by user_id + time overlap and feed them into the
    merge logic alongside otel_logs events.

    Returns span rows with the columns needed to synthesize otel_logs-shaped events.
    """
    sql = (
        "SELECT "
        "span_id, trace_id, name, type, method, "
        "input, output, error, "
        "start_time, latency_ms, status, "
        "tools_available, tool_schema_valid, "
        "mcp_id "
        "FROM spans FINAL "
        "WHERE user_id = {uid:String} "
        "AND is_deleted = 0 "
        "AND type IN ("
        "  'tool_call', 'tool_list', 'initialize', "
        "  'resource_read', 'resource_list', 'resource_subscribe', "
        "  'prompt_get', 'prompt_list', 'ping', 'completion', 'config', 'other'"
        ") "
        "AND start_time >= parseDateTimeBestEffort({t_start:String}) - INTERVAL 2 SECOND "
        "AND start_time <= parseDateTimeBestEffort({t_end:String}) + INTERVAL 2 SECOND "
        "ORDER BY start_time ASC "
        "LIMIT 500 "
        "FORMAT JSON"
    )
    params = {
        "param_uid": user_id,
        "param_t_start": start_time,
        "param_t_end": end_time,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("clickhouse_query_shim_spans_failed", error=str(e))
        return []


async def query_scores(
    project_id: str,
    *,
    trace_id: str | None = None,
    span_id: str | None = None,
    source: str | None = None,
    name: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query scores with optional filters."""
    conditions = ["project_id = {pid:String}", "is_deleted = 0"]
    params: dict[str, str] = {"param_pid": project_id}
    if trace_id:
        conditions.append("trace_id = {tid:String}")
        params["param_tid"] = trace_id
    if span_id:
        conditions.append("span_id = {sid:String}")
        params["param_sid"] = span_id
    if source:
        conditions.append("source = {src:String}")
        params["param_src"] = source
    if name:
        conditions.append("name = {name:String}")
        params["param_name"] = name
    where = " AND ".join(conditions)
    sql = f"SELECT * FROM scores FINAL WHERE {where} ORDER BY timestamp DESC LIMIT {int(limit)} FORMAT JSON"
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("clickhouse_query_scores_failed", error=str(e))
        return []


async def insert_audit_log(events: list[dict]):
    """Batch insert audit log events into ClickHouse."""
    if not events:
        return
    lines = []
    for e in events:
        row = {
            "event_id": e["event_id"],
            "timestamp": _normalize_ts(e["timestamp"]),
            "actor_id": e.get("actor_id", ""),
            "actor_email": e.get("actor_email", ""),
            "actor_role": e.get("actor_role", ""),
            "action": e["action"],
            "resource_type": e.get("resource_type", ""),
            "resource_id": e.get("resource_id", ""),
            "resource_name": e.get("resource_name", ""),
            "http_method": e.get("http_method", ""),
            "http_path": e.get("http_path", ""),
            "status_code": e.get("status_code", 0),
            "ip_address": e.get("ip_address", ""),
            "user_agent": e.get("user_agent", ""),
            "detail": e.get("detail", ""),
        }
        lines.append(json.dumps(row, default=str))
    body = "\n".join(lines)
    sql = "INSERT INTO audit_log FORMAT JSONEachRow"
    try:
        r = await _query(sql, data=body)
        r.raise_for_status()
        await _invalidate_cache()
    except Exception as exc:
        logger.error("clickhouse_insert_audit_log_failed", error=str(exc))


async def _insert_webhook_deliveries(records: list[dict]):
    """Batch insert webhook delivery records into ClickHouse."""
    if not records:
        return
    lines = []
    for r in records:
        row = {
            "delivery_id": r["delivery_id"],
            "event_id": r["event_id"],
            "alert_rule_id": r["alert_rule_id"],
            "attempt_number": r["attempt_number"],
            "timestamp": _normalize_ts(r["timestamp"]),
            "webhook_url": r["webhook_url"],
            "status_code": r["status_code"],
            "delivery_status": r["delivery_status"],
            "error": r.get("error"),
            "duration_ms": r["duration_ms"],
            "payload_size": r["payload_size"],
        }
        lines.append(json.dumps(row, default=str))
    body = "\n".join(lines)
    sql = (
        "INSERT INTO webhook_deliveries (delivery_id, event_id, alert_rule_id, "
        "attempt_number, timestamp, webhook_url, status_code, delivery_status, "
        "error, duration_ms, payload_size) FORMAT JSONEachRow"
    )
    try:
        r = await _query(sql, data=body)
        r.raise_for_status()
    except Exception as exc:
        logger.error("clickhouse_insert_webhook_deliveries_failed", error=str(exc))


# --- Session events (JSONL ingest) ---


async def insert_session_events(rows: list[dict]):
    """Batch insert session event rows into ClickHouse using JSONEachRow."""
    if not rows:
        return
    lines = []
    for row in rows:
        lines.append(json.dumps(row, default=str))
    sql = (
        "INSERT INTO session_events (session_id, project_id, user_id, agent_id, "
        "agent_version, layer_hash, ide, line_offset, line_hash, event_type, timestamp, uuid, parent_uuid, "
        "tool_name, tool_id, content_preview, content_length, raw_line, credits, parent_session_id, "
        "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, model, raw_line_truncated) FORMAT JSONEachRow"
    )
    try:
        r = await _query(sql, data="\n".join(lines))
        r.raise_for_status()
        await _invalidate_cache()
    except Exception as e:
        logger.error("clickhouse_insert_session_events_failed", error=str(e))
        raise


async def query_session_event_count(session_id: str, project_id: str) -> tuple[int, int]:
    """Return (count, max_offset) for a session's stored events.

    Uses FINAL so ReplacingMergeTree dedup is applied before counting.
    Returns (0, -1) when no rows exist.
    """
    sql = (
        "SELECT count() AS cnt, max(line_offset) AS max_off "
        "FROM session_events FINAL "
        "WHERE session_id = {sid:String} AND project_id = {pid:String} "
        "FORMAT JSON"
    )
    params = {"param_sid": session_id, "param_pid": project_id}
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [{}])
        row = data[0] if data else {}
        count = int(row.get("cnt", 0))
        max_off = int(row.get("max_off", -1)) if count > 0 else -1
        return count, max_off
    except Exception as e:
        logger.error("clickhouse_query_session_event_count_failed", error=str(e))
        return 0, -1


async def query_existing_for_dedup(
    session_id: str,
    project_id: str,
    min_offset: int,
    max_offset: int,
) -> tuple[frozenset[int], frozenset[str]]:
    """Return (existing_offsets, existing_hashes) for the given session/range.

    Both sets are used together in ``ingest_session_lines`` to skip lines
    that have already been stored:

    * ``existing_offsets`` -- position-based check; catches rows ingested
      before ``line_hash`` was added (legacy rows have ``line_hash = ''``).
    * ``existing_hashes`` -- content-addressed check; catches the same bytes
      regardless of what ``line_offset`` the client assigned them, making
      dedup robust to off-by-one differences between IDE push implementations.

    Uses FINAL so ReplacingMergeTree dedup is applied before reading.
    Fail-open: returns (frozenset(), frozenset()) on any error so the ingest
    call can proceed normally.
    """
    if min_offset > max_offset:
        return frozenset(), frozenset()
    sql = (
        "SELECT line_offset, line_hash "
        "FROM session_events FINAL "
        "WHERE project_id = {pid:String} AND session_id = {sid:String} "
        "AND line_offset >= {min_off:UInt32} AND line_offset <= {max_off:UInt32} "
        "FORMAT JSON"
    )
    params = {
        "param_pid": project_id,
        "param_sid": session_id,
        "param_min_off": str(min_offset),
        "param_max_off": str(max_offset),
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        existing_offsets = frozenset(int(row["line_offset"]) for row in data)
        existing_hashes = frozenset(row["line_hash"] for row in data if row.get("line_hash"))
        return existing_offsets, existing_hashes
    except Exception as e:
        logger.warning("clickhouse_query_existing_for_dedup_failed", error=str(e))
        return frozenset(), frozenset()
