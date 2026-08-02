-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
-- SPDX-License-Identifier: Apache-2.0

-- Rebuild project-keyed tables so old project identities collapse into the
-- single deployment project without relying on mutations or losing rows.
DROP VIEW IF EXISTS session_stats_mv;

SELECT throwIf(count() > 0, 'scope cleanup aborted: conflicting session identities')
FROM
(
    SELECT session_id, user_id, harness, line_offset
    FROM session_events FINAL
    GROUP BY session_id, user_id, harness, line_offset
    HAVING countDistinct(project_id) > 1
);

DROP TABLE IF EXISTS session_events_scope_cleanup_backup;
CREATE TABLE IF NOT EXISTS session_events_scope_cleanup AS session_events;
TRUNCATE TABLE session_events_scope_cleanup;
INSERT INTO session_events_scope_cleanup
(
    session_id, project_id, user_id, agent_id, agent_version, layer_hash,
    harness, line_offset, source_end_offset, line_hash, source_sha256,
    is_source_record, rendered, event_type, timestamp, uuid, parent_uuid,
    tool_name, tool_id, content_preview, content_length, raw_line,
    ingested_at, credits, parent_session_id, input_tokens, output_tokens,
    cache_read_tokens, cache_write_tokens, model, raw_line_truncated
)
SELECT
    session_id, 'default', user_id, agent_id, agent_version, layer_hash,
    harness, line_offset, source_end_offset, line_hash, source_sha256,
    is_source_record, rendered, event_type, timestamp, uuid, parent_uuid,
    tool_name, tool_id, content_preview, content_length, raw_line,
    ingested_at, credits, parent_session_id, input_tokens, output_tokens,
    cache_read_tokens, cache_write_tokens, model, raw_line_truncated
FROM session_events FINAL;

SELECT throwIf(
    (SELECT count() FROM session_events_scope_cleanup) != (SELECT count() FROM session_events FINAL),
    'scope cleanup aborted: session event count changed during staging'
);
SELECT throwIf(
    (SELECT count() FROM session_events_scope_cleanup WHERE project_id != 'default') > 0,
    'scope cleanup aborted: session event normalization failed'
);

RENAME TABLE session_events TO session_events_scope_cleanup_backup,
             session_events_scope_cleanup TO session_events;
DROP TABLE IF EXISTS session_events_scope_cleanup_backup;

DROP TABLE IF EXISTS session_checkpoints_scope_cleanup_backup;
CREATE TABLE IF NOT EXISTS session_checkpoints_scope_cleanup AS session_checkpoints;
TRUNCATE TABLE session_checkpoints_scope_cleanup;
INSERT INTO session_checkpoints_scope_cleanup
(
    project_id, user_id, harness, session_id, acknowledged_line,
    acknowledged_offset, checkpoint_version, updated_at
)
SELECT
    'default', user_id, harness, session_id,
    argMax(acknowledged_line, checkpoint_version),
    argMax(acknowledged_offset, checkpoint_version),
    max(checkpoint_version),
    argMax(updated_at, checkpoint_version)
FROM session_checkpoints FINAL
GROUP BY user_id, harness, session_id;

RENAME TABLE session_checkpoints TO session_checkpoints_scope_cleanup_backup,
             session_checkpoints_scope_cleanup TO session_checkpoints;
DROP TABLE IF EXISTS session_checkpoints_scope_cleanup_backup;

