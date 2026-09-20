-- SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
-- SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
-- SPDX-License-Identifier: Apache-2.0
--
-- DuckDB analytics baseline: the complete final schema in a single migration.
--
-- Mapping from the ClickHouse schema this replaces:
--   * ReplacingMergeTree(v) ORDER BY k  ->  writer-side DELETE + INSERT in one
--     transaction (ANALYTICS_UPSERT_KEYS in services/analytics/duckdb/_settings.py)
--   * Aggregate combinators             ->  FILTER clauses (writer-side refresh)
--   * projections / bloom_filter / set skip indexes  ->  DuckDB zone maps
--   * TTL                               ->  services/retention.py DELETE job
--
-- No PRIMARY KEY constraints and no ART indexes are declared. Replay-heavy
-- tables are replaced in bulk while concurrent readers hold older snapshots;
-- mutable ART indexes on those tables triggered a fatal DuckDB index-rollback
-- path and inflated the database file, and zone maps already prune the
-- analytical scans these tables serve. Replay identity is enforced by the
-- upsert keys above, never by a constraint.

CREATE TABLE IF NOT EXISTS security_events (
    event_id    VARCHAR,
    timestamp   TIMESTAMP NOT NULL,
    event_type  VARCHAR NOT NULL,
    severity    VARCHAR NOT NULL,
    actor_id    VARCHAR DEFAULT '',
    actor_email VARCHAR DEFAULT '',
    actor_role  VARCHAR DEFAULT '',
    target_id   VARCHAR DEFAULT '',
    target_type VARCHAR DEFAULT '',
    outcome     VARCHAR DEFAULT '',
    source_ip   VARCHAR DEFAULT '',
    user_agent  VARCHAR DEFAULT '',
    detail      VARCHAR DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_log (
    event_id      VARCHAR,
    timestamp     TIMESTAMP NOT NULL,
    actor_id      VARCHAR DEFAULT '',
    actor_email   VARCHAR DEFAULT '',
    actor_role    VARCHAR DEFAULT '',
    action        VARCHAR DEFAULT '',
    resource_type VARCHAR DEFAULT '',
    resource_id   VARCHAR DEFAULT '',
    resource_name VARCHAR DEFAULT '',
    http_method   VARCHAR DEFAULT '',
    http_path     VARCHAR DEFAULT '',
    status_code   INTEGER DEFAULT 0,
    ip_address    VARCHAR DEFAULT '',
    user_agent    VARCHAR DEFAULT '',
    detail        VARCHAR DEFAULT '',
    sensitivity   VARCHAR DEFAULT 'standard',
    request_id    VARCHAR DEFAULT '',
    outcome       VARCHAR DEFAULT '',
    duration_ms   FLOAT DEFAULT 0,
    chain_hash    VARCHAR DEFAULT '',
    source        VARCHAR DEFAULT 'server'
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    delivery_id     VARCHAR,
    event_id        VARCHAR,
    alert_rule_id   VARCHAR,
    attempt_number  UTINYINT,
    timestamp       TIMESTAMP NOT NULL,
    webhook_url     VARCHAR,
    status_code     INTEGER,
    delivery_status VARCHAR,
    error           VARCHAR,
    duration_ms     FLOAT,
    payload_size    UINTEGER
);

-- Canonical session telemetry. ClickHouse used ReplacingMergeTree(ingested_at)
-- with default-order dedup; the ingest path now deletes and re-inserts one row
-- per (project, user, harness, session, line) with the newest payload.
CREATE TABLE IF NOT EXISTS session_events (
    session_id          VARCHAR NOT NULL,
    project_id          VARCHAR NOT NULL,
    user_id             VARCHAR NOT NULL,
    agent_id            VARCHAR,
    agent_version       VARCHAR,
    layer_hash          VARCHAR,
    harness             VARCHAR NOT NULL,
    line_offset         UINTEGER NOT NULL,
    source_end_offset   UBIGINT DEFAULT 0,
    line_hash           VARCHAR DEFAULT '',
    source_sha256       VARCHAR DEFAULT '',
    is_source_record    UTINYINT DEFAULT 1,
    rendered            UTINYINT DEFAULT 1,
    event_type          VARCHAR NOT NULL,
    timestamp           TIMESTAMP NOT NULL,
    uuid                VARCHAR,
    parent_uuid         VARCHAR,
    tool_name           VARCHAR,
    tool_id             VARCHAR,
    content_preview     VARCHAR DEFAULT '',
    content_length      UINTEGER DEFAULT 0,
    raw_line            VARCHAR DEFAULT '',
    ingested_at         TIMESTAMP DEFAULT now(),
    credits             DOUBLE DEFAULT 0,
    parent_session_id   VARCHAR,
    input_tokens        INTEGER DEFAULT 0,
    output_tokens       INTEGER DEFAULT 0,
    cache_read_tokens   INTEGER DEFAULT 0,
    cache_write_tokens  INTEGER DEFAULT 0,
    model               VARCHAR DEFAULT '',
    raw_line_truncated  UTINYINT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS session_checkpoints (
    project_id          VARCHAR NOT NULL,
    user_id             VARCHAR NOT NULL,
    harness             VARCHAR NOT NULL,
    session_id          VARCHAR NOT NULL,
    acknowledged_line   BIGINT NOT NULL DEFAULT -1,
    acknowledged_offset UBIGINT NOT NULL DEFAULT 0,
    checkpoint_version  UBIGINT NOT NULL DEFAULT 0,
    updated_at          TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS session_stats_agg (
    project_id          VARCHAR NOT NULL,
    session_id          VARCHAR NOT NULL,
    agent_id            VARCHAR DEFAULT '',
    agent_version       VARCHAR DEFAULT '',
    user_id             VARCHAR NOT NULL DEFAULT '',
    parent_session_id   VARCHAR DEFAULT '',
    harness             VARCHAR NOT NULL DEFAULT '',
    layer_hash          VARCHAR DEFAULT '',
    first_event_time    TIMESTAMP,
    last_event_time     TIMESTAMP,
    event_count         BIGINT DEFAULT 0,
    prompt_count        BIGINT DEFAULT 0,
    tool_call_count     BIGINT DEFAULT 0,
    tool_result_count   BIGINT DEFAULT 0,
    input_tokens        BIGINT DEFAULT 0,
    output_tokens       BIGINT DEFAULT 0,
    cache_read_tokens   BIGINT DEFAULT 0,
    cache_write_tokens  BIGINT DEFAULT 0,
    total_credits       DOUBLE DEFAULT 0,
    model               VARCHAR DEFAULT '',
    summary_version     UBIGINT NOT NULL DEFAULT 0,
    updated_at          TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS layer_snapshots (
    hash          VARCHAR NOT NULL,
    project_id    VARCHAR NOT NULL,
    user_id       VARCHAR NOT NULL,
    harness       VARCHAR NOT NULL DEFAULT '',
    content       VARCHAR DEFAULT '',
    uploaded_at   TIMESTAMP DEFAULT now(),
    file_count    USMALLINT DEFAULT 0,
    total_size    UINTEGER DEFAULT 0,
    lockfile_hash VARCHAR DEFAULT ''
);
