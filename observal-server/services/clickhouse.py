import json
import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import settings

logger = logging.getLogger(__name__)


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
        _client = httpx.AsyncClient(timeout=10)
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
    # Legacy tables (kept for backward compat)
    """CREATE TABLE IF NOT EXISTS mcp_tool_calls (
        event_id UUID,
        timestamp DateTime64(3, 'UTC'),
        mcp_server_id String,
        tool_name String,
        input_params String,
        response String,
        latency_ms UInt32,
        status String,
        user_action String,
        session_id String,
        user_id String,
        ide String
    ) ENGINE = MergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (mcp_server_id, timestamp)""",
    """CREATE TABLE IF NOT EXISTS agent_interactions (
        event_id UUID,
        timestamp DateTime64(3, 'UTC'),
        agent_id String,
        session_id String,
        tool_calls UInt32,
        user_action String,
        latency_ms UInt32,
        user_id String,
        ide String
    ) ENGINE = MergeTree()
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (agent_id, timestamp)""",
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
            logger.warning(f"ClickHouse init statement failed: {e}")

    # Apply admin-configured resource tuning from enterprise_config
    await apply_resource_settings()

    # Apply data retention TTL if configured
    retention_days = settings.DATA_RETENTION_DAYS
    if retention_days > 0:
        ttl_stmts = [
            f"ALTER TABLE traces MODIFY TTL toDate(start_time) + INTERVAL {retention_days} DAY",
            f"ALTER TABLE spans MODIFY TTL toDate(start_time) + INTERVAL {retention_days} DAY",
            f"ALTER TABLE scores MODIFY TTL toDate(timestamp) + INTERVAL {retention_days} DAY",
            f"ALTER TABLE mcp_tool_calls MODIFY TTL toDate(timestamp) + INTERVAL {retention_days} DAY",
            f"ALTER TABLE agent_interactions MODIFY TTL toDate(timestamp) + INTERVAL {retention_days} DAY",
        ]
        applied = 0
        for stmt in ttl_stmts:
            try:
                await _query(stmt)
                applied += 1
            except Exception as e:
                logger.warning(f"ClickHouse TTL configuration failed: {e}")
        if applied == len(ttl_stmts):
            logger.info("ClickHouse retention set to %d days", retention_days)
        else:
            logger.warning("ClickHouse retention partially applied: %d/%d tables", applied, len(ttl_stmts))
    else:
        logger.info("ClickHouse data retention disabled (DATA_RETENTION_DAYS=0)")


