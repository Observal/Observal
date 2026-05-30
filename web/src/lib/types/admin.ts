// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
// SPDX-License-Identifier: AGPL-3.0-only

// ── Admin ───────────────────────────────────────────────────────────

export interface AdminUser {
	id: string;
	username?: string;
	name?: string;
	email?: string;
	role: string;
	department?: string | null;
	created_at?: string;
}

export interface AdminSetting {
	key: string;
	value: string;
	is_sensitive?: boolean;
	is_set?: boolean;
}

export interface AuditLogEntry {
	event_id: string;
	timestamp: string;
	actor_id: string;
	actor_email: string;
	actor_role: string;
	action: string;
	resource_type: string;
	resource_id: string;
	resource_name: string;
	http_method: string;
	http_path: string;
	status_code: number;
	ip_address: string;
	user_agent: string;
	detail: string;
	org_id: string;
	sensitivity: string;
	request_id: string;
	outcome: string;
	duration_ms: number;
	chain_hash: string;
	source: string;
}

export interface SecurityEvent {
	event_id: string;
	timestamp: string;
	event_type: string;
	severity: string;
	actor_id: string;
	actor_email: string;
	actor_role: string;
	target_id: string;
	target_type: string;
	outcome: string;
	source_ip: string;
	user_agent: string;
	detail: string;
	org_id: string;
}

export interface DiagnosticsResponse {
	status: "ok" | "degraded" | "unhealthy";
	licensed: boolean;
	checks: Record<string, Record<string, unknown>>;
}

// ── Insights ───────────────────────────────────────────────────────

export interface InsightReportListItem {
	id: string;
	agent_id: string;
	status: "pending" | "running" | "completed" | "failed";
	period_start: string;
	period_end: string;
	sessions_analyzed: number;
	created_at: string;
	completed_at: string | null;
}

export interface InsightCostMetrics {
	total_cost_usd: number;
	avg_cost_per_session: number;
	p50_session_cost: number;
	p90_session_cost: number;
	p99_session_cost: number;
	cache_efficiency_ratio: number;
	most_expensive_model: string;
	cost_by_model: { model: string; total_cost_usd: number }[];
}

export interface InsightToolErrors {
	total_categorized: number;
	categories: Record<string, number>;
	by_tool: Record<string, Record<string, number>>;
}

export interface InsightInterruptions {
	stop_reasons: Record<string, number>;
	user_interruptions: number;
	total_stops: number;
}

export interface InsightReconciliation {
	available: boolean;
	reconciled_sessions?: number;
	total_input_tokens?: number;
	total_output_tokens?: number;
	cache_read_tokens?: number;
	cache_creation_tokens?: number;
	thinking_turns?: number;
	tool_uses?: number;
}

export interface InsightMetrics {
	overview: {
		total_sessions: string;
		unique_users: string;
		first_session: string;
		last_session: string;
	};
	tokens: {
		total_input_tokens: string;
		total_output_tokens: string;
		total_tokens: string;
		total_cache_read_tokens: string;
		total_cache_write_tokens: string;
	};
	cost?: InsightCostMetrics;
	duration: {
		session_count: string;
		avg_duration_seconds: string;
		p50_duration_seconds: string;
		p90_duration_seconds: string;
	};
	errors: {
		total_events: string;
		total_tool_calls: string;
		failure_stops: string;
		error_events: string;
		error_rate: number;
	};
	tool_errors?: InsightToolErrors;
	interruptions?: InsightInterruptions;
	reconciliation?: InsightReconciliation;
	tools: {
		name: string;
		invocations: string;
		errors: string;
	}[];
	sessions: {
		session_id: string;
		duration_seconds: string;
		prompt_count: string;
		tool_call_count: string;
		input_tokens: string;
		output_tokens: string;
	}[];
}

