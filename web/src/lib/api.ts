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
  VersionSuggestions,
  BulkResult,
  ComponentLeaderboardItem,
} from "./types";

const API = "/api/v1";

function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("observal_access_token");
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("observal_refresh_token");
}

export function setTokens(accessToken: string, refreshToken: string) {
  localStorage.setItem("observal_access_token", accessToken);
  localStorage.setItem("observal_refresh_token", refreshToken);
}

export function clearSession() {
  localStorage.removeItem("observal_access_token");
  localStorage.removeItem("observal_refresh_token");
  localStorage.removeItem("observal_api_key"); // clean up legacy
  localStorage.removeItem("observal_user_role");
  localStorage.removeItem("observal_user_name");
  localStorage.removeItem("observal_user_email");
}

export function setUserRole(role: string) {
  localStorage.setItem("observal_user_role", role);
}

export function getUserRole(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("observal_user_role");
}

export function setUserName(name: string) {
  localStorage.setItem("observal_user_name", name);
}

export function getUserName(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("observal_user_name");
}

export function setUserEmail(email: string) {
  localStorage.setItem("observal_user_email", email);
}

export function getUserEmail(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("observal_user_email");
}

let _refreshPromise: Promise<boolean> | null = null;

async function _tryRefreshToken(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;

  try {
    const res = await fetch(`${API}/auth/token/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!res.ok) return false;

    const data = await res.json();
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

async function request<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const token = getAccessToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    // Auto-refresh on 401 (except for auth endpoints where 401 means bad credentials)
    if (res.status === 401 && !path.startsWith("/auth/")) {
      // Deduplicate concurrent refresh attempts
      if (!_refreshPromise) {
        _refreshPromise = _tryRefreshToken().finally(() => {
          _refreshPromise = null;
        });
      }
      const refreshed = await _refreshPromise;

      if (refreshed) {
        // Retry the original request with new token
        const newToken = getAccessToken();
        if (newToken) headers["Authorization"] = `Bearer ${newToken}`;
        const retryRes = await fetch(`${API}${path}`, {
          method,
          headers,
          body: body !== undefined ? JSON.stringify(body) : undefined,
        });
        if (retryRes.ok) {
          if (retryRes.status === 204) return undefined as T;
          return retryRes.json() as Promise<T>;
        }
      }

      // Refresh failed or retry failed — clear session
      clearSession();
      if (typeof window !== "undefined") {
        window.location.href = "/login?reason=session_expired";
      }
      throw new Error("Session expired");
    }

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
function patch<T = unknown>(path: string, body?: unknown) {
  return request<T>("PATCH", path, body);
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
type AuthResponse = {
  user: { id: string; email: string; username?: string | null; name: string; role: string; created_at: string };
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

export const auth = {
  init: (body: { email: string; name: string; password?: string }) =>
    post<AuthResponse>("/auth/init", body),
  register: (body: { email: string; name: string; password: string }) =>
    post<AuthResponse>("/auth/register", body),
  login: (body: { email: string; password: string }) =>
    post<AuthResponse>("/auth/login", body),
  whoami: () => get<{ id: string; email: string; username?: string | null; name: string; role: string }>("/auth/whoami"),
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
  my: (type?: RegistryType) => get<RegistryItem[]>(`/${type ?? "agents"}/my`),
  archive: (id: string) => patch(`/agents/${id}/archive`),
  unarchive: (id: string) => patch(`/agents/${id}/unarchive`),
  draft: (body: unknown, type?: RegistryType) =>
    post<RegistryItem>(`/${type ?? "agents"}/draft`, body),
  updateDraft: (id: string, body: unknown, type?: RegistryType) =>
    put<RegistryItem>(`/${type ?? "agents"}/${id}/draft`, body),
  submitDraft: (id: string, type?: RegistryType) =>
    post(`/${type ?? "agents"}/${id}/submit`),
  submit: (type: RegistryType, body: unknown) =>
    post<RegistryItem>(`/${type}/submit`, body),
  versionSuggestions: (id: string) =>
    get<VersionSuggestions>(`/agents/${id}/version-suggestions`),
};

// ── Review ──────────────────────────────────────────────────────────
export const review = {
  list: (params?: Record<string, string>) => {
    const qs = params ? `?${new URLSearchParams(params)}` : "";
    return get<ReviewItem[]>(`/review${qs}`);
  },
  listAgents: () => get<ReviewItem[]>("/review?tab=agents"),
  get: (id: string) => get<ReviewItem>(`/review/${id}`),
  approve: (id: string) => post(`/review/${id}/approve`),
  reject: (id: string, body: { reason: string }) =>
    post(`/review/${id}/reject`, body),
  approveAgent: (id: string) => post(`/review/agents/${id}/approve`),
  rejectAgent: (id: string, body: { reason: string }) =>
    post(`/review/agents/${id}/reject`, body),
  approveBundle: (id: string) => post(`/review/bundles/${id}/approve`),
  rejectBundle: (id: string, body: { reason: string }) =>
    post(`/review/bundles/${id}/reject`, body),
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
  leaderboard: (window?: LeaderboardWindow, limit?: number, user?: string) => {
    const params = new URLSearchParams();
    if (window) params.set("window", window);
    if (limit) params.set("limit", String(limit));
    if (user) params.set("user", user);
    const qs = params.toString();
    return get<LeaderboardItem[]>(`/overview/leaderboard${qs ? `?${qs}` : ''}`);
  },
  componentLeaderboard: () =>
    get<ComponentLeaderboardItem[]>("/overview/component-leaderboard"),
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
    post<{ id: string; email: string; name: string; role: string; password: string }>("/admin/users", body),
  updateRole: (id: string, body: { role: string }) =>
    put<AdminUser>(`/admin/users/${id}/role`, body),
  resetPassword: (id: string, body: { new_password: string }) =>
    put<{ message: string }>(`/admin/users/${id}/password`, body),
  deleteUser: (id: string) => del(`/admin/users/${id}`),
};

// ── Config ─────────────────────────────────────────────────────────
export type PublicConfig = {
  deployment_mode: "local" | "enterprise";
  sso_enabled: boolean;
  saml_enabled: boolean;
  eval_configured: boolean;
};

export const config = {
  public: () => get<PublicConfig>("/config/public"),
};

// ── Bulk ───────────────────────────────────────────────────────────
export const bulk = {
  createAgents: (body: { agents: unknown[]; dry_run?: boolean }) =>
    post<BulkResult>("/bulk/agents", body),
};

// ── Health ──────────────────────────────────────────────────────────
export const health = () =>
  fetch("/health").then((r) => r.json());
