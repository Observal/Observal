// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
// SPDX-License-Identifier: AGPL-3.0-only

// ── Overview ────────────────────────────────────────────────────────

export interface OverviewStats {
	total_mcps: number;
	total_agents: number;
	total_users: number;
	total_tool_calls: number;
	total_agent_interactions: number;
}

export interface TopItem {
	id: string;
	name: string;
	value: number;
}

export interface TrendPoint {
	date: string;
	submissions: number;
	users: number;
}

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
	subagent_sessions?: SubagentSession[];
}

export interface RawSessionEvent {
	timestamp: string;
	event_name: string;
	body?: string;
	attributes?: Record<string, string>;
	service_name?: string;
}

// ── Tokens ──────────────────────────────────────────────────────────

export interface TokenStats {
	total_input: number;
	total_output: number;
	total_tokens: number;
	avg_per_trace: number;
	by_agent: TokenUsageRow[];
	by_mcp: TokenUsageRow[];
	over_time: { date: string; input: number; output: number }[];
}

export interface TokenUsageRow {
	name: string;
	input: number;
	output: number;
	total: number;
	traces: number;
}

// ── Registry ────────────────────────────────────────────────────────

export interface RegistryItem {
	id: string;
	name: string;
	description?: string;
	status?: string;
	rejection_reason?: string;
	created_at?: string;
	updated_at?: string;
	[key: string]: unknown;
}

// ── Agent enriched types ────────────────────────────────────────────

export interface TopAgentItem {
	id: string;
	name: string;
	description: string;
	owner: string;
	created_by_username?: string | null;
	version: string;
	download_count: number;
	average_rating: number | null;
}

export interface LeaderboardItem extends TopAgentItem {
	created_by_email?: string;
}
export type LeaderboardWindow = "24h" | "7d" | "30d" | "all";

export interface ComponentLeaderboardItem {
	id: string;
	name: string;
	component_type: string;
	description: string;
	download_count: number;
	created_by_email: string;
	average_rating: number | null;
	total_reviews: number;
}

export interface VersionSuggestions {
	current: string;
	suggestions: {
		patch: string;
		minor: string;
		major: string;
	};
}

export interface AgentVersionSummary {
	id: string;
	agent_id: string;
	version: string;
	description: string;
	status: string;
	is_prerelease: boolean;
	download_count: number;
	supported_ides: string[];
	released_by: string;
	released_at: string | null;
	created_at: string | null;
	rejection_reason: string | null;
	component_count: number;
}

export interface AgentVersionsResponse {
	items: AgentVersionSummary[];
	total: number;
	page: number;
	page_size: number;
}

// ── Component Versions ─────────────────────────────────────────────

export interface ComponentVersionSummary {
	id: string;
	listing_id: string;
	version: string;
	description: string;
	changelog: string | null;
	status: string;
	rejection_reason: string | null;
	download_count: number;
	supported_ides: string[];
	released_by: string;
	released_at: string | null;
	created_at: string | null;
	// Hook fields
	event?: string;
	execution_mode?: string;
	priority?: number;
	handler_type?: string;
	handler_config?: Record<string, unknown>;
	input_schema?: Record<string, unknown>;
	output_schema?: Record<string, unknown>;
	scope?: string;
	tool_filter?: Record<string, unknown>;
	file_pattern?: string[];
	// Skill fields
	skill_path?: string;
	git_url?: string;
	git_ref?: string;
	skill_md_content?: string;
	validated?: boolean;
	target_agents?: string[];
	task_type?: string;
	slash_command?: string;
	// Prompt fields
	category?: string;
	template?: string;
	variables?: unknown[];
	model_hints?: Record<string, unknown>;
	tags?: string[];
	// MCP/Sandbox fields
	source_url?: string;
	source_ref?: string;
	resolved_sha?: string;
}

export interface ComponentVersionsResponse {
	items: ComponentVersionSummary[];
	total: number;
	page: number;
	page_size: number;
}

export type ComponentVersionDetail = ComponentVersionSummary;

export interface BulkResultItem {
	name: string;
	status: "created" | "skipped" | "error";
	agent_id?: string | null;
	error?: string | null;
}

export interface BulkResult {
	total: number;
	created: number;
	skipped: number;
	errors: number;
	dry_run: boolean;
	results: BulkResultItem[];
}

export interface FeedbackSummary {
	listing_id: string;
	average_rating: number;
	total_reviews: number;
}

export interface ValidationIssue {
	severity: "error" | "warning";
	component_type?: string;
	component_id?: string;
	message: string;
}

export interface ValidationResult {
	valid: boolean;
	issues: ValidationIssue[];
}

// ── Version Diff ────────────────────────────────────────────────────

export interface ComponentChange {
	type: string;
	name: string;
	change: "added" | "removed" | "updated";
	version?: string;
	from?: string;
	to?: string;
}

export interface VersionDiff {
	agent_id: string;
	version_a: string;
	version_b: string;
	yaml_diff: string;
	component_changes: ComponentChange[];
}

