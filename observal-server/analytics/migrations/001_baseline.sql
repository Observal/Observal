-- SPDX-FileCopyrightText: 2026 Observal contributors
-- SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
-- SPDX-License-Identifier: Apache-2.0
--
-- DuckDB analytics baseline.  This is the final ClickHouse schema
-- (001 + 002 + 003 + 004) expressed in DuckDB:
--   * ReplacingMergeTree(v) ORDER BY k  ->  PRIMARY KEY k + INSERT OR REPLACE
--   * Aggregate combinators             ->  FILTER clauses (writer-side refresh)
--   * bloom_filter / set skip indexes   ->  ART indexes
--   * TTL                               ->  services/retention.py DELETE job

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

CREATE INDEX IF NOT EXISTS idx_security_events_event_type ON security_events (event_type);
CREATE INDEX IF NOT EXISTS idx_security_events_severity ON security_events (severity);
CREATE INDEX IF NOT EXISTS idx_security_events_actor ON security_events (actor_id);
CREATE INDEX IF NOT EXISTS idx_security_events_ts ON security_events (timestamp);

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

-- actor_id and action are served by the composite indexes in 002_query_indexes
-- (idx_audit_log_actor_time, idx_audit_log_filter), which lead with them.
CREATE INDEX IF NOT EXISTS idx_audit_log_resource_type ON audit_log (resource_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log (timestamp);

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

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_alert ON webhook_deliveries (alert_rule_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_delivery ON webhook_deliveries (delivery_id);

-- Canonical session telemetry.  ClickHouse used ReplacingMergeTree(ingested_at)
-- with default-order dedup; the primary key plus INSERT OR REPLACE keeps one
-- row per (project, user, harness, session, line) with the newest payload.
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
    raw_line_truncated  UTINYINT DEFAULT 0,
    PRIMARY KEY (project_id, user_id, harness, session_id, line_offset)
);

-- session_id is the leading column of the profile indexes added in
-- 002_query_indexes, so no separate single-column index is needed here.
CREATE INDEX IF NOT EXISTS idx_session_events_user ON session_events (user_id);
CREATE INDEX IF NOT EXISTS idx_session_events_event_type ON session_events (event_type);
CREATE INDEX IF NOT EXISTS idx_session_events_ts ON session_events (timestamp);
CREATE INDEX IF NOT EXISTS idx_session_events_line_hash ON session_events (line_hash);

CREATE TABLE IF NOT EXISTS session_checkpoints (
    project_id          VARCHAR NOT NULL,
    user_id             VARCHAR NOT NULL,
    harness             VARCHAR NOT NULL,
    session_id          VARCHAR NOT NULL,
    acknowledged_line   BIGINT NOT NULL DEFAULT -1,
    acknowledged_offset UBIGINT NOT NULL DEFAULT 0,
    checkpoint_version  UBIGINT NOT NULL DEFAULT 0,
    updated_at          TIMESTAMP DEFAULT now(),
    PRIMARY KEY (project_id, user_id, harness, session_id)
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
    updated_at          TIMESTAMP DEFAULT now(),
    PRIMARY KEY (project_id, user_id, harness, session_id)
);

CREATE INDEX IF NOT EXISTS idx_session_stats_user ON session_stats_agg (user_id);
CREATE INDEX IF NOT EXISTS idx_session_stats_agent ON session_stats_agg (agent_id);
-- last_event_time leads idx_session_stats_active_user in 002_query_indexes.

CREATE TABLE IF NOT EXISTS layer_snapshots (
    hash          VARCHAR NOT NULL,
    project_id    VARCHAR NOT NULL,
    user_id       VARCHAR NOT NULL,
    harness       VARCHAR NOT NULL DEFAULT '',
    content       VARCHAR DEFAULT '',
    uploaded_at   TIMESTAMP DEFAULT now(),
    file_count    USMALLINT DEFAULT 0,
    total_size    UINTEGER DEFAULT 0,
    lockfile_hash VARCHAR DEFAULT '',
    PRIMARY KEY (project_id, user_id, hash)
);
