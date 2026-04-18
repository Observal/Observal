// ── Overview ────────────────────────────────────────────────────────

export interface OverviewStats {
  total_mcps: number;
  total_agents: number;
  total_users: number;
  total_tool_calls_today: number;
  total_agent_interactions_today: number;
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

// ── OTel ────────────────────────────────────────────────────────────

export interface OtelStats {
  total_sessions: number;
  total_prompts: number;
  total_api_requests: number;
  total_tool_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_traces: number;
  total_spans: number;
}

export interface OtelTrace {
  trace_id: string;
  span_name: string;
  service_name?: string;
  duration_ns: number;
  status: string;
  session_id?: string;
  timestamp?: string;
}

export interface OtelSessionData {
  session_id: string;
  events: RawOtelEvent[];
  traces: unknown[];
  service_name: string;
}

export interface RawOtelEvent {
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

export type LeaderboardItem = TopAgentItem;
export type LeaderboardWindow = "24h" | "7d" | "30d" | "all";

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

// ── Review ──────────────────────────────────────────────────────────

export interface McpValidationResult {
  stage: string;
  passed: boolean;
  details?: string;
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
  status?: string;
  mcp_validated?: boolean;
  validation_results?: McpValidationResult[];
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

// ── OTel Sessions ───────────────────────────────────────────────────

export interface OtelSession {
  session_id: string;
  first_event_time: string;
  last_event_time: string;
  is_active?: boolean;
  prompt_count: number;
  api_request_count: number;
  tool_result_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  model: string;
  service_name: string;
}

export interface OtelErrorEvent {
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

// ── Telemetry ───────────────────────────────────────────────────────

export interface TelemetryStatus {
  clickhouse: boolean;
  traces_count: number;
  spans_count: number;
  scores_count: number;
}