DROP TABLE IF EXISTS session_stats_agg_scope_cleanup_backup;
CREATE TABLE IF NOT EXISTS session_stats_agg_scope_cleanup AS session_stats_agg;
TRUNCATE TABLE session_stats_agg_scope_cleanup;
INSERT INTO session_stats_agg_scope_cleanup
(
    project_id, session_id, agent_id, agent_version, user_id, parent_session_id,
    harness, layer_hash, first_event_time, last_event_time, event_count,
    prompt_count, tool_call_count, tool_result_count, input_tokens,
    output_tokens, cache_read_tokens, cache_write_tokens, total_credits,
    model, summary_version, updated_at
)
SELECT
    'default',
    session_id,
    coalesce(anyIf(agent_id, agent_id IS NOT NULL AND agent_id != ''), ''),
    coalesce(anyIf(agent_version, agent_version IS NOT NULL AND agent_version != ''), ''),
    user_id,
    coalesce(anyIf(parent_session_id, parent_session_id IS NOT NULL AND parent_session_id != ''), ''),
    harness,
    coalesce(anyIf(layer_hash, layer_hash IS NOT NULL AND layer_hash != ''), ''),
    minIf(timestamp, rendered = 1 AND timestamp > '1971-01-01 00:00:00' AND timestamp < '2099-01-01 00:00:00'),
    maxIf(timestamp, rendered = 1 AND timestamp > '1971-01-01 00:00:00' AND timestamp < '2099-01-01 00:00:00'),
    countIf(rendered = 1),
    countIf(rendered = 1 AND event_type = 'user_prompt'),
    countIf(rendered = 1 AND event_type = 'tool_call'),
    countIf(rendered = 1 AND event_type = 'tool_result'),
    sumIf(input_tokens, rendered = 1),
    sumIf(output_tokens, rendered = 1),
    sumIf(cache_read_tokens, rendered = 1),
    sumIf(cache_write_tokens, rendered = 1),
    max(credits),
    anyLastIf(model, rendered = 1 AND model != ''),
    toUInt64(toUnixTimestamp64Milli(now64(3))),
    now64(3)
FROM session_events FINAL
GROUP BY session_id, user_id, harness;

SELECT throwIf(
    (SELECT count() FROM session_stats_agg_scope_cleanup) !=
    (
        SELECT count()
        FROM
        (
            SELECT session_id, user_id, harness
            FROM session_events FINAL
            GROUP BY session_id, user_id, harness
        )
    ),
    'scope cleanup aborted: aggregate count does not match canonical sessions'
);

RENAME TABLE session_stats_agg TO session_stats_agg_scope_cleanup_backup,
             session_stats_agg_scope_cleanup TO session_stats_agg;
DROP TABLE IF EXISTS session_stats_agg_scope_cleanup_backup;

DROP TABLE IF EXISTS layer_snapshots_scope_cleanup_backup;
CREATE TABLE IF NOT EXISTS layer_snapshots_scope_cleanup AS layer_snapshots;
TRUNCATE TABLE layer_snapshots_scope_cleanup;
INSERT INTO layer_snapshots_scope_cleanup
(
    hash, project_id, user_id, harness, content, uploaded_at,
    file_count, total_size, lockfile_hash
)
SELECT
    hash,
    'default',
    user_id,
    harness,
    argMax(content, uploaded_at),
    max(uploaded_at),
    argMax(file_count, uploaded_at),
    argMax(total_size, uploaded_at),
    argMax(lockfile_hash, uploaded_at)
FROM layer_snapshots FINAL
GROUP BY hash, user_id, harness;

RENAME TABLE layer_snapshots TO layer_snapshots_scope_cleanup_backup,
             layer_snapshots_scope_cleanup TO layer_snapshots;
DROP TABLE IF EXISTS layer_snapshots_scope_cleanup_backup;

CREATE MATERIALIZED VIEW IF NOT EXISTS session_stats_mv
    TO session_stats_agg AS
    SELECT
        'default' AS project_id,
        session_id,
        coalesce(anyIf(agent_id, agent_id IS NOT NULL AND agent_id != ''), '') AS agent_id,
        coalesce(anyIf(agent_version, agent_version IS NOT NULL AND agent_version != ''), '') AS agent_version,
        user_id,
        coalesce(anyIf(parent_session_id, parent_session_id IS NOT NULL AND parent_session_id != ''), '') AS parent_session_id,
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
    FROM session_events
    GROUP BY session_id, user_id, harness;

ALTER TABLE audit_log DROP INDEX IF EXISTS idx_org_id;
ALTER TABLE audit_log DROP COLUMN IF EXISTS org_id;
ALTER TABLE security_events DROP COLUMN IF EXISTS org_id;

SELECT throwIf((SELECT count() FROM session_events WHERE project_id != 'default') > 0,
               'scope cleanup aborted: non-canonical session project remains');
SELECT throwIf((SELECT count() FROM session_checkpoints WHERE project_id != 'default') > 0,
               'scope cleanup aborted: non-canonical checkpoint project remains');
SELECT throwIf((SELECT count() FROM session_stats_agg WHERE project_id != 'default') > 0,
               'scope cleanup aborted: non-canonical aggregate project remains');
SELECT throwIf((SELECT count() FROM layer_snapshots WHERE project_id != 'default') > 0,
               'scope cleanup aborted: non-canonical snapshot project remains');
