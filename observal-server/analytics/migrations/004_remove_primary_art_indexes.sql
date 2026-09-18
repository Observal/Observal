-- SPDX-FileCopyrightText: 2026 Observal contributors
-- SPDX-License-Identifier: Apache-2.0
--
-- Telemetry replay is serialized and deduplicated by the analytics service.
-- Keeping PRIMARY KEY constraints adds mutable ART indexes to the hottest
-- tables; overlapping replacement batches have triggered a fatal DuckDB index
-- rollback path. Rebuild the four replayed tables without those indexes while
-- preserving the newest row for every logical identity.

CREATE TABLE session_events_without_art (
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

INSERT INTO session_events_without_art BY NAME
SELECT * FROM session_events
QUALIFY row_number() OVER (
    PARTITION BY project_id, user_id, harness, session_id, line_offset
    ORDER BY ingested_at DESC NULLS LAST
) = 1;

CREATE TABLE session_checkpoints_without_art (
    project_id          VARCHAR NOT NULL,
    user_id             VARCHAR NOT NULL,
    harness             VARCHAR NOT NULL,
    session_id          VARCHAR NOT NULL,
    acknowledged_line   BIGINT NOT NULL DEFAULT -1,
    acknowledged_offset UBIGINT NOT NULL DEFAULT 0,
    checkpoint_version  UBIGINT NOT NULL DEFAULT 0,
    updated_at          TIMESTAMP DEFAULT now()
);

INSERT INTO session_checkpoints_without_art BY NAME
SELECT * FROM session_checkpoints
QUALIFY row_number() OVER (
    PARTITION BY project_id, user_id, harness, session_id
    ORDER BY checkpoint_version DESC, updated_at DESC NULLS LAST
) = 1;

CREATE TABLE session_stats_agg_without_art (
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

INSERT INTO session_stats_agg_without_art BY NAME
SELECT * FROM session_stats_agg
QUALIFY row_number() OVER (
    PARTITION BY project_id, user_id, harness, session_id
    ORDER BY summary_version DESC, updated_at DESC NULLS LAST
) = 1;

CREATE TABLE layer_snapshots_without_art (
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

INSERT INTO layer_snapshots_without_art BY NAME
SELECT * FROM layer_snapshots
QUALIFY row_number() OVER (
    PARTITION BY project_id, user_id, hash
    ORDER BY uploaded_at DESC NULLS LAST
) = 1;

DROP TABLE session_events;
ALTER TABLE session_events_without_art RENAME TO session_events;
DROP TABLE session_checkpoints;
ALTER TABLE session_checkpoints_without_art RENAME TO session_checkpoints;
DROP TABLE session_stats_agg;
ALTER TABLE session_stats_agg_without_art RENAME TO session_stats_agg;
DROP TABLE layer_snapshots;
ALTER TABLE layer_snapshots_without_art RENAME TO layer_snapshots;

CHECKPOINT;
