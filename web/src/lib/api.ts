const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const API = `${BASE_URL}/api/v1`;

function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("observal_api_key");
}

export function setApiKey(key: string) {
  localStorage.setItem("observal_api_key", key);
}

export function clearApiKey() {
  localStorage.removeItem("observal_api_key");
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
export const auth = {
  init: (body: { username: string; password: string }) =>
    post<{ api_key: string }>("/auth/init", body),
  login: (body: { api_key: string }) =>
    post<{ username: string }>("/auth/login", body),
  whoami: () => get<{ id: string; username: string; role: string }>("/auth/whoami"),
};

// ── Registry (all 8 types) ─────────────────────────────────────────
export type RegistryType =
  | "mcps"
  | "agents"
  | "tools"
  | "skills"
  | "hooks"
  | "prompts"
  | "sandboxes"
  | "graphrags";

export const registry = {
  list: (type: RegistryType, params?: Record<string, string>) => {
    const qs = params ? `?${new URLSearchParams(params)}` : "";
    return get<unknown[]>(`/${type}${qs}`);
  },
  get: (type: RegistryType, id: string) => get<unknown>(`/${type}/${id}`),
  create: (type: RegistryType, body: unknown) => post<unknown>(`/${type}`, body),
  install: (type: RegistryType, id: string, body?: unknown) =>
    post<unknown>(`/${type}/${id}/install`, body),
  delete: (type: RegistryType, id: string) => del(`/${type}/${id}`),
  metrics: (type: RegistryType, id: string) =>
    get<unknown>(`/${type}/${id}/metrics`),
};

// ── Review ──────────────────────────────────────────────────────────
export const review = {
  list: (params?: Record<string, string>) => {
    const qs = params ? `?${new URLSearchParams(params)}` : "";
    return get<unknown[]>(`/review${qs}`);
  },
  get: (id: string) => get<unknown>(`/review/${id}`),
  approve: (id: string) => post(`/review/${id}/approve`),
  reject: (id: string, body: { reason: string }) =>
    post(`/review/${id}/reject`, body),
};

// ── Telemetry ───────────────────────────────────────────────────────
export const telemetry = {
  status: () => get<unknown>("/telemetry/status"),
  ingest: (body: unknown) => post<unknown>("/telemetry/ingest", body),
};

// ── Dashboard ───────────────────────────────────────────────────────
export const dashboard = {
  stats: () => get<unknown>("/overview/stats"),
  topMcps: () => get<unknown[]>("/overview/top-mcps"),
  topAgents: () => get<unknown[]>("/overview/top-agents"),
  trends: () => get<unknown>("/overview/trends"),
  mcpMetrics: (id: string) => get<unknown>(`/mcps/${id}/metrics`),
  agentMetrics: (id: string) => get<unknown>(`/agents/${id}/metrics`),
  tokenStats: () => get<unknown>('/dashboard/tokens'),
  ideUsage: () => get<unknown>('/dashboard/ide-usage'),
  sandboxMetrics: () => get<unknown>('/dashboard/sandbox-metrics'),
  graphragMetrics: () => get<unknown>('/dashboard/graphrag-metrics'),
  latencyHeatmap: () => get<unknown[]>('/dashboard/latency-heatmap'),
  unannotatedTraces: () => get<unknown[]>('/dashboard/unannotated-traces'),
  otelSessions: () => get<unknown[]>('/otel/sessions'),
  otelSession: (id: string) => get<unknown>(`/otel/sessions/${encodeURIComponent(id)}`),
  otelTraces: () => get<unknown[]>('/otel/traces'),
  otelTrace: (id: string) => get<unknown>(`/otel/traces/${encodeURIComponent(id)}`),
  otelStats: () => get<unknown>('/otel/stats'),
};

// ── Feedback ────────────────────────────────────────────────────────
export const feedback = {
  submit: (body: {
    listing_type: string;
    listing_id: string;
    stars: number;
    comment?: string;
  }) => post<unknown>("/feedback", body),
  get: (type: string, id: string) => get<unknown[]>(`/feedback/${type}/${id}`),
  summary: (id: string) => get<unknown>(`/feedback/summary/${id}`),
};

// ── Eval ────────────────────────────────────────────────────────────
export const eval_ = {
  run: (agentId: string, body?: unknown) =>
    post<unknown>(`/eval/agents/${agentId}`, body),
  scorecards: (agentId: string, params?: Record<string, string>) => {
    const qs = params ? `?${new URLSearchParams(params)}` : "";
    return get<unknown[]>(`/eval/agents/${agentId}/scorecards${qs}`);
  },
  show: (scorecardId: string) =>
    get<unknown>(`/eval/scorecards/${scorecardId}`),
  compare: (agentId: string, params: Record<string, string>) => {
    const qs = `?${new URLSearchParams(params)}`;
    return get<unknown>(`/eval/agents/${agentId}/compare${qs}`);
  },
};

// ── Admin ───────────────────────────────────────────────────────────
export const admin = {
  settings: () => get<unknown>("/admin/settings"),
  updateSetting: (key: string, body: unknown) =>
    put<unknown>(`/admin/settings/${key}`, body),
  users: () => get<unknown[]>("/admin/users"),
  createUser: (body: unknown) => post<unknown>("/admin/users", body),
  updateRole: (id: string, body: { role: string }) =>
    put<unknown>(`/admin/users/${id}/role`, body),
};

// ── Health ──────────────────────────────────────────────────────────
export const health = () =>
  fetch(`${BASE_URL}/health`).then((r) => r.json());
