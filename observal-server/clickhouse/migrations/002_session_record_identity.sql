# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

DROP VIEW IF EXISTS session_stats_mv;

CREATE TABLE IF NOT EXISTS session_events_v2 (
    session_id          String,
    project_id          String,
    user_id             String,
    agent_id            Nullable(String),
    agent_version       Nullable(String),
    layer_hash          Nullable(String),
    harness             LowCardinality(String),
    line_offset         UInt32,
    source_end_offset   UInt64 DEFAULT 0,
    line_hash           String DEFAULT '' CODEC(ZSTD(1)),
    is_source_record    UInt8 DEFAULT 1,
    rendered            UInt8 DEFAULT 1,
    event_type          LowCardinality(String),
    timestamp           DateTime64(3, 'UTC'),
    uuid                Nullable(String),
    parent_uuid         Nullable(String),
    tool_name           Nullable(String),
    tool_id             Nullable(String),
    content_preview     String CODEC(ZSTD(1)),
    content_length      UInt32,
    raw_line            String CODEC(ZSTD(3)),
    ingested_at         DateTime64(3, 'UTC') DEFAULT now64(3),
    credits             Float64 DEFAULT 0,
    parent_session_id   Nullable(String),
    input_tokens        Int32 DEFAULT 0,
    output_tokens       Int32 DEFAULT 0,
    cache_read_tokens   Int32 DEFAULT 0,
    cache_write_tokens  Int32 DEFAULT 0,
    model               LowCardinality(String) DEFAULT '',
    raw_line_truncated  UInt8 DEFAULT 0,
    INDEX idx_se_session_id session_id TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_se_project_id project_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_se_user_id user_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_se_event_type event_type TYPE set(20) GRANULARITY 1,
    INDEX idx_se_line_hash line_hash TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_se_parent_session_id parent_session_id TYPE set(0) GRANULARITY 1
) ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(timestamp)
ORDER BY (project_id, user_id, harness, session_id, line_offset);

INSERT INTO session_events_v2
SELECT
    session_id,
    project_id,
    user_id,
    agent_id,
    agent_version,
    layer_hash,
    harness,
    line_offset,
    toUInt64(0) AS source_end_offset,
    line_hash,
    toUInt8(event_type != 'kiro_credits') AS is_source_record,
    toUInt8(1) AS rendered,
    event_type,
    timestamp,
    uuid,
    parent_uuid,
    tool_name,
    tool_id,
    content_preview,
    content_length,
    raw_line,
    ingested_at,
    credits,
    parent_session_id,
    input_tokens,
    output_tokens,
    cache_read_tokens,
    cache_write_tokens,
    model,
    raw_line_truncated
FROM session_events FINAL;

RENAME TABLE session_events TO session_events_pre_002, session_events_v2 TO session_events;

DROP TABLE session_events_pre_002;

CREATE TABLE IF NOT EXISTS session_checkpoints (
    project_id          String,
    user_id             String,
    harness             LowCardinality(String),
    session_id          String,
    acknowledged_line   Int64,
    acknowledged_offset UInt64 DEFAULT 0,
    checkpoint_version  UInt64,
    updated_at          DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(checkpoint_version)
ORDER BY (project_id, user_id, harness, session_id);

INSERT INTO session_checkpoints
SELECT
    project_id,
    user_id,
    harness,
    session_id,
    toInt64(max(line_offset)) AS acknowledged_line,
    toUInt64(0) AS acknowledged_offset,
    toUInt64(max(line_offset)) + 1 AS checkpoint_version,
    now64(3) AS updated_at
FROM session_events FINAL
WHERE is_source_record = 1
GROUP BY project_id, user_id, harness, session_id;

CREATE TABLE IF NOT EXISTS session_stats_agg_v2 (
    project_id          String,
    session_id          String,
    agent_id            LowCardinality(String) DEFAULT '',
    agent_version       LowCardinality(String) DEFAULT '',
    user_id             String DEFAULT '',
    parent_session_id   String DEFAULT '',
    harness             LowCardinality(String) DEFAULT '',
    layer_hash          String DEFAULT '',
    first_event_time    DateTime64(3, 'UTC'),
    last_event_time     DateTime64(3, 'UTC'),
    event_count         Int64,
    prompt_count        Int64,
    tool_call_count     Int64,
    tool_result_count   Int64,
    input_tokens        Int64,
    output_tokens       Int64,
    cache_read_tokens   Int64,
    cache_write_tokens  Int64,
    total_credits       Float64,
    model               String,
    summary_version     UInt64,
    updated_at          DateTime64(3, 'UTC') DEFAULT now64(3),
    INDEX idx_ssa_user_id user_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_ssa_agent_id agent_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_ssa_agent_version agent_version TYPE bloom_filter(0.01) GRANULARITY 1
) ENGINE = ReplacingMergeTree(summary_version)
PARTITION BY sipHash64(project_id, user_id, harness, session_id) % 64
ORDER BY (project_id, user_id, harness, session_id);

INSERT INTO session_stats_agg_v2
SELECT
    project_id,
    session_id,
    coalesce(anyIf(agent_id, agent_id IS NOT NULL AND agent_id != ''), '') AS agent_id,
    coalesce(anyIf(agent_version, agent_version IS NOT NULL AND agent_version != ''), '') AS agent_version,
    user_id,
    coalesce(anyIf(parent_session_id, parent_session_id IS NOT NULL), '') AS parent_session_id,
    harness,
    coalesce(anyIf(layer_hash, layer_hash IS NOT NULL AND layer_hash != ''), '') AS layer_hash,
    minIf(timestamp, rendered = 1 AND timestamp > '1971-01-01 00:00:00' AND timestamp < '2099-01-01 00:00:00') AS first_event_time,
    maxIf(timestamp, rendered = 1 AND timestamp > '1971-01-01 00:00:00' AND timestamp < '2099-01-01 00:00:00') AS last_event_time,
    countIf(rendered = 1) AS event_count,
    countIf(rendered = 1 AND event_type = 'user_prompt') AS prompt_count,
    countIf(rendered = 1 AND event_type = 'tool_call') AS tool_call_count,
    countIf(rendered = 1 AND event_type = 'tool_result') AS tool_result_count,
    sumIf(input_tokens, rendered = 1) AS input_tokens,
    sumIf(output_tokens, rendered = 1) AS output_tokens,
    sumIf(cache_read_tokens, rendered = 1) AS cache_read_tokens,
    sumIf(cache_write_tokens, rendered = 1) AS cache_write_tokens,
    max(credits) AS total_credits,
    anyLastIf(model, rendered = 1 AND model != '') AS model,
    toUInt64(toUnixTimestamp64Milli(now64(3))) AS summary_version,
    now64(3) AS updated_at
FROM session_events FINAL
GROUP BY project_id, session_id, user_id, harness;

RENAME TABLE session_stats_agg TO session_stats_agg_pre_002, session_stats_agg_v2 TO session_stats_agg;

DROP TABLE session_stats_agg_pre_002;
