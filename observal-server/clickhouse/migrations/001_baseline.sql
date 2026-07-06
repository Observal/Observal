# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

DROP TABLE IF EXISTS traces
;

DROP TABLE IF EXISTS spans
;

DROP TABLE IF EXISTS scores
;

DROP TABLE IF EXISTS otel_logs
;

CREATE TABLE IF NOT EXISTS security_events (
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
    ORDER BY (event_type, severity, timestamp)
;

CREATE TABLE IF NOT EXISTS audit_log (
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
    ORDER BY (action, resource_type, timestamp)
;

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS org_id String DEFAULT ''
;

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS sensitivity LowCardinality(String) DEFAULT 'standard'
;

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS request_id String DEFAULT ''
;

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS outcome LowCardinality(String) DEFAULT ''
;

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS duration_ms Float32 DEFAULT 0
;

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS chain_hash String DEFAULT ''
;

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS source LowCardinality(String) DEFAULT 'server'
;

ALTER TABLE audit_log ADD INDEX IF NOT EXISTS idx_outcome outcome TYPE bloom_filter(0.01) GRANULARITY 1
;

ALTER TABLE audit_log ADD INDEX IF NOT EXISTS idx_sensitivity sensitivity TYPE bloom_filter(0.01) GRANULARITY 1
;

ALTER TABLE audit_log ADD INDEX IF NOT EXISTS idx_org_id org_id TYPE bloom_filter(0.01) GRANULARITY 1
;

ALTER TABLE audit_log ADD INDEX IF NOT EXISTS idx_source source TYPE bloom_filter(0.01) GRANULARITY 1
;

CREATE TABLE IF NOT EXISTS webhook_deliveries (
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
    ORDER BY (alert_rule_id, timestamp)
;

CREATE TABLE IF NOT EXISTS session_events (
        session_id      String,
        project_id      String,
        user_id         String,
        agent_id        Nullable(String),
        agent_version   Nullable(String),
        layer_hash      Nullable(String),
        harness             LowCardinality(String),
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
        INDEX idx_se_event_type event_type TYPE set(20) GRANULARITY 1,
        INDEX idx_se_line_hash line_hash TYPE bloom_filter(0.001) GRANULARITY 1
    ) ENGINE = ReplacingMergeTree(ingested_at)
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (project_id, session_id, line_offset)
;

ALTER TABLE session_events ADD COLUMN IF NOT EXISTS parent_session_id Nullable(String)
;

ALTER TABLE session_events ADD INDEX IF NOT EXISTS idx_se_parent_session_id parent_session_id TYPE set(0) GRANULARITY 1
;

ALTER TABLE session_events ADD COLUMN IF NOT EXISTS input_tokens Int32 DEFAULT 0
;

ALTER TABLE session_events ADD COLUMN IF NOT EXISTS output_tokens Int32 DEFAULT 0
;

ALTER TABLE session_events ADD COLUMN IF NOT EXISTS cache_read_tokens Int32 DEFAULT 0
;

ALTER TABLE session_events ADD COLUMN IF NOT EXISTS cache_write_tokens Int32 DEFAULT 0
;

ALTER TABLE session_events ADD COLUMN IF NOT EXISTS model LowCardinality(String) DEFAULT ''
;

ALTER TABLE session_events ADD COLUMN IF NOT EXISTS raw_line_truncated UInt8 DEFAULT 0
;

CREATE TABLE IF NOT EXISTS session_stats_agg (
        project_id          String,
        session_id          String,
        agent_id            LowCardinality(String) DEFAULT '',
        agent_version       LowCardinality(String) DEFAULT '',
        user_id             String                 DEFAULT '',
        parent_session_id   String                 DEFAULT '',
        harness                 LowCardinality(String) DEFAULT '',
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
    ORDER BY (project_id, session_id)
;

CREATE MATERIALIZED VIEW IF NOT EXISTS session_stats_mv
    TO session_stats_agg AS
    SELECT
        project_id,
        session_id,
        coalesce(anyIf(agent_id, agent_id IS NOT NULL AND agent_id != ''), '') AS agent_id,
        coalesce(anyIf(user_id, user_id != ''), '')                             AS user_id,
        coalesce(anyIf(parent_session_id, parent_session_id IS NOT NULL AND parent_session_id != ''), '') AS parent_session_id,
        coalesce(anyIf(harness, harness != ''), '')                                     AS harness,
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
    GROUP BY project_id, session_id
;

ALTER TABLE session_events MODIFY COLUMN raw_line String TTL timestamp + INTERVAL 30 DAY
;

ALTER TABLE session_events ADD INDEX IF NOT EXISTS idx_se_event_type event_type TYPE set(20) GRANULARITY 1
;

ALTER TABLE session_events ADD INDEX IF NOT EXISTS idx_se_parent_session_id parent_session_id TYPE set(0) GRANULARITY 1
;


DROP VIEW IF EXISTS session_stats_mv
;

ALTER TABLE session_stats_agg MODIFY COLUMN total_credits SimpleAggregateFunction(max, Float64)
;

CREATE MATERIALIZED VIEW IF NOT EXISTS session_stats_mv
    TO session_stats_agg AS
    SELECT
        project_id,
        session_id,
        coalesce(anyIf(agent_id, agent_id IS NOT NULL AND agent_id != ''), '') AS agent_id,
        coalesce(anyIf(agent_version, agent_version IS NOT NULL AND agent_version != ''), '') AS agent_version,
        coalesce(anyIf(user_id, user_id != ''), '')                             AS user_id,
        coalesce(anyIf(parent_session_id, parent_session_id IS NOT NULL AND parent_session_id != ''), '') AS parent_session_id,
        coalesce(anyIf(harness, harness != ''), '')                                     AS harness,
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
    GROUP BY project_id, session_id
;

ALTER TABLE session_stats_agg ADD COLUMN IF NOT EXISTS layer_hash String DEFAULT ''
;

ALTER TABLE session_stats_agg ADD COLUMN IF NOT EXISTS agent_version LowCardinality(String) DEFAULT ''
;

ALTER TABLE session_stats_agg ADD INDEX IF NOT EXISTS idx_ssa_agent_version agent_version TYPE bloom_filter(0.01) GRANULARITY 1
;

DROP VIEW IF EXISTS session_stats_mv
;

CREATE MATERIALIZED VIEW IF NOT EXISTS session_stats_mv
    TO session_stats_agg AS
    SELECT
        project_id,
        session_id,
        coalesce(anyIf(agent_id, agent_id IS NOT NULL AND agent_id != ''), '') AS agent_id,
        coalesce(anyIf(agent_version, agent_version IS NOT NULL AND agent_version != ''), '') AS agent_version,
        coalesce(anyIf(user_id, user_id != ''), '')                             AS user_id,
        coalesce(anyIf(parent_session_id, parent_session_id IS NOT NULL AND parent_session_id != ''), '') AS parent_session_id,
        coalesce(anyIf(harness, harness != ''), '')                                     AS harness,
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
    GROUP BY project_id, session_id
;

CREATE TABLE IF NOT EXISTS layer_snapshots (
        hash            String,
        project_id      String,
        user_id         String,
        harness             LowCardinality(String),
        content         String CODEC(ZSTD(3)),
        uploaded_at     DateTime64(3, 'UTC') DEFAULT now(),
        file_count      UInt16,
        total_size      UInt32,
        lockfile_hash   String DEFAULT ''
    ) ENGINE = ReplacingMergeTree(uploaded_at)
    ORDER BY (project_id, user_id, hash)
;