// ── Review ──────────────────────────────────────────────────────────

export interface McpValidationResult {
	stage: string;
	passed: boolean;
	details?: string;
	run_at?: string;
}

export interface ReviewItem {
	id: string;
	name?: string;
	description?: string;
	version?: string;
	owner?: string;
	type?: string;
	listing_type?: string;
	submitted_by?: string;
	submitted_at?: string;
	created_at?: string;
	updated_at?: string;
	status?: string;
	mcp_validated?: boolean;
	validation_results?: McpValidationResult[];
	components_ready?: boolean;
	component_blockers?: {
		component_type: string;
		component_id: string;
		name: string;
		status: string;
	}[];
	bundle_id?: string;
	bundle_name?: string;
	rejection_reason?: string;

	// Common detail fields
	git_url?: string;
	git_ref?: string;
	supported_ides?: string[];

	// MCP-specific
	transport?: string;
	framework?: string;
	docker_image?: string;
	command?: string;
	args?: string[];
	url?: string;
	headers?: unknown[];
	auto_approve?: string[];
	tools_schema?: Record<string, unknown>;
	environment_variables?: unknown[];
	setup_instructions?: string;
	changelog?: string;

	// Skill-specific
	skill_path?: string;
	skill_md_content?: string;
	validated?: boolean;
	target_agents?: string[];
	task_type?: string;
	slash_command?: string;

	// Hook-specific
	event?: string;
	execution_mode?: string;
	handler_type?: string;
	handler_config?: Record<string, unknown>;
	input_schema?: Record<string, unknown>;
	output_schema?: Record<string, unknown>;
	scope?: string;
	tool_filter?: string[];
	file_pattern?: string[];
	priority?: number;

	// Prompt-specific
	category?: string;
	template?: string;
	variables?: unknown[];
	model_hints?: Record<string, unknown>;
	tags?: string[];

	// Sandbox-specific
	runtime_type?: string;
	image?: string;
	dockerfile_url?: string;
	resource_limits?: Record<string, unknown>;
	network_policy?: string;
	allowed_mounts?: string[];
	env_vars?: Record<string, unknown>;
	entrypoint?: string;

	// Agent-specific
	prompt?: string;
	model_name?: string;
	model_config_json?: Record<string, unknown>;
	external_mcps?: unknown[];
	required_ide_features?: string[];
	component_count?: number;
	components?: { component_type: string; component_id: string }[];
	visibility?: "public" | "private";
	team_accesses?: { group_name: string; permission: "view" | "edit" }[];
}

// ── Scores ──────────────────────────────────────────────────────────

export interface Score {
	score_id: string;
	trace_id: string;
	span_id?: string;
	name: string;
	source: string;
	data_type: string;
	value?: number;
	string_value?: string;
	comment?: string;
	timestamp: string;
}

// ── Feedback ────────────────────────────────────────────────────────

export interface FeedbackItem {
	id: string;
	listing_id?: string;
	listing_name?: string;
	listing_type?: string;
	rating: number;
	comment?: string;
	user?: string;
	username?: string;
	created_at?: string;
}

// ── Eval ────────────────────────────────────────────────────────────

export interface Scorecard {
	id: string;
	agent_id?: string;
	agent_name?: string;
	version?: string;
	status?: string;
	overall_score?: number;
	created_at?: string;
	dimensions?: { name: string; score: number; comment?: string }[];
	metadata?: Record<string, unknown>;
	// New structured scoring fields
	dimension_scores?: Record<string, number>;
	composite_score?: number;
	display_score?: number;
	grade?: string;
	overall_grade?: string;
	scoring_recommendations?: string[];
	penalty_count?: number;
}

export interface TracePenalty {
	event_name: string;
	dimension: string;
	amount: number;
	evidence: string;
	severity?: string;
	trace_event_index?: number | null;
}

export interface AgentAggregate {
	mean: number;
	std: number;
	ci_low: number;
	ci_high: number;
	dimension_averages: Record<string, number>;
	weakest_dimension: string | null;
	drift_alert: boolean;
	trend: { timestamp: string; composite: number }[];
}

// ── IDE Usage ───────────────────────────────────────────────────────

export interface IdeRow {
	ide: string;
	traces: number;
	avg_latency_ms: number;
	error_count: number;
	error_rate: number;
}

export interface IdeUsageData {
	ides: IdeRow[];
}

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
	deployment_mode: string;
	checks: Record<string, Record<string, unknown>>;
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
	// V2 structured format — each section is a structured object
	// V1 fallback — each section is string[] | string
	// The frontend handles both formats gracefully
	at_a_glance: unknown;
	usage_patterns: unknown;
	user_experience?: unknown;
	what_works?: unknown;
	friction_analysis: unknown;
	suggestions: unknown;
	token_optimization?: unknown;
	regression_detection?: unknown;
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
	sessions_analyzed: number;
	llm_model_used: string | null;
	error_message: string | null;
	started_at: string;
	completed_at: string | null;
	created_at: string;
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
