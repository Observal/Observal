# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""ClickHouse DDL, table initialization, and resource-tuning settings.

Note: INIT_SQL is large by necessity (DDL for 10 tables + ALTER migrations).
The module intentionally exceeds the 350-line target from refactor.md S1.3;
the SQL constant cannot be compressed further.
"""

from loguru import logger as optic

import services.clickhouse._settings as _ch_settings
import services.clickhouse.client as _client

# ── DDL ───────────────────────────────────────────────────────────────────────

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
    # Security events table (SIEM integration - SOC 2 / ISO 27001)
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
    # Audit log table (enterprise compliance - SOC 2 / ISO 27001)
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
    # Audit log schema expansion
    """ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS org_id String DEFAULT ''""",
    """ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS sensitivity LowCardinality(String) DEFAULT 'standard'""",
    """ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS request_id String DEFAULT ''""",
    """ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS outcome LowCardinality(String) DEFAULT ''""",
    """ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS duration_ms Float32 DEFAULT 0""",
    """ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS chain_hash String DEFAULT ''""",
    """ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS source LowCardinality(String) DEFAULT 'server'""",
    """ALTER TABLE audit_log ADD INDEX IF NOT EXISTS idx_outcome outcome TYPE bloom_filter(0.01) GRANULARITY 1""",
    """ALTER TABLE audit_log ADD INDEX IF NOT EXISTS idx_sensitivity sensitivity TYPE bloom_filter(0.01) GRANULARITY 1""",
    """ALTER TABLE audit_log ADD INDEX IF NOT EXISTS idx_org_id org_id TYPE bloom_filter(0.01) GRANULARITY 1""",
    """ALTER TABLE audit_log ADD INDEX IF NOT EXISTS idx_source source TYPE bloom_filter(0.01) GRANULARITY 1""",
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
    # set(0) is exact-match with unlimited cardinality - ideal for sparse equality lookups.
    """ALTER TABLE session_events ADD INDEX IF NOT EXISTS idx_se_parent_session_id parent_session_id TYPE set(0) GRANULARITY 1""",
    # Materialized token / model columns - extract at ingest, avoid JSONExtract at query time.
    # Default 0 / '' so existing rows remain queryable without rewriting.
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS input_tokens Int32 DEFAULT 0""",
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS output_tokens Int32 DEFAULT 0""",
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS cache_read_tokens Int32 DEFAULT 0""",
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS cache_write_tokens Int32 DEFAULT 0""",
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS model LowCardinality(String) DEFAULT ''""",
    # raw_line size guard - 1 when the original line exceeded RAW_LINE_MAX_BYTES and was truncated.
    """ALTER TABLE session_events ADD COLUMN IF NOT EXISTS raw_line_truncated UInt8 DEFAULT 0""",
    # Pre-aggregated session stats - AggregatingMergeTree table + materialized view.
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
        agent_version       LowCardinality(String) DEFAULT '',
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
    PARTITION BY toYYYYMM(first_event_time)
    ORDER BY (project_id, session_id)""",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS session_stats_mv
    TO session_stats_agg AS
    SELECT
        project_id,
        session_id,
        coalesce(anyIf(agent_id, agent_id IS NOT NULL AND agent_id != ''), '') AS agent_id,
        coalesce(anyIf(user_id, user_id != ''), '')                             AS user_id,
        coalesce(anyIf(parent_session_id, parent_session_id IS NOT NULL AND parent_session_id != ''), '') AS parent_session_id,
        coalesce(anyIf(ide, ide != ''), '')                                     AS ide,
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
    # Source: clickhouse.com/docs/guides/developer/ttl - column TTL expression pattern.
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
    # set(0) stores exact values per block with no size cap - correct for equality
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
    # ── Fix Kiro credits double-counting ───────────────────────────────────────
    # The credits row is idempotent (same line_offset=0xFFFFFFFF, ReplacingMergeTree
    # deduplicates), but the MV fires on each INSERT, so sum() accumulated
    # duplicate credits. Switch to max() since each push writes cumulative total.
    """DROP VIEW IF EXISTS session_stats_mv""",
    """ALTER TABLE session_stats_agg MODIFY COLUMN total_credits SimpleAggregateFunction(max, Float64)""",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS session_stats_mv
    TO session_stats_agg AS
    SELECT
        project_id,
        session_id,
        coalesce(anyIf(agent_id, agent_id IS NOT NULL AND agent_id != ''), '') AS agent_id,
        coalesce(anyIf(agent_version, agent_version IS NOT NULL AND agent_version != ''), '') AS agent_version,
        coalesce(anyIf(user_id, user_id != ''), '')                             AS user_id,
        coalesce(anyIf(parent_session_id, parent_session_id IS NOT NULL AND parent_session_id != ''), '') AS parent_session_id,
        coalesce(anyIf(ide, ide != ''), '')                                     AS ide,
        minIf(timestamp, timestamp > '1971-01-01 00:00:00' AND timestamp < '2099-01-01 00:00:00') AS first_event_time,
        maxIf(timestamp, timestamp > '1971-01-01 00:00:00' AND timestamp < '2099-01-01 00:00:00') AS last_event_time,
        count()                               AS event_count,
        countIf(event_type = 'user_prompt')   AS prompt_count,
        countIf(event_type = 'tool_call')     AS tool_call_count,
        countIf(event_type = 'tool_result')   AS tool_result_count,
        sum(input_tokens)                     AS input_tokens,
        sum(output_tokens)                    AS output_tokens,
        sum(cache_read_tokens)                AS cache_read_tokens,
        sum(cache_write_tokens)               AS cache_write_tokens,
        max(credits)                          AS total_credits,
        anyLastIf(model, model != '')         AS model
    FROM session_events
    GROUP BY project_id, session_id""",
    # ── Poisoned timestamp fix (applied once, now a no-op) ──────────────────────
    # Previously this TRUNCATED session_stats_agg and backfilled on every deploy,
    # wiping all trace data. Removed: the partition migration handles backfill
    # correctly and only runs once. The MV filters timestamps going forward.
    # ── Add layer_hash and agent_version to session_stats_agg for version-aware insights ─────────
    """ALTER TABLE session_stats_agg ADD COLUMN IF NOT EXISTS layer_hash String DEFAULT ''""",
    """ALTER TABLE session_stats_agg ADD COLUMN IF NOT EXISTS agent_version LowCardinality(String) DEFAULT ''""",
    """ALTER TABLE session_stats_agg ADD INDEX IF NOT EXISTS idx_ssa_agent_version agent_version TYPE bloom_filter(0.01) GRANULARITY 1""",
    """DROP VIEW IF EXISTS session_stats_mv""",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS session_stats_mv
    TO session_stats_agg AS
    SELECT
        project_id,
        session_id,
        coalesce(anyIf(agent_id, agent_id IS NOT NULL AND agent_id != ''), '') AS agent_id,
        coalesce(anyIf(agent_version, agent_version IS NOT NULL AND agent_version != ''), '') AS agent_version,
        coalesce(anyIf(user_id, user_id != ''), '')                             AS user_id,
        coalesce(anyIf(parent_session_id, parent_session_id IS NOT NULL AND parent_session_id != ''), '') AS parent_session_id,
        coalesce(anyIf(ide, ide != ''), '')                                     AS ide,
        coalesce(anyIf(layer_hash, layer_hash IS NOT NULL AND layer_hash != ''), '') AS layer_hash,
        minIf(timestamp, timestamp > '1971-01-01 00:00:00' AND timestamp < '2099-01-01 00:00:00') AS first_event_time,
        maxIf(timestamp, timestamp > '1971-01-01 00:00:00' AND timestamp < '2099-01-01 00:00:00') AS last_event_time,
        count()                               AS event_count,
        countIf(event_type = 'user_prompt')   AS prompt_count,
        countIf(event_type = 'tool_call')     AS tool_call_count,
        countIf(event_type = 'tool_result')   AS tool_result_count,
        sum(input_tokens)                     AS input_tokens,
        sum(output_tokens)                    AS output_tokens,
        sum(cache_read_tokens)                AS cache_read_tokens,
        sum(cache_write_tokens)               AS cache_write_tokens,
        max(credits)                          AS total_credits,
        anyLastIf(model, model != '')         AS model
    FROM session_events
    GROUP BY project_id, session_id""",
    # Layer snapshots: stores full IDE config manifests for version-aware insights.
    # Keyed by (project_id, user_id, hash). ReplacingMergeTree deduplicates.
    """CREATE TABLE IF NOT EXISTS layer_snapshots (
        hash            String,
        project_id      String,
        user_id         String,
        ide             LowCardinality(String),
        content         String CODEC(ZSTD(3)),
        uploaded_at     DateTime64(3, 'UTC') DEFAULT now(),
        file_count      UInt16,
        total_size      UInt32,
        lockfile_hash   String DEFAULT ''
    ) ENGINE = ReplacingMergeTree(uploaded_at)
    ORDER BY (project_id, user_id, hash)""",
]

# ── Resource tuning ───────────────────────────────────────────────────────────

# Maps enterprise_config keys to ClickHouse SET-able settings.
# Only whitelisted settings are accepted to avoid SQL injection.
RESOURCE_SETTINGS_MAP: dict[str, tuple[str, type]] = {
    "resource.max_query_memory_mb": ("max_memory_usage", int),
    "resource.group_by_spill_mb": ("max_bytes_before_external_group_by", int),
    "resource.sort_spill_mb": ("max_bytes_before_external_sort", int),
    "resource.join_memory_mb": ("max_bytes_in_join", int),
}


# Re-export for backwards compat (tests and __init__ reference these)
DEFAULT_QUERY_SETTINGS = _ch_settings.DEFAULT_QUERY_SETTINGS
_resource_overrides = _ch_settings._resource_overrides


async def apply_resource_settings(overrides: dict[str, str] | None = None):
    """Load resource tuning settings and inject them into every ClickHouse query.

    Reads from enterprise_config (Postgres) unless *overrides* is supplied.
    """
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
            optic.warning("could not read resource settings from DB (using defaults): {}", e)

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
            optic.warning("invalid resource setting {}={}, skipping", config_key, raw)

    _ch_settings._resource_overrides.clear()
    _ch_settings._resource_overrides.update(new_overrides)
    optic.info("ClickHouse resource overrides applied: {}", new_overrides)


async def _materialize_if_needed():
    """Conditionally materialize projection and indexes on session_events.

    Only runs MATERIALIZE commands when parts exist that lack the projection
    or indexes. Avoids creating new mutations on every server restart.
    """
    try:
        r = await _client._query(
            "SELECT count() AS cnt FROM system.parts "
            "WHERE table = 'session_events' AND database = currentDatabase() "
            "AND active AND NOT has(projections, 'proj_session_view') "
            "FORMAT JSON"
        )
        if r.status_code == 200:
            data = r.json().get("data", [{}])
            if int(data[0].get("cnt", 0)) > 0:
                await _client._query("ALTER TABLE session_events MATERIALIZE PROJECTION proj_session_view")
                optic.info("materialized proj_session_view projection on existing parts")
    except Exception as e:
        optic.warning("could not check projection status: {}", e)

    for idx_name in ("idx_se_event_type", "idx_se_parent_session_id"):
        try:
            r = await _client._query(
                "SELECT count() AS cnt FROM system.parts "
                "WHERE table = 'session_events' AND database = currentDatabase() "
                f"AND active AND NOT has(data_skipping_indices, '{idx_name}') "
                "FORMAT JSON"
            )
            if r.status_code == 200:
                data = r.json().get("data", [{}])
                if int(data[0].get("cnt", 0)) > 0:
                    await _client._query(f"ALTER TABLE session_events MATERIALIZE INDEX {idx_name}")
                    optic.info("materialized index {} on existing parts", idx_name)
        except Exception as e:
            optic.warning("could not check index {} status: {}", idx_name, e)


async def _migrate_session_stats_partition():
    """One-time migration: add PARTITION BY to session_stats_agg if missing.

    Checks system.tables for partition_key. If empty (old schema), drops and
    recreates the table with monthly partitioning, recreates the MV, and
    backfills from session_events. Idempotent: no-op if already partitioned.
    """
    import json

    resp = await _client._query(
        "SELECT partition_key FROM system.tables "
        "WHERE database = currentDatabase() AND name = 'session_stats_agg' "
        "FORMAT JSONEachRow"
    )
    if not resp or resp.status_code >= 400 or not resp.text.strip():
        return  # Table doesn't exist (fresh install will create via INIT_SQL)

    rows = [json.loads(line) for line in resp.text.strip().splitlines() if line.strip()]
    if not rows:
        return

    if rows[0].get("partition_key", ""):
        optic.debug("session_stats_agg already partitioned, skipping migration")
        return

    optic.info("migrating session_stats_agg: adding PARTITION BY toYYYYMM(first_event_time)")

    steps = [
        "DROP VIEW IF EXISTS session_stats_mv",
        "DROP TABLE IF EXISTS session_stats_agg",
        """CREATE TABLE session_stats_agg (
            project_id          String,
            session_id          String,
            agent_id            LowCardinality(String) DEFAULT '',
            agent_version       LowCardinality(String) DEFAULT '',
            user_id             String                 DEFAULT '',
            parent_session_id   String                 DEFAULT '',
            ide                 LowCardinality(String) DEFAULT '',
            layer_hash          String                 DEFAULT '',
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
            total_credits       SimpleAggregateFunction(max,     Float64),
            model               SimpleAggregateFunction(anyLast, String),
            INDEX idx_ssa_user_id       user_id       TYPE bloom_filter(0.01) GRANULARITY 1,
            INDEX idx_ssa_agent_id      agent_id      TYPE bloom_filter(0.01) GRANULARITY 1,
            INDEX idx_ssa_agent_version agent_version TYPE bloom_filter(0.01) GRANULARITY 1
        ) ENGINE = AggregatingMergeTree()
        PARTITION BY toYYYYMM(first_event_time)
        ORDER BY (project_id, session_id)""",
        """CREATE MATERIALIZED VIEW session_stats_mv
        TO session_stats_agg AS
        SELECT
            project_id, session_id,
            coalesce(anyIf(agent_id, agent_id IS NOT NULL AND agent_id != ''), '') AS agent_id,
            coalesce(anyIf(agent_version, agent_version IS NOT NULL AND agent_version != ''), '') AS agent_version,
            coalesce(anyIf(user_id, user_id != ''), '') AS user_id,
            coalesce(anyIf(parent_session_id, parent_session_id IS NOT NULL AND parent_session_id != ''), '') AS parent_session_id,
            coalesce(anyIf(ide, ide != ''), '') AS ide,
            coalesce(anyIf(layer_hash, layer_hash IS NOT NULL AND layer_hash != ''), '') AS layer_hash,
            minIf(timestamp, timestamp > '1971-01-01' AND timestamp < '2099-01-01') AS first_event_time,
            maxIf(timestamp, timestamp > '1971-01-01' AND timestamp < '2099-01-01') AS last_event_time,
            count() AS event_count,
            countIf(event_type = 'user_prompt') AS prompt_count,
            countIf(event_type = 'tool_call') AS tool_call_count,
            countIf(event_type = 'tool_result') AS tool_result_count,
            sum(input_tokens) AS input_tokens,
            sum(output_tokens) AS output_tokens,
            sum(cache_read_tokens) AS cache_read_tokens,
            sum(cache_write_tokens) AS cache_write_tokens,
            max(credits) AS total_credits,
            anyLastIf(model, model != '') AS model
        FROM session_events
        GROUP BY project_id, session_id""",
        """INSERT INTO session_stats_agg
        SELECT
            project_id, session_id,
            coalesce(anyIf(agent_id, agent_id IS NOT NULL AND agent_id != ''), '') AS agent_id,
            coalesce(anyIf(agent_version, agent_version IS NOT NULL AND agent_version != ''), '') AS agent_version,
            coalesce(anyIf(user_id, user_id != ''), '') AS user_id,
            coalesce(anyIf(parent_session_id, parent_session_id IS NOT NULL AND parent_session_id != ''), '') AS parent_session_id,
            coalesce(anyIf(ide, ide != ''), '') AS ide,
            coalesce(anyIf(layer_hash, layer_hash IS NOT NULL AND layer_hash != ''), '') AS layer_hash,
            minIf(timestamp, timestamp > '1971-01-01' AND timestamp < '2099-01-01') AS first_event_time,
            maxIf(timestamp, timestamp > '1971-01-01' AND timestamp < '2099-01-01') AS last_event_time,
            count() AS event_count,
            countIf(event_type = 'user_prompt') AS prompt_count,
            countIf(event_type = 'tool_call') AS tool_call_count,
            countIf(event_type = 'tool_result') AS tool_result_count,
            sum(input_tokens) AS input_tokens,
            sum(output_tokens) AS output_tokens,
            sum(cache_read_tokens) AS cache_read_tokens,
            sum(cache_write_tokens) AS cache_write_tokens,
            max(credits) AS total_credits,
            anyLastIf(model, model != '') AS model
        FROM session_events
        GROUP BY project_id, session_id""",
    ]

    try:
        for stmt in steps:
            await _client._query(stmt)
    except Exception as e:
        optic.error(
            "session_stats_agg partition migration FAILED mid-way: {} "
            "— table may be in inconsistent state, manual intervention required",
            e,
        )
        raise

    optic.info("session_stats_agg partition migration complete")


async def init_clickhouse():
    """Create ClickHouse tables if they don't exist and configure retention.

    Raises on unreachable server so startup fails fast.
    """
    optic.info("initializing ClickHouse schema")
    from services.clickhouse.client import clickhouse_health

    if not await clickhouse_health():
        raise RuntimeError(f"ClickHouse unreachable at {_client.CLICKHOUSE_HTTP}")

    for stmt in INIT_SQL:
        try:
            await _client._query(stmt)
        except Exception as e:
            optic.warning("DDL statement failed (may be harmless if already applied): {}", str(e)[:120])

    await _migrate_session_stats_partition()
    await _materialize_if_needed()
    await apply_resource_settings()

    import services.dynamic_settings as ds

    retention_days = await ds.get_int("data.retention_days")
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
                await _client._query(stmt)
                applied += 1
            except Exception as e:
                optic.warning("TTL statement failed: {}", e)
        if applied == len(ttl_stmts):
            optic.info("ClickHouse retention configured: {} days across all tables", retention_days)
        else:
            optic.warning(
                "retention only applied to {}/{} tables - some data may not auto-expire", applied, len(ttl_stmts)
            )
    else:
        optic.info("data retention disabled (retention_days=0), data kept indefinitely")