export interface InsightNarrative {
	// V3 structured format: each section is a structured object
	// V1 fallback: each section is string[] or string
	// The frontend handles both formats gracefully
	at_a_glance: unknown;
	what_they_work_on?: unknown;
	usage_patterns: unknown;
	interaction_style?: unknown;
	user_experience?: unknown;
	what_works?: unknown;
	friction_analysis: unknown;
	suggestions: unknown;
	usage_cost_analysis?: unknown;
	token_optimization?: unknown;
	regression_detection?: unknown;
	on_the_horizon?: unknown;
	fun_ending?: unknown;
	regressions?: InsightRegression[];
}

export interface InsightRegression {
	metric: string;
	direction: "improved" | "degraded";
	magnitude: number;
	current_value: number;
	previous_value: number;
	severity: "low" | "medium" | "high";
}

export interface InsightReport {
	id: string;
	agent_id: string;
	triggered_by: string | null;
	status: "pending" | "running" | "completed" | "failed";
	period_start: string;
	period_end: string;
	metrics: InsightMetrics | null;
	narrative: InsightNarrative | null;
	facets_summary: Record<string, unknown> | null;
	sessions_analyzed: number;
	llm_model_used: string | null;
	error_message: string | null;
	started_at: string;
	completed_at: string | null;
	created_at: string;
	applied_at: string | null;
	applied_items: InsightAppliedItems | null;
}

export interface InsightAppliedItems {
	agent_version: { id: string; version: string; additions_count: number; linked_components: number } | null;
	skills: { id: string; name: string; description: string; type: string }[];
	hooks: { id: string; name: string; description: string; type: string }[];
	prompts: { id: string; name: string; description: string; type: string }[];
}

// ── Telemetry ───────────────────────────────────────────────────────

export interface TelemetryStatus {
	clickhouse: boolean;
	traces_count: number;
	spans_count: number;
	scores_count: number;
}

// ── Models catalog ──────────────────────────────────────────────────

export interface ModelDisplay {
	primary: string;
	secondary: string | null;
	is_rolling: boolean;
	is_deprecated: boolean;
}

export interface CatalogModel {
	model_id: string;
	display_name: string;
	provider: string;
	family: string;
	release_date: string | null;
	last_updated: string | null;
	context_window: number | null;
	output_tokens: number | null;
	cost_input: number | null;
	cost_output: number | null;
	capabilities: string[];
	supported_ides: string[];
	deprecated: boolean;
	display: ModelDisplay | null;
}

export interface ModelCatalog {
	models: CatalogModel[];
	fetched_at: string;
	source: "live" | "redis" | "snapshot" | "empty";
	degraded: boolean;
	etag: string | null;
	upstream_etag: string | null;
	model_count: number;
}

export interface ModelRefreshDiff {
	added: string[];
	removed: string[];
	updated: string[];
	total: number;
}

export interface ModelRefreshResult {
	ok: boolean;
	diff: ModelRefreshDiff;
	fetched_at: string;
	source: string;
	degraded: boolean;
	model_count: number;
	etag: string | null;
	upstream_etag: string | null;
}

export interface SystemWarning {
	level: "critical" | "warning" | "info";
	code: string;
	message: string;
}

// ── Exec Dashboard ─────────────────────────────────────────────────

export interface ExecAdoptionResponse {
	monthly: { month: string; adoption_pct: number }[];
	current_pct: number;
	total_users: number;
	active_users: number;
	departments_covered: number;
}

export interface ExecAgentCounts {
	total: number;
	active: number;
	published: number;
	in_development: number;
	by_category: { category: string; count: number }[];
}

export interface ExecUsageByCategory {
	category: string;
	sessions: number;
	growth_pct: number;
}

export interface ExecPlatformCoverage {
	platform: string;
	users: number;
	sessions: number;
}

export interface ExecPlatformScore {
	platform: string;
	composite_score: number;
	sessions: number;
	avg_cost: number;
	avg_latency_ms: number;
	success_rate: number;
	error_rate: number;
	users: number;
}

export interface ExecVelocityResponse {
	weekly: { week: string; traces: number }[];
	current_weekly_avg: number;
	baseline_weekly_avg: number;
	multiplier: number;
}

export interface ExecTopAgent {
	id: string;
	name: string;
	category: string;
	composite_score: number;
	sessions: number;
	downloads: number;
	avg_rating: number | null;
	weekly_trend: number[];
}