async def insert_tool_call(event: dict):
    sql = """INSERT INTO mcp_tool_calls
        (event_id, timestamp, mcp_server_id, tool_name, input_params, response, latency_ms, status, user_action, session_id, user_id, ide)
        VALUES
        ({event_id:String}, {ts:String}, {mcp_server_id:String}, {tool_name:String}, {input_params:String}, {response:String}, {latency_ms:UInt32}, {status:String}, {user_action:String}, {session_id:String}, {user_id:String}, {ide:String})"""
    params = {
        "param_event_id": event["event_id"],
        "param_ts": event["timestamp"],
        "param_mcp_server_id": event.get("mcp_server_id", ""),
        "param_tool_name": event.get("tool_name", ""),
        "param_input_params": event.get("input_params", ""),
        "param_response": event.get("response", ""),
        "param_latency_ms": str(event.get("latency_ms", 0)),
        "param_status": event.get("status", ""),
        "param_user_action": event.get("user_action", ""),
        "param_session_id": event.get("session_id", ""),
        "param_user_id": event.get("user_id", ""),
        "param_ide": event.get("ide", ""),
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        await _invalidate_cache()
    except Exception as e:
        logger.error(f"ClickHouse insert_tool_call failed: {e}")
        raise


async def insert_agent_interaction(event: dict):
    sql = """INSERT INTO agent_interactions
        (event_id, timestamp, agent_id, session_id, tool_calls, user_action, latency_ms, user_id, ide)
        VALUES
        ({event_id:String}, {ts:String}, {agent_id:String}, {session_id:String}, {tool_calls:UInt32}, {user_action:String}, {latency_ms:UInt32}, {user_id:String}, {ide:String})"""
    params = {
        "param_event_id": event["event_id"],
        "param_ts": event["timestamp"],
        "param_agent_id": event.get("agent_id", ""),
        "param_session_id": event.get("session_id", ""),
        "param_tool_calls": str(event.get("tool_calls", 0)),
        "param_user_action": event.get("user_action", ""),
        "param_latency_ms": str(event.get("latency_ms", 0)),
        "param_user_id": event.get("user_id", ""),
        "param_ide": event.get("ide", ""),
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        await _invalidate_cache()
    except Exception as e:
        logger.error(f"ClickHouse insert_agent_interaction failed: {e}")
        raise


def _now_ms() -> str:
    """Current UTC timestamp as ISO string with millisecond precision."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


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
            "start_time": t["start_time"],
            "end_time": t.get("end_time"),
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
        }
        lines.append(json.dumps(row, default=str))
    sql = (
        "INSERT INTO traces (trace_id, parent_trace_id, project_id, mcp_id, agent_id, "
        "user_id, session_id, ide, environment, start_time, end_time, trace_type, name, "
        "metadata, tags, input, output, event_ts, is_deleted, "
        "tool_id, sandbox_id, graphrag_id, hook_id, skill_id, prompt_id) FORMAT JSONEachRow"
    )
    try:
        r = await _query(sql, data="\n".join(lines))
        r.raise_for_status()
        await _invalidate_cache()
    except Exception as e:
        logger.error(f"ClickHouse insert_traces failed: {e}")
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
            "start_time": s["start_time"],
            "end_time": s.get("end_time"),
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
        "variables_provided, template_tokens, rendered_tokens) FORMAT JSONEachRow"
    )
    try:
        r = await _query(sql, data="\n".join(lines))
        r.raise_for_status()
        await _invalidate_cache()
    except Exception as e:
        logger.error(f"ClickHouse insert_spans failed: {e}")
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
            "timestamp": sc["timestamp"],
            "event_ts": event_ts,
            "is_deleted": 0,
        }
        lines.append(json.dumps(row, default=str))
    sql = (
        "INSERT INTO scores (score_id, trace_id, span_id, project_id, mcp_id, agent_id, "
        "user_id, name, source, data_type, value, string_value, comment, "
        "eval_template_id, eval_config_id, eval_run_id, environment, metadata, "
        "timestamp, event_ts, is_deleted) FORMAT JSONEachRow"
    )
    try:
        r = await _query(sql, data="\n".join(lines))
        r.raise_for_status()
        await _invalidate_cache()
    except Exception as e:
        logger.error(f"ClickHouse insert_scores failed: {e}")
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
            "Timestamp": r["Timestamp"],
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
        logger.error(f"ClickHouse insert_otel_logs failed: {e}")
        raise


async def query_recent_events(minutes: int = 60) -> dict:
    """Get event counts from the last N minutes."""
    minutes = int(minutes)
    tool_count = 0
    agent_count = 0

    try:
        r = await _query(
            "SELECT count() as cnt FROM mcp_tool_calls WHERE timestamp > now() - INTERVAL {minutes:UInt32} MINUTE FORMAT JSON",
            {"param_minutes": str(minutes)},
        )
        if r.status_code == 200:
            tool_count = int(r.json().get("data", [{}])[0].get("cnt", 0))
    except Exception as e:
        logger.warning(f"ClickHouse query tool_calls failed: {e}")

    try:
        r = await _query(
            "SELECT count() as cnt FROM agent_interactions WHERE timestamp > now() - INTERVAL {minutes:UInt32} MINUTE FORMAT JSON",
            {"param_minutes": str(minutes)},
        )
        if r.status_code == 200:
            agent_count = int(r.json().get("data", [{}])[0].get("cnt", 0))
    except Exception as e:
        logger.warning(f"ClickHouse query agent_interactions failed: {e}")

    return {"tool_call_events": tool_count, "agent_interaction_events": agent_count}


# --- Query functions for new tables ---


async def query_traces(
    project_id: str,
    *,
    trace_type: str | None = None,
    mcp_id: str | None = None,
    agent_id: str | None = None,
    user_id: str | None = None,
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
        logger.error(f"ClickHouse query_traces failed: {e}")
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
        logger.error(f"ClickHouse query_trace_by_id failed: {e}")
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
        logger.error(f"ClickHouse query_spans failed: {e}")
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
        logger.error(f"ClickHouse query_span_by_id failed: {e}")
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
        logger.error(f"ClickHouse query_shim_spans_for_window failed: {e}")
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
        logger.error(f"ClickHouse query_scores failed: {e}")
        return []


async def insert_audit_log(events: list[dict]):
    """Batch insert audit log events into ClickHouse."""
    if not events:
        return
    lines = []
    for e in events:
        row = {
            "event_id": e["event_id"],
            "timestamp": e["timestamp"],
            "actor_id": e.get("actor_id", ""),
            "actor_email": e.get("actor_email", ""),
            "actor_role": e.get("actor_role", ""),
            "action": e["action"],
            "resource_type": e.get("resource_type", ""),
            "resource_id": e.get("resource_id", ""),
            "resource_name": e.get("resource_name", ""),
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
        logger.error(f"ClickHouse insert_audit_log failed: {exc}")


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
            "timestamp": r["timestamp"],
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
        logger.error(f"ClickHouse _insert_webhook_deliveries failed: {exc}")
