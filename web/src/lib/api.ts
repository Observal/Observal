import type {
  OverviewStats,
  TopItem,
  TopAgentItem,
  TrendPoint,
  OtelStats,
  OtelTrace,
  OtelSessionData,
  TokenStats,
  FeedbackItem,
  FeedbackSummary,
  Scorecard,
  TracePenalty,
  AgentAggregate,
  IdeUsageData,
  AdminUser,
  AdminSetting,
  OtelSession,
  OtelErrorEvent,
  TelemetryStatus,
  ReviewItem,
  RegistryItem,
  LeaderboardItem,
  LeaderboardWindow,
  ValidationResult,
} from "./types";

const API = "/api/v1";

function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("observal_api_key");
}

export function setApiKey(key: string) {
  localStorage.setItem("observal_api_key", key);
}

export function clearApiKey() {
  localStorage.removeItem("observal_api_key");
  localStorage.removeItem("observal_user_role");
}

export function setUserRole(role: string) {
  localStorage.setItem("observal_user_role", role);
}

export function getUserRole(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("observal_user_role");
}

export function clearSession() {
  localStorage.removeItem("observal_api_key");
  localStorage.removeItem("observal_user_role");
}

async function request<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const key = getApiKey();
  if (key) headers["X-API-Key"] = key;

  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function get<T = unknown>(path: string) {
  return request<T>("GET", path);
}
function post<T = unknown>(path: string, body?: unknown) {
  return request<T>("POST", path, body);
}
function put<T = unknown>(path: string, body?: unknown) {
  return request<T>("PUT", path, body);
}
function del<T = unknown>(path: string) {
  return request<T>("DELETE", path);
}

export async function graphql<T = unknown>(
  query: string,
  variables?: Record<string, unknown>,
): Promise<T> {
  const res = await post<{ data: T; errors?: { message: string }[] }>(
    "/graphql",
    { query, variables },
  );
  if (res.errors?.length) throw new Error(res.errors[0].message);
  return res.data;
}

// ── Auth ────────────────────────────────────────────────────────────
type AuthResponse = { user: { id: string; email: string; name: string; role: string; created_at: string }; api_key: string };

export const auth = {
  init: (body: { email: string; name: string; password?: string }) =>
    post<AuthResponse>("/auth/init", body),
  register: (body: { email: string; name: string; password: string }) =>
    post<AuthResponse>("/auth/register", body),
  login: (body: { api_key?: string; email?: string; password?: string }) =>
    post<AuthResponse>("/auth/login", body),
  whoami: () => get<{ id: string; email: string; name: string; role: string }>("/auth/whoami"),
  requestReset: (body: { email: string }) =>
    post<{ message: string }>("/auth/request-reset", body),
  resetPassword: (body: { email: string; token: string; new_password: string }) =>
    post<AuthResponse>("/auth/reset-password", body),
  exchangeCode: (body: { code: string }) =>
    post<AuthResponse>("/auth/exchange", body),
};

// ── Registry (all 8 types) ─────────────────────────────────────────
export type RegistryType =
  | "mcps"
  | "agents"
  | "skills"
  | "hooks"
  | "prompts"
  | "sandboxes";

export const registry = {
  list: (type: RegistryType, params?: Record<string, string>) => {
    const qs = params ? `?${new URLSearchParams(params)}` : "";
    return get<RegistryItem[]>(`/${type}${qs}`);
  },
  get: (type: RegistryType, id: string) => get<RegistryItem>(`/${type}/${id}`),
  create: (type: RegistryType, body: unknown) => post<RegistryItem>(`/${type}`, body),
  install: (type: RegistryType, id: string, body?: unknown) =>
    post<unknown>(`/${type}/${id}/install`, body),
  delete: (type: RegistryType, id: string) => del(`/${type}/${id}`),
  metrics: (type: RegistryType, id: string) =>
    get<unknown>(`/${type}/${id}/metrics`),
  resolve: (id: string) => get<unknown>(`/agents/${id}/resolve`),
  manifest: (id: string) => get<Record<string, unknown>>(`/agents/${id}/manifest`),
  downloads: (id: string) =>
    get<{ total: number; unique_users: number; recent_7d: number }>(`/agents/${id}/downloads`),
  validate: (body: { components: { component_type: string; component_id: string }[] }) =>
    post<ValidationResult>("/agents/validate", body),
};

// ── Review ──────────────────────────────────────────────────────────
export const review = {
  list: (params?: Record<string, string>) => {
    const qs = params ? `?${new URLSearchParams(params)}` : "";
    return get<ReviewItem[]>(`/review${qs}`);
  },
  get: (id: string) => get<ReviewItem>(`/review/${id}`),
  approve: (id: string) => post(`/review/${id}/approve`),
  reject: (id: string, body: { reason: string }) =>
    post(`/review/${id}/reject`, body),
};

