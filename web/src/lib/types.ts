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

export interface SessionData {
  session_id: string;
  events: RawSessionEvent[];
  traces: unknown[];
  service_name: string;
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
  target_agents?: string[];
  task_type?: string;
  triggers?: Record<string, unknown>;
  slash_command?: string;
  has_scripts?: boolean;
  has_templates?: boolean;
  is_power?: boolean;
  power_md?: string;
  mcp_server_config?: Record<string, unknown>;
  activation_keywords?: string[];
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
  component_blockers?: { component_type: string; component_id: string; name: string; status: string }[];
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
  target_agents?: string[];
  task_type?: string;
  triggers?: Record<string, unknown>;
  slash_command?: string;
  mcp_server_config?: Record<string, unknown>;
  has_scripts?: boolean;
  has_templates?: boolean;
  is_power?: boolean;
  power_md?: string;
  activation_keywords?: string[];

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
  visibility?: 'public' | 'private';
  team_accesses?: { group_name: string; permission: 'view' | 'edit' }[];
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
  model: string;
  service_name: string;
  user_id?: string;
  user_name?: string;
  platform?: string;
  terminal_type?: string;
  credits?: string;
  tools_used?: string;
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
  at_a_glance: string;
  usage_patterns: string[];
  friction_analysis: string[];
  suggestions: string[];
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
