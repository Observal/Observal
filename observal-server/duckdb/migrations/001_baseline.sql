-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
-- SPDX-License-Identifier: Apache-2.0
--
-- Observal analytics baseline schema (DuckDB dialect).
--
-- Consolidates the final state of the legacy ClickHouse migrations
-- (001_baseline .. 004_remove_legacy_scope) into one baseline:
--   * MergeTree append-only tables   -> plain DuckDB tables
--   * ReplacingMergeTree tables      -> PRIMARY KEY + INSERT OR REPLACE
--   * AggregatingMergeTree + MV      -> plain table maintained in app code
--                                       (refresh_session_summary), unchanged
--   * TTL                            -> enforced by services.retention cron
--   * bloom_filter / set indexes     -> dropped (DuckDB zone maps are automatic;
--                                       PKs create ART indexes)
--   * LowCardinality / CODEC(ZSTD)   -> dropped (DuckDB picks per-column
--                                       encodings automatically)
--   * UUID                           -> VARCHAR (only equality filters are used)
--   * DateTime64(3, 'UTC')           -> TIMESTAMP (naive UTC; the client pins
--                                       SET TimeZone='UTC' on connect)

CREATE TABLE IF NOT EXISTS security_events (
    event_id    VARCHAR,
    timestamp   TIMESTAMP NOT NULL,
    event_type  VARCHAR,
    severity    VARCHAR,
    actor_id    VARCHAR DEFAULT '',
    actor_email VARCHAR DEFAULT '',
    actor_role  VARCHAR DEFAULT '',
    target_id   VARCHAR DEFAULT '',
    target_type VARCHAR DEFAULT '',
    outcome     VARCHAR,
    source_ip   VARCHAR DEFAULT '',
    user_agent  VARCHAR DEFAULT '',
    detail      VARCHAR DEFAULT ''
)
;

CREATE TABLE IF NOT EXISTS audit_log (
    event_id      VARCHAR,
    timestamp     TIMESTAMP NOT NULL,
    actor_id      VARCHAR,
    actor_email   VARCHAR,
    actor_role    VARCHAR,
    action        VARCHAR,
    resource_type VARCHAR,
    resource_id   VARCHAR DEFAULT '',
    resource_name VARCHAR DEFAULT '',
    http_method   VARCHAR DEFAULT '',
    http_path     VARCHAR DEFAULT '',
    status_code   USMALLINT DEFAULT 0,
    ip_address    VARCHAR DEFAULT '',
    user_agent    VARCHAR DEFAULT '',
    detail        VARCHAR DEFAULT '',
    sensitivity   VARCHAR DEFAULT 'standard',
    request_id    VARCHAR DEFAULT '',
    outcome       VARCHAR DEFAULT '',
    duration_ms   FLOAT DEFAULT 0,
    chain_hash    VARCHAR DEFAULT '',
    source        VARCHAR DEFAULT 'server'
)
;

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    delivery_id     VARCHAR,
    event_id        VARCHAR,
    alert_rule_id   VARCHAR,
    attempt_number  UTINYINT,
    timestamp       TIMESTAMP NOT NULL,
    webhook_url     VARCHAR,
    status_code     USMALLINT,
    delivery_status VARCHAR,
    error           VARCHAR,
    duration_ms     FLOAT,
    payload_size    UINTEGER
)
;

-- ReplacingMergeTree(ingested_at) ORDER BY (project_id, user_id, harness, session_id, line_offset)
CREATE TABLE IF NOT EXISTS session_events (
    session_id        VARCHAR NOT NULL,
    project_id        VARCHAR NOT NULL,
    user_id           VARCHAR NOT NULL,
    agent_id          VARCHAR,
    agent_version     VARCHAR,
    layer_hash        VARCHAR,
    harness           VARCHAR NOT NULL,
    line_offset       UINTEGER NOT NULL,
    source_end_offset UBIGINT DEFAULT 0,
    line_hash         VARCHAR DEFAULT '',
    source_sha256     VARCHAR DEFAULT '',
    is_source_record  UTINYINT DEFAULT 1,
    rendered          UTINYINT DEFAULT 1,
    event_type        VARCHAR,
    timestamp         TIMESTAMP NOT NULL,
    uuid              VARCHAR,
    parent_uuid       VARCHAR,
    tool_name         VARCHAR,
    tool_id           VARCHAR,
    content_preview   VARCHAR,
    content_length    UINTEGER,
    raw_line          VARCHAR,
    ingested_at       TIMESTAMP DEFAULT now()::TIMESTAMP,
    credits           DOUBLE DEFAULT 0,
    parent_session_id VARCHAR,
    input_tokens      INTEGER DEFAULT 0,
    output_tokens     INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    model             VARCHAR DEFAULT '',
    raw_line_truncated UTINYINT DEFAULT 0,
    PRIMARY KEY (project_id, user_id, harness, session_id, line_offset)
)
;

-- ReplacingMergeTree(checkpoint_version) ORDER BY (project_id, user_id, harness, session_id)
CREATE TABLE IF NOT EXISTS session_checkpoints (
    project_id          VARCHAR NOT NULL,
    user_id             VARCHAR NOT NULL,
    harness             VARCHAR NOT NULL,
    session_id          VARCHAR NOT NULL,
    acknowledged_line   BIGINT,
    acknowledged_offset UBIGINT DEFAULT 0,
    checkpoint_version  UBIGINT,
    updated_at          TIMESTAMP DEFAULT now()::TIMESTAMP,
    PRIMARY KEY (project_id, user_id, harness, session_id)
)
;

-- ReplacingMergeTree(summary_version) ORDER BY (project_id, user_id, harness, session_id)
-- Maintained in application code by refresh_session_summary(); there is no
-- materialized view - the aggregate is refreshed explicitly after ingest.
CREATE TABLE IF NOT EXISTS session_stats_agg (
    project_id        VARCHAR NOT NULL,
    session_id        VARCHAR NOT NULL,
    agent_id          VARCHAR DEFAULT '',
    agent_version     VARCHAR DEFAULT '',
    user_id           VARCHAR NOT NULL DEFAULT '',
    parent_session_id VARCHAR DEFAULT '',
    harness           VARCHAR NOT NULL DEFAULT '',
    layer_hash        VARCHAR DEFAULT '',
    first_event_time  TIMESTAMP,
    last_event_time   TIMESTAMP,
    event_count       BIGINT,
    prompt_count      BIGINT,
    tool_call_count   BIGINT,
    tool_result_count BIGINT,
    input_tokens      BIGINT,
    output_tokens     BIGINT,
    cache_read_tokens BIGINT,
    cache_write_tokens BIGINT,
    total_credits     DOUBLE,
    model             VARCHAR,
    summary_version   UBIGINT,
    updated_at        TIMESTAMP DEFAULT now()::TIMESTAMP,
    PRIMARY KEY (project_id, user_id, harness, session_id)
)
;

-- ReplacingMergeTree(uploaded_at) ORDER BY (project_id, user_id, hash)
CREATE TABLE IF NOT EXISTS layer_snapshots (
    hash          VARCHAR NOT NULL,
    project_id    VARCHAR NOT NULL,
    user_id       VARCHAR NOT NULL,
    harness       VARCHAR,
    content       VARCHAR,
    uploaded_at   TIMESTAMP DEFAULT now()::TIMESTAMP,
    file_count    USMALLINT,
    total_size    UINTEGER,
    lockfile_hash VARCHAR DEFAULT '',
    PRIMARY KEY (project_id, user_id, hash)
)
;