// ── Telemetry ───────────────────────────────────────────────────────
export const telemetry = {
  status: () => get<TelemetryStatus>("/telemetry/status"),
  ingest: (body: unknown) => post<unknown>("/telemetry/ingest", body),
};

// ── Dashboard ───────────────────────────────────────────────────────
export const dashboard = {
  stats: (range?: string) => get<OverviewStats>(`/overview/stats${range ? `?range=${range}` : ''}`),
  topMcps: () => get<TopItem[]>("/overview/top-mcps"),
  topAgents: (limit?: number) => get<TopAgentItem[]>(`/overview/top-agents${limit ? `?limit=${limit}` : ''}`),
  leaderboard: (window?: LeaderboardWindow, limit?: number) => {
    const params = new URLSearchParams();
    if (window) params.set("window", window);
    if (limit) params.set("limit", String(limit));
    const qs = params.toString();
    return get<LeaderboardItem[]>(`/overview/leaderboard${qs ? `?${qs}` : ''}`);
  },
  trends: (range?: string) => get<TrendPoint[]>(`/overview/trends${range ? `?range=${range}` : ''}`),
  mcpMetrics: (id: string) => get<unknown>(`/mcps/${id}/metrics`),
  agentMetrics: (id: string) => get<unknown>(`/agents/${id}/metrics`),
  tokenStats: (range?: string) => get<TokenStats>(`/dashboard/tokens${range ? `?range=${range}` : ''}`),
  ideUsage: () => get<IdeUsageData>('/dashboard/ide-usage'),
  otelSessions: () => get<OtelSession[]>('/otel/sessions'),
  otelSession: (id: string) => get<OtelSessionData>(`/otel/sessions/${encodeURIComponent(id)}`),
  otelTraces: () => get<OtelTrace[]>('/otel/traces'),
  otelTrace: (id: string) => get<unknown>(`/otel/traces/${encodeURIComponent(id)}`),
  otelStats: () => get<OtelStats>('/otel/stats'),
  otelErrors: () => get<OtelErrorEvent[]>('/otel/errors'),
};

// ── Feedback ────────────────────────────────────────────────────────
export const feedback = {
  submit: (body: {
    listing_type: string;
    listing_id: string;
    rating: number;
    comment?: string;
  }) => post<FeedbackItem>("/feedback", body),
  get: (type: string, id: string) => get<FeedbackItem[]>(`/feedback/${type}/${id}`),
  summary: (id: string) => get<FeedbackSummary>(`/feedback/summary/${id}`),
};

// ── Eval ────────────────────────────────────────────────────────────
export const eval_ = {
  run: (agentId: string, body?: unknown) =>
    post<unknown>(`/eval/agents/${agentId}`, body),
  scorecards: (agentId: string, params?: Record<string, string>) => {
    const qs = params ? `?${new URLSearchParams(params)}` : "";
    return get<Scorecard[]>(`/eval/agents/${agentId}/scorecards${qs}`);
  },
  show: (scorecardId: string) =>
    get<Scorecard>(`/eval/scorecards/${scorecardId}`),
  compare: (agentId: string, params: Record<string, string>) => {
    const qs = `?${new URLSearchParams(params)}`;
    return get<unknown>(`/eval/agents/${agentId}/compare${qs}`);
  },
  aggregate: (agentId: string, windowSize?: number) => {
    const qs = windowSize ? `?window_size=${windowSize}` : "";
    return get<AgentAggregate>(`/eval/agents/${agentId}/aggregate${qs}`);
  },
  penalties: (scorecardId: string) =>
    get<TracePenalty[]>(`/eval/scorecards/${scorecardId}/penalties`),
};

// ── Admin ───────────────────────────────────────────────────────────
export const admin = {
  settings: () => get<AdminSetting[] | Record<string, string>>("/admin/settings"),
  updateSetting: (key: string, body: unknown) =>
    put<unknown>(`/admin/settings/${key}`, body),
  deleteSetting: (key: string) => del(`/admin/settings/${key}`),
  users: () => get<AdminUser[]>("/admin/users"),
  createUser: (body: { email: string; name: string; role?: string }) =>
    post<{ id: string; email: string; name: string; role: string; api_key: string }>("/admin/users", body),
  updateRole: (id: string, body: { role: string }) =>
    put<AdminUser>(`/admin/users/${id}/role`, body),
  resetPassword: (id: string, body: { new_password: string }) =>
    put<{ message: string }>(`/admin/users/${id}/password`, body),
};

// ── Health ──────────────────────────────────────────────────────────
export const health = () =>
  fetch("/health").then((r) => r.json());
