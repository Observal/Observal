// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
// SPDX-License-Identifier: AGPL-3.0-only

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

export interface AgentComponentReference {
	component_type: string;
	component_id: string;
	name?: string;
	component_name?: string;
	mcp_name?: string;
	resolved_version?: string;
	status?: string;
}

export interface AgentVersionDetail extends AgentVersionSummary {
	prompt: string;
	model_name: string;
	model_config_json?: Record<string, unknown>;
	models_by_ide?: Record<string, unknown>;
	external_mcps?: unknown[];
	yaml_snapshot?: unknown;
	ide_configs?: Record<string, unknown>;
	required_ide_features?: string[];
	inferred_supported_ides?: string[];
	components: AgentComponentReference[];
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
	scope?: string;
	tool_filter?: Record<string, unknown>;
	script_content?: string;
	script_filename?: string;
	source_path?: string;
	requirements?: string[];
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
	scope?: string;
	tool_filter?: string[];
	priority?: number;
	script_content?: string;
	script_filename?: string;
	source_url?: string;
	source_ref?: string;
	source_path?: string;
	resolved_sha?: string;
	requirements?: string[];

	// Prompt-specific
	category?: string;
	template?: string;
	variables?: unknown[];
	model_hints?: Record<string, unknown>;
	tags?: string[];

	// Sandbox-specific
	runtime_type?: string;
	image?: string;
	resource_limits?: Record<string, unknown>;
	network_policy?: string;
	entrypoint?: string;
	sandbox_path?: string;
	validated_at?: string;

	// Agent-specific
	prompt?: string;
	model_name?: string;
	model_config_json?: Record<string, unknown>;
	external_mcps?: unknown[];
	required_ide_features?: string[];
	component_count?: number;
	components?: { component_type: string; component_id: string }[];
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
	user_id?: string | null;
	rating: number;
	comment?: string;
	anonymous?: boolean;
	user?: string;
	username?: string;
	created_at?: string;
	updated_at?: string | null;
}
