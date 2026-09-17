-- SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
-- SPDX-License-Identifier: Apache-2.0
--
-- Read-path indexes for sessions, dashboards, insights, and governance.
-- DuckDB keeps zone maps either way; these ART indexes cover the equality and
-- range predicates the ported queries use.

CREATE INDEX IF NOT EXISTS idx_session_events_detail
    ON session_events (project_id, user_id, session_id, harness, line_offset);

CREATE INDEX IF NOT EXISTS idx_session_events_parent
    ON session_events (project_id, user_id, parent_session_id, harness, line_offset);

CREATE INDEX IF NOT EXISTS idx_session_events_profile_tool
    ON session_events (session_id, tool_name);

CREATE INDEX IF NOT EXISTS idx_session_events_profile_event
    ON session_events (session_id, event_type);

CREATE INDEX IF NOT EXISTS idx_session_stats_scope
    ON session_stats_agg (project_id, user_id, last_event_time);

CREATE INDEX IF NOT EXISTS idx_session_stats_active_user
    ON session_stats_agg (last_event_time, project_id, user_id);

CREATE INDEX IF NOT EXISTS idx_session_stats_agent_version
    ON session_stats_agg (project_id, agent_id, agent_version, last_event_time);

CREATE INDEX IF NOT EXISTS idx_session_stats_harness_event
    ON session_stats_agg (project_id, harness, first_event_time);

CREATE INDEX IF NOT EXISTS idx_session_stats_model_event
    ON session_stats_agg (project_id, model, first_event_time);

-- No separate audit_log (timestamp) index: 001_baseline.sql already creates
-- idx_audit_log_ts on the same column.

CREATE INDEX IF NOT EXISTS idx_audit_log_actor_time
    ON audit_log (actor_id, actor_email, timestamp);

CREATE INDEX IF NOT EXISTS idx_audit_log_filter
    ON audit_log (action, resource_type, timestamp);

-- No layer_snapshots (project_id, user_id, hash) index: that is the table's
-- primary key, which DuckDB already backs with an ART index.