export interface ExecConfig {
	id: string;
	org_id: string;
	hourly_dev_cost: number;
	pre_ai_baselines: Record<string, number>;
	department_budgets: Record<string, { headcount: number; monthly_budget: number }>;
	target_adoption_pct: number;
	target_adoption_date: string | null;
}

export interface ExecDepartmentItem {
	department: string;
	user_count: number;
	agent_count: number;
	utilization_pct: number;
	sessions_per_user: number;
}

export interface ExecDepartmentsResponse {
	departments: ExecDepartmentItem[];
}

export interface ExecDeptTokenItem {
	department: string;
	tokens_used: number;
	cost_per_task: number;
	sessions_per_user: number;
	trend_pct: number;
}

export interface ExecCostByCategory {
	category: string;
	baseline_cost: number;
	actual_cost: number;
	saved_pct: number;
}

export interface ExecCostSummary {
	monthly_savings: number;
	cost_reduction_pct: number;
	projected_annual_savings: number;
	cost_per_task: number;
	monthly_trend: { month: string; ai_spend: number; savings: number }[];
	by_category: ExecCostByCategory[];
	configured: boolean;
}

export interface ExecROIProjectionPoint {
	quarter: string;
	projected_savings: number;
	cumulative_savings: number;
	confidence: number;
}

export interface ExecROIProjectionsResponse {
	projections: ExecROIProjectionPoint[];
	growth_rate_pct: number;
	time_to_breakeven_months: number | null;
	total_invested: number;
	total_saved: number;
	roi_multiple: number;
}

export interface ExecModelComparison {
	model: string;
	sessions: number;
	avg_cost: number;
	avg_tokens: number;
	success_rate: number;
	best_at: string;
}

export interface ExecDepartmentGap {
	department: string;
	adoption_pct: number;
	sessions: number;
	opportunity: string;
}

export interface ExecQuickWin {
	title: string;
	detail: string;
	estimated_savings: number;
	effort: string;
}

export interface ExecPlatformComparison {
	platform: string;
	avg_task_time_ms: number;
	sessions: number;
	success_rate: number;
}

export interface ExecStrategicInsightsResponse {
	model_comparison: ExecModelComparison[];
	department_gaps: ExecDepartmentGap[];
	quick_wins: ExecQuickWin[];
	platform_comparison: ExecPlatformComparison[];
	power_user_pct: number;
	power_user_value_pct: number;
	total_active_users: number;
	automatable_pct: number;
}

export interface ExecDeveloperItem {
	user_id: string;
	name: string;
	department: string;
	sessions: number;
	tokens_consumed: number;
	cost: number;
	percentile: number;
}

export interface ExecDeveloperBreakdown {
	total_developers: number;
	active_developers: number;
	top_20_value_pct: number;
	developers: ExecDeveloperItem[];
}

export interface ExecInactiveAgent {
	id: string;
	name: string;
	category: string;
	last_session_days_ago: number;
	previous_sessions: number;
}

export interface ExecInactiveUser {
	user_id: string;
	name: string;
	department: string;
	last_session_days_ago: number;
	previous_sessions: number;
}

export interface ExecInactivityAlerts {
	inactive_agents: ExecInactiveAgent[];
	inactive_users: ExecInactiveUser[];
}

export interface ExecTimeToValueItem {
	id: string;
	name: string;
	category: string;
	created_at: string;
	days_to_100: number | null;
	current_sessions: number;
}

export interface ExecTimeToValueResponse {
	agents: ExecTimeToValueItem[];
	avg_days_to_100: number | null;
}

export interface ExecAIInsightsResponse {
	quick_wins: { title: string; detail: string; estimated_savings: string; effort: string }[];
	adoption_gaps: { title: string; detail: string; impact: string }[];
	platform_insight: { title: string; detail: string };
	model_insight: { title: string; detail: string };
	automation_opportunity: { title: string; detail: string };
	usage_pattern: { title: string; detail: string };
	generated: boolean;
}
