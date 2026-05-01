import type {
  OverviewStats,
  TopItem,
  TopAgentItem,
  TrendPoint,
  SessionsStats,
  SessionTrace,
  SessionData,
  TokenStats,
  FeedbackItem,
  FeedbackSummary,
  Scorecard,
  TracePenalty,
  AgentAggregate,
  IdeUsageData,
  AdminUser,
  AdminSetting,
  Session,
  SessionsSummary,
  SessionErrorEvent,
  TelemetryStatus,
  ReviewItem,
  RegistryItem,
  LeaderboardItem,
  LeaderboardWindow,
  ValidationResult,
  VersionSuggestions,
  AgentVersionsResponse,
  BulkResult,
  ComponentLeaderboardItem,
  AuditLogEntry,
  SecurityEvent,
  DiagnosticsResponse,
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

  let res: Response | undefined;
  for (let attempt = 0; attempt < 2; attempt++) {
    res = await fetch(`${API}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (res.status < 500) break;
    // Brief pause before retry on 5xx
    if (attempt === 0) await new Promise((r) => setTimeout(r, 500));
  }
  const response = res!;

  if (!response.ok) {
    // Auto-refresh on 401 (except for auth endpoints where 401 means bad credentials)
    if (response.status === 401 && !path.startsWith("/auth/")) {
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

    const text = await response.text().catch(() => response.statusText);
    throw new Error(`${response.status}: ${text}`);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
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
  login: (body: { email: string; password: string }) =>
    post<AuthResponse & { must_change_password?: boolean }>("/auth/login", body),
  whoami: () => get<{ id: string; email: string; username?: string | null; name: string; role: string }>("/auth/whoami"),
  exchangeCode: (body: { code: string }) =>
    post<AuthResponse>("/auth/exchange", body),
  deviceConfirm: (userCode: string) =>
    post<{ message: string }>("/auth/device/confirm", { user_code: userCode }),
  changePassword: (body: { current_password: string; new_password: string }) =>
    put<{ message: string }>("/auth/profile/password", body),
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
  updateAgent: (id: string, body: unknown) =>
    put<RegistryItem>(`/agents/${id}`, body),
  submitDraft: (id: string, type?: RegistryType) =>
    post(`/${type ?? "agents"}/${id}/submit`),
  submit: (type: RegistryType, body: unknown) =>
    post<RegistryItem>(`/${type}/submit`, body),
  versionSuggestions: (id: string) =>
    get<VersionSuggestions>(`/agents/${id}/version-suggestions`),
  listVersions: (agentId: string, page = 1, pageSize = 50) =>
    get<AgentVersionsResponse>(`/agents/${agentId}/versions?page=${page}&page_size=${pageSize}`),
  getVersion: (agentId: string, version: string) =>
    get<unknown>(`/agents/${agentId}/versions/${version}`),
  createVersion: (agentId: string, body: unknown) =>
    post<unknown>(`/agents/${agentId}/versions`, body),
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
  relatedSkills: (id: string) =>
    get<{ skills: ReviewItem[] }>(`/review/${id}/related-skills`),
  approveWithSkills: (id: string, body: { skill_ids: string[] }) =>
    post(`/review/${id}/approve-with-skills`, body),
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
  componentLeaderboard: (window?: LeaderboardWindow, limit?: number) => {
    const params = new URLSearchParams();
    if (window) params.set("window", window);
    if (limit) params.set("limit", String(limit));
    const qs = params.toString();
    return get<ComponentLeaderboardItem[]>(`/overview/component-leaderboard${qs ? `?${qs}` : ''}`);
  },
  trends: (range?: string) => get<TrendPoint[]>(`/overview/trends${range ? `?range=${range}` : ''}`),
  mcpMetrics: (id: string) => get<unknown>(`/mcps/${id}/metrics`),
  agentMetrics: (id: string) => get<unknown>(`/agents/${id}/metrics`),
  tokenStats: (range?: string) => get<TokenStats>(`/dashboard/tokens${range ? `?range=${range}` : ''}`),
  ideUsage: () => get<IdeUsageData>('/dashboard/ide-usage'),
  sessions: (params?: { status?: string; platform?: string; days?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.platform) qs.set("platform", params.platform);
    if (params?.days) qs.set("days", String(params.days));
    const suffix = qs.toString() ? `?${qs}` : "";
    return get<Session[]>(`/sessions${suffix}`);
  },
  sessionsSummary: () => get<SessionsSummary>('/sessions/summary'),
  session: (id: string) => get<SessionData>(`/sessions/${encodeURIComponent(id)}`),
  traces: () => get<SessionTrace[]>('/sessions/traces'),
  trace: (id: string) => get<unknown>(`/sessions/traces/${encodeURIComponent(id)}`),
  sessionsStats: () => get<SessionsStats>('/sessions/stats'),
  sessionsErrors: () => get<SessionErrorEvent[]>('/sessions/errors'),
  sessionEfficiency: (sessionId: string) => get<Record<string, unknown>>(`/sessions/${encodeURIComponent(sessionId)}/efficiency`),
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
  resetPassword: (id: string, body: { new_password?: string; generate?: boolean }) =>
    put<{ message: string; generated_password?: string; must_change_password?: string }>(`/admin/users/${id}/password`, body),
  deleteUser: (id: string) => del(`/admin/users/${id}`),
  applyResources: () =>
    post<{ applied: Record<string, string>; message: string }>("/admin/resources/apply", {}),
  getTracePrivacy: () =>
    get<{ trace_privacy: boolean }>("/admin/org/trace-privacy"),
  setTracePrivacy: (enabled: boolean) =>
    put<{ trace_privacy: boolean }>("/admin/org/trace-privacy", { trace_privacy: enabled }),
  auditLog: (params?: Record<string, string>) => {
    const qs = params ? `?${new URLSearchParams(params)}` : "";
    return get<AuditLogEntry[]>(`/admin/audit-log${qs}`);
  },
  auditLogExport: (params?: Record<string, string>) => {
    const qs = params ? `?${new URLSearchParams(params)}` : "";
    return get<string>(`/admin/audit-log/export${qs}`);
  },
  securityEvents: (params?: Record<string, string>) => {
    const qs = params ? `?${new URLSearchParams(params)}` : "";
    return get<{ events: SecurityEvent[]; total: number }>(`/admin/security-events${qs}`);
  },
  diagnostics: () => get<DiagnosticsResponse>("/admin/diagnostics"),
  samlConfig: () => get<Record<string, unknown>>("/admin/saml-config"),
  updateSamlConfig: (body: Record<string, unknown>) =>
    put<Record<string, unknown>>("/admin/saml-config", body),
  deleteSamlConfig: () => del("/admin/saml-config"),
  scimTokens: () => get<{ id: string; description: string; active: boolean; created_at: string; token_prefix: string }[]>("/admin/scim-tokens"),
  createScimToken: (body: { description?: string }) =>
    post<{ id: string; token: string; description: string; message: string }>("/admin/scim-tokens", body),
  revokeScimToken: (id: string) => del(`/admin/scim-tokens/${id}`),
};

// ── Config ─────────────────────────────────────────────────────────
export type PublicConfig = {
  deployment_mode: "local" | "enterprise";
  sso_enabled: boolean;
  sso_only: boolean;
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
