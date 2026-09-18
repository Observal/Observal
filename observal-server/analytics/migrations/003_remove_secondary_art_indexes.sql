-- SPDX-FileCopyrightText: 2026 Observal contributors
-- SPDX-License-Identifier: Apache-2.0
--
-- DuckDB's zone maps are a better fit for these analytical scans. Secondary
-- ART indexes substantially increase database size and make idempotent bulk
-- replacement prohibitively expensive. Primary-key indexes remain intact.

DROP INDEX IF EXISTS idx_security_events_event_type;
DROP INDEX IF EXISTS idx_security_events_severity;
DROP INDEX IF EXISTS idx_security_events_actor;
DROP INDEX IF EXISTS idx_security_events_ts;
DROP INDEX IF EXISTS idx_audit_log_resource_type;
DROP INDEX IF EXISTS idx_audit_log_ts;
DROP INDEX IF EXISTS idx_webhook_deliveries_alert;
DROP INDEX IF EXISTS idx_webhook_deliveries_delivery;
DROP INDEX IF EXISTS idx_session_events_user;
DROP INDEX IF EXISTS idx_session_events_event_type;
DROP INDEX IF EXISTS idx_session_events_ts;
DROP INDEX IF EXISTS idx_session_events_line_hash;
DROP INDEX IF EXISTS idx_session_stats_user;
DROP INDEX IF EXISTS idx_session_stats_agent;
DROP INDEX IF EXISTS idx_session_events_detail;
DROP INDEX IF EXISTS idx_session_events_parent;
DROP INDEX IF EXISTS idx_session_events_profile_tool;
DROP INDEX IF EXISTS idx_session_events_profile_event;
DROP INDEX IF EXISTS idx_session_stats_scope;
DROP INDEX IF EXISTS idx_session_stats_active_user;
DROP INDEX IF EXISTS idx_session_stats_agent_version;
DROP INDEX IF EXISTS idx_session_stats_harness_event;
DROP INDEX IF EXISTS idx_session_stats_model_event;
DROP INDEX IF EXISTS idx_audit_log_actor_time;
DROP INDEX IF EXISTS idx_audit_log_filter;

CHECKPOINT;
