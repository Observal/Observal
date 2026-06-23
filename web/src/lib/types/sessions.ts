// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
// SPDX-License-Identifier: AGPL-3.0-only

// ── Sessions ────────────────────────────────────────────────────────

export interface SessionsStats {
	total_sessions: number;
	total_prompts: number;
	total_api_requests: number;
	total_tool_calls: number;
	total_input_tokens: number;
	total_output_tokens: number;
	total_traces: number;
	total_spans: number;
}

export interface SessionTrace {
	trace_id: string;
	span_name: string;
	service_name?: string;
	duration_ns: number;
	status: string;
	session_id?: string;
	timestamp?: string;
}

export interface SubagentSession {
	session_id: string;
	spawned_by: string | null;
	events: RawSessionEvent[];
}

export interface SessionData {
	session_id: string;
	events: RawSessionEvent[];
	traces: unknown[];
	service_name: string;
	agent_id?: string | null;
	agent_name?: string | null;
	agent_version?: string | null;
	subagent_sessions?: SubagentSession[];
	max_offset?: number;
}

export interface RawSessionEvent {
	timestamp: string;
	event_name: string;
	body?: string;
	attributes?: Record<string, string>;
	service_name?: string;
}

// ── Sessions ────────────────────────────────────────────────────────

export interface Session {
	session_id: string;
	first_event_time: string;
	last_event_time: string;
	is_active?: boolean;
	prompt_count: number;
	api_request_count: number;
	tool_result_count: number;
	total_input_tokens: number;
	total_output_tokens: number;
	total_cache_read_tokens?: number;
	total_cache_write_tokens?: number;
	total_credits?: number; // Kiro only: lifetime session credit spend
	model: string;
	service_name: string;
	user_id?: string;
	user_name?: string;
	platform?: string;
	terminal_type?: string;
	credits?: string;
	tools_used?: string;
	agent_id?: string | null;
	agent_name?: string | null;
	agent_version?: string | null;
}

export interface SessionsSummary {
	total_sessions: number;
	today_sessions: number;
}

export interface SessionErrorEvent {
	timestamp: string;
	event_name: string;
	body: string;
	session_id: string;
	tool_name: string;
	error: string;
	agent_id: string;
	agent_type: string;
	tool_input: string;
	tool_response: string;
	stop_reason: string;
	user_id: string;
	user_name?: string;
}
