
// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
// SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

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
	ComponentVersionsResponse,
	ComponentVersionDetail,
	VersionDiff,
	BulkResult,
	ComponentLeaderboardItem,
	AuditLogEntry,
	SecurityEvent,
	DiagnosticsResponse,
	SystemWarning,
	InsightReportListItem,
	InsightReport,
	ExecAdoptionResponse,
	ExecAgentCounts,
	ExecUsageByCategory,
	ExecPlatformCoverage,
	ExecPlatformScore,
	ExecVelocityResponse,
	ExecTopAgent,
	ExecConfig,
	ExecDepartmentsResponse,
	ExecDeptTokenItem,
	ExecCostSummary,
	ExecROIProjectionsResponse,
	ExecStrategicInsightsResponse,
	ExecDeveloperBreakdown,
	ExecInactivityAlerts,
	ExecTimeToValueResponse,
	ExecAIInsightsResponse,
} from "./types";

const API = "/api/v1";

const STORAGE_KEY_ACCESS_TOKEN = "observal_access_token";
const STORAGE_KEY_REFRESH_TOKEN = "observal_refresh_token";
const STORAGE_KEY_USER_ROLE = "observal_user_role";
const STORAGE_KEY_USER_NAME = "observal_user_name";
const STORAGE_KEY_USER_EMAIL = "observal_user_email";
const STORAGE_KEY_USER_USERNAME = "observal_user_username";
const STORAGE_KEY_USER_AVATAR = "observal_user_avatar";

// Access token is stored in sessionStorage (clears on tab close) to reduce
// the XSS exposure window. Refresh token stays in localStorage so silent
// refresh survives page reloads across tabs.
// TODO(SEC-025): migrate to HttpOnly cookies via a Next.js API route for
// full XSS protection.
function getAccessToken(): string | null {
	if (typeof window === "undefined") return null;
	return sessionStorage.getItem(STORAGE_KEY_ACCESS_TOKEN);
}

function getRefreshToken(): string | null {
	if (typeof window === "undefined") return null;
	return localStorage.getItem(STORAGE_KEY_REFRESH_TOKEN);
}

export function setTokens(accessToken: string, refreshToken: string) {
	sessionStorage.setItem(STORAGE_KEY_ACCESS_TOKEN, accessToken);
	localStorage.setItem(STORAGE_KEY_REFRESH_TOKEN, refreshToken);
}

export function clearSession() {
	sessionStorage.removeItem(STORAGE_KEY_ACCESS_TOKEN);
	localStorage.removeItem(STORAGE_KEY_REFRESH_TOKEN);
	localStorage.removeItem("observal_api_key"); // clean up legacy
	localStorage.removeItem(STORAGE_KEY_USER_ROLE);
	localStorage.removeItem(STORAGE_KEY_USER_NAME);
	localStorage.removeItem(STORAGE_KEY_USER_EMAIL);
	localStorage.removeItem(STORAGE_KEY_USER_USERNAME);
	localStorage.removeItem(STORAGE_KEY_USER_AVATAR);
}

export function setUserRole(role: string) {
	localStorage.setItem(STORAGE_KEY_USER_ROLE, role);
}

export function getUserRole(): string | null {
	if (typeof window === "undefined") return null;
	return localStorage.getItem(STORAGE_KEY_USER_ROLE);
}

export function setUserName(name: string) {
	localStorage.setItem(STORAGE_KEY_USER_NAME, name);
}

export function getUserName(): string | null {
	if (typeof window === "undefined") return null;
	return localStorage.getItem(STORAGE_KEY_USER_NAME);
}

export function setUserEmail(email: string) {
	localStorage.setItem(STORAGE_KEY_USER_EMAIL, email);
}

export function getUserEmail(): string | null {
	if (typeof window === "undefined") return null;
	return localStorage.getItem(STORAGE_KEY_USER_EMAIL);
}

export function setUserUsername(username: string) {
	localStorage.setItem(STORAGE_KEY_USER_USERNAME, username);
}

export function getUserUsername(): string | null {
	if (typeof window === "undefined") return null;
	return localStorage.getItem(STORAGE_KEY_USER_USERNAME);
}

export function setUserAvatar(avatar: string | null) {
	if (avatar) {
		localStorage.setItem(STORAGE_KEY_USER_AVATAR, avatar);
	} else {
		localStorage.removeItem(STORAGE_KEY_USER_AVATAR);
	}
	window.dispatchEvent(new Event("storage"));
}

export function getUserAvatar(): string | null {
	if (typeof window === "undefined") return null;
	return localStorage.getItem(STORAGE_KEY_USER_AVATAR);
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

/**
 * Public wrapper for silent token refresh (e.g. new tab with no sessionStorage).
 * Returns true if the access token was restored successfully.
 */
export async function refreshAccessToken(): Promise<boolean> {
	return _tryRefreshToken();
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
			cache: "no-store",
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
					cache: "no-store",
				});
				if (retryRes.ok) {
					if (retryRes.status === 204) return undefined as T;
					return retryRes.json() as Promise<T>;
				}
			}

			// Refresh failed or retry failed, clear session
			clearSession();
			if (typeof window !== "undefined") {
				window.location.href = "/login?reason=session_expired";
			}
			throw new Error("Session expired");
		}

		const text = await response.text().catch(() => response.statusText);
		let detail = text;
		try {
			const parsed = JSON.parse(text);
			if (parsed.detail) {
				if (typeof parsed.detail === "string") {
					detail = parsed.detail;
				} else if (Array.isArray(parsed.detail)) {
					detail = parsed.detail
						.map(
							(e: { msg?: string }) =>
								e.msg?.replace(/^Value error, /i, "") || "Validation error",
						)
						.join(". ");
				} else {
					detail = JSON.stringify(parsed.detail);
				}
			} else if (parsed.error) {
				detail =
					typeof parsed.error === "string"
						? parsed.error
						: JSON.stringify(parsed.error);
			}
		} catch {
			// not JSON, use raw text unless it's HTML or a 5xx error
			if (response.status >= 500 || text.trim().startsWith("<")) {
				detail = "Unable to reach the server. Please try again later.";
			}
		}
		const err = new Error(detail);
		(err as Error & { status: number }).status = response.status;
		throw err;
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
	user: {
		id: string;
		email: string;
		username?: string | null;
		name: string;
		role: string;
		avatar_url?: string | null;
		created_at: string;
	};
	access_token: string;
	refresh_token: string;
	expires_in: number;
};

export const auth = {
	init: (body: { email: string; name: string; password?: string }) =>
		post<AuthResponse>("/auth/init", body),
	login: (body: { email: string; password: string }) =>
		post<AuthResponse & { must_change_password?: boolean }>(
			"/auth/login",
			body,
		),
	whoami: () =>
		get<{
			id: string;
			email: string;
			username?: string | null;
			name: string;
			role: string;
			avatar_url?: string | null;
		}>("/auth/whoami"),
	exchangeCode: (body: { code: string }) =>
		post<AuthResponse>("/auth/exchange", body),
	deviceConfirm: (userCode: string) =>
		post<{ message: string }>("/auth/device/confirm", { user_code: userCode }),
	changePassword: (body: { current_password: string; new_password: string }) =>
		put<{ message: string }>("/auth/profile/password", body),
	uploadAvatar: (body: { avatar_url: string }) =>
		put<{ avatar_url: string | null }>("/auth/profile/avatar", body),
	deleteAvatar: () => del<{ avatar_url: null }>("/auth/profile/avatar"),
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
	create: (type: RegistryType, body: unknown) =>
		post<RegistryItem>(`/${type}`, body),
	install: (type: RegistryType, id: string, body?: unknown) =>
		post<unknown>(`/${type}/${id}/install`, body),
	delete: (type: RegistryType, id: string) => del(`/${type}/${id}`),
	metrics: (type: RegistryType, id: string) =>
		get<unknown>(`/${type}/${id}/metrics`),
	resolve: (id: string) => get<unknown>(`/agents/${id}/resolve`),
	manifest: (id: string) =>
		get<Record<string, unknown>>(`/agents/${id}/manifest`),
	downloads: (id: string) =>
		get<{ total: number; unique_users: number; recent_7d: number }>(
			`/agents/${id}/downloads`,
		),
	validate: (body: {
		components: { component_type: string; component_id: string }[];
	}) => post<ValidationResult>("/agents/validate", body),
	previewConfig: (body: {
		name: string;
		description: string;
		prompt: string;
		model_name: string;
		components: { component_type: string; component_id: string }[];
		target_ides?: string[];
	}) =>
		post<{ configs: Record<string, Record<string, string>> }>(
			"/agents/preview-config",
			body,
		),
	my: (type?: RegistryType) => get<RegistryItem[]>(`/${type ?? "agents"}/my`),
	archived: () => get<RegistryItem[]>("/agents/archived"),
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
		get<AgentVersionsResponse>(
			`/agents/${agentId}/versions?page=${page}&page_size=${pageSize}`,
		),
	getVersion: (agentId: string, version: string) =>
		get<unknown>(`/agents/${agentId}/versions/${version}`),
	createVersion: (agentId: string, body: unknown) =>
		post<unknown>(`/agents/${agentId}/versions`, body),
	getVersionDiff: (agentId: string, v1: string, v2: string) =>
		get<VersionDiff>(`/agents/${agentId}/versions/${v1}/diff/${v2}`),

	// Component versions
	listComponentVersions: (
		type: RegistryType,
		listingId: string,
		page = 1,
		pageSize = 50,
	) =>
		get<ComponentVersionsResponse>(
			`/${type}/${listingId}/versions?page=${page}&page_size=${pageSize}`,
		),
	getComponentVersion: (
		type: RegistryType,
		listingId: string,
		version: string,
	) => get<ComponentVersionDetail>(`/${type}/${listingId}/versions/${version}`),
	publishComponentVersion: (
		type: RegistryType,
		listingId: string,
		body: unknown,
	) => post<ComponentVersionDetail>(`/${type}/${listingId}/versions`, body),
	componentVersionSuggestions: (type: RegistryType, listingId: string) =>
		get<VersionSuggestions>(`/${type}/${listingId}/version-suggestions`),
	startEdit: (id: string, type?: RegistryType) =>
		post<{ status: string }>(`/${type ?? "agents"}/${id}/start-edit`),
	cancelEdit: (id: string, type?: RegistryType) =>
		post<{ status: string }>(`/${type ?? "agents"}/${id}/cancel-edit`),
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
	approveAgent: (id: string, body?: { category?: string }) =>
		post(`/review/agents/${id}/approve`, body),
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
	stats: (range?: string) =>
		get<OverviewStats>(`/overview/stats${range ? `?range=${range}` : ""}`),
	topMcps: () => get<TopItem[]>("/overview/top-mcps"),
	topAgents: (limit?: number) =>
		get<TopAgentItem[]>(
			`/overview/top-agents${limit ? `?limit=${limit}` : ""}`,
		),
	leaderboard: (window?: LeaderboardWindow, limit?: number, user?: string) => {
		const params = new URLSearchParams();
		if (window) params.set("window", window);
		if (limit) params.set("limit", String(limit));
		if (user) params.set("user", user);
		const qs = params.toString();
		return get<LeaderboardItem[]>(`/overview/leaderboard${qs ? `?${qs}` : ""}`);
	},
	componentLeaderboard: (window?: LeaderboardWindow, limit?: number) => {
		const params = new URLSearchParams();
		if (window) params.set("window", window);
		if (limit) params.set("limit", String(limit));
		const qs = params.toString();
		return get<ComponentLeaderboardItem[]>(
			`/overview/component-leaderboard${qs ? `?${qs}` : ""}`,
		);
	},
	trends: (range?: string) =>
		get<TrendPoint[]>(`/overview/trends${range ? `?range=${range}` : ""}`),
	tokenStats: (range?: string) =>
		get<TokenStats>(`/dashboard/tokens${range ? `?range=${range}` : ""}`),
	ideUsage: () => get<IdeUsageData>("/dashboard/ide-usage"),
	sessions: (params?: {
		status?: string;
		platform?: string;
		days?: number;
	}) => {
		const qs = new URLSearchParams();
		if (params?.status) qs.set("status", params.status);
		if (params?.platform) qs.set("platform", params.platform);
		if (params?.days) qs.set("days", String(params.days));
		const suffix = qs.toString() ? `?${qs}` : "";
		return get<Session[]>(`/sessions${suffix}`);
	},
	sessionsSummary: () => get<SessionsSummary>("/sessions/summary"),
	session: (id: string) =>
		get<SessionData>(`/sessions/${encodeURIComponent(id)}`),
	traces: () => get<SessionTrace[]>("/sessions/traces"),
	trace: (id: string) =>
		get<unknown>(`/sessions/traces/${encodeURIComponent(id)}`),
	sessionsStats: () => get<SessionsStats>("/sessions/stats"),
	sessionsErrors: () => get<SessionErrorEvent[]>("/sessions/errors"),
};

// ── Feedback ────────────────────────────────────────────────────────
export const feedback = {
	submit: (body: {
		listing_type: string;
		listing_id: string;
		rating: number;
		comment?: string;
	}) => post<FeedbackItem>("/feedback", body),
	get: (type: string, id: string) =>
		get<FeedbackItem[]>(`/feedback/${type}/${id}`),
	summary: (id: string) => get<FeedbackSummary>(`/feedback/summary/${id}`),
};

// ── Admin ───────────────────────────────────────────────────────────
export const admin = {
	settings: () =>
		get<AdminSetting[] | Record<string, string>>("/admin/settings"),
	updateSetting: (key: string, body: unknown) =>
		put<unknown>(`/admin/settings/${key}`, body),
	deleteSetting: (key: string) => del(`/admin/settings/${key}`),
	users: () => get<AdminUser[]>("/admin/users"),
	createUser: (body: {
		email: string;
		name: string;
		username?: string;
		role?: string;
	}) =>
		post<{
			id: string;
			email: string;
			name: string;
			username?: string;
			role: string;
			password: string;
		}>("/admin/users", body),
	updateRole: (id: string, body: { role: string }) =>
		put<AdminUser>(`/admin/users/${id}/role`, body),
	updateDepartment: (id: string, body: { department: string | null }) =>
		put<AdminUser>(`/admin/users/${id}/department`, body),
	bulkDepartment: (entries: { email: string; department: string }[]) =>
		post<{ updated: number; not_found: string[] }>(
			"/admin/users/bulk-department",
			{ entries },
		),
	resetPassword: (
		id: string,
		body: { new_password?: string; generate?: boolean },
	) =>
		put<{
			message: string;
			generated_password?: string;
			must_change_password?: string;
		}>(`/admin/users/${id}/password`, body),
	deleteUser: (id: string) => del(`/admin/users/${id}`),
	applyResources: () =>
		post<{ applied: Record<string, string>; message: string }>(
			"/admin/resources/apply",
			{},
		),
	getTracePrivacy: () =>
		get<{ trace_privacy: boolean }>("/admin/org/trace-privacy"),
	setTracePrivacy: (enabled: boolean) =>
		put<{ trace_privacy: boolean }>("/admin/org/trace-privacy", {
			trace_privacy: enabled,
		}),
	getRegisteredAgentsOnly: () =>
		get<{ registered_agents_only: boolean }>(
			"/admin/org/registered-agents-only",
		),
	setRegisteredAgentsOnly: (enabled: boolean) =>
		put<{ registered_agents_only: boolean }>(
			"/admin/org/registered-agents-only",
			{ registered_agents_only: enabled },
		),
	auditLog: (params?: Record<string, string>) => {
		const qs = params ? `?${new URLSearchParams(params)}` : "";
		return get<AuditLogEntry[]>(`/admin/audit-log${qs}`);
	},
	auditLogExport: async (params?: Record<string, string>) => {
		const qs = params ? `?${new URLSearchParams(params)}` : "";
		const token = getAccessToken();
		const headers: Record<string, string> = {};
		if (token) headers["Authorization"] = `Bearer ${token}`;
		const res = await fetch(`${API}/admin/audit-log/export${qs}`, { headers });
		if (!res.ok) throw new Error("Export failed");
		return res.text();
	},
	securityEvents: (params?: Record<string, string>) => {
		const qs = params ? `?${new URLSearchParams(params)}` : "";
		return get<{ events: SecurityEvent[]; total: number }>(
			`/admin/security-events${qs}`,
		);
	},
	diagnostics: () => get<DiagnosticsResponse>("/admin/diagnostics"),
	systemWarnings: () => get<SystemWarning[]>("/admin/system-warnings"),
	samlConfig: () => get<Record<string, unknown>>("/admin/saml-config"),
	updateSamlConfig: (body: Record<string, unknown>) =>
		put<Record<string, unknown>>("/admin/saml-config", body),
	deleteSamlConfig: () => del("/admin/saml-config"),
	scimTokens: () =>
		get<
			{
				id: string;
				description: string;
				active: boolean;
				created_at: string;
				token_prefix: string;
			}[]
		>("/admin/scim-tokens"),
	createScimToken: (body: { description?: string }) =>
		post<{ id: string; token: string; description: string; message: string }>(
			"/admin/scim-tokens",
			body,
		),
	revokeScimToken: (id: string) => del(`/admin/scim-tokens/${id}`),
	getRetention: () => get<RetentionConfig>("/admin/org/retention"),
	setRetention: (body: RetentionConfigUpdate) =>
		put<RetentionConfig>("/admin/org/retention", body),
	previewRetention: (days: number) =>
		get<RetentionPreview>(`/admin/org/retention/preview?days=${days}`),
	getRetentionStats: () => get<RetentionStats>("/admin/org/retention/stats"),
	getRetentionWarnings: () =>
		get<RetentionWarnings>("/admin/org/retention/warnings"),
};

// ── Retention Types ───────────────────────────────────────────────
export type RetentionConfig = {
	retention_enabled: boolean;
	data_retention_days: number | null;
	score_retention_days: number | null;
	max_trace_count: number | null;
	global_retention_days: number;
};

export type RetentionConfigUpdate = {
	retention_enabled: boolean;
	data_retention_days?: number | null;
	score_retention_days?: number | null;
	max_trace_count?: number | null;
};

export type RetentionPreview = {
	traces: number;
	spans: number;
	scores: number;
	session_events: number;
	insight_reports: number;
};

export type RetentionStats = {
	retention_enabled: boolean;
	data_retention_days: number | null;
	score_retention_days: number | null;
	total_traces: number;
	oldest_trace_age_days: number;
	traces_expiring_7d: number;
	next_purge_approx: string | null;
};

export type RetentionWarnings = {
	warnings: {
		agent_id: string;
		agent_name: string;
		traces_expiring_soon: number;
		last_insight_report: string | null;
	}[];
	retention_days: number | null;
	retention_enabled: boolean;
};

// ── Config ─────────────────────────────────────────────────────────
export type PublicConfig = {
	licensed: boolean;
	sso_enabled: boolean;
	sso_only: boolean;
	saml_enabled: boolean;
	insights_available: boolean;
	exec_dashboard_available: boolean;
	licensed_features: string[];
	branding_logo: string | null;
	branding_app_name: string | null;
	branding_wordmark: string | null;
};

export interface IdeEntry {
	name: string;
	display_name: string;
	features: string[];
	accepts_model_choice: boolean;
}

interface IdesResponse {
	ides: IdeEntry[];
}

export const config = {
	public: () => get<PublicConfig>("/config/public"),
	ides: () => get<IdesResponse>("/config/ides").then((r) => r.ides),
};

// ── Models ─────────────────────────────────────────────────────────
export const models = {
	list: () => get<import("./types").ModelCatalog>("/models"),
	refresh: () =>
		post<import("./types").ModelRefreshResult>("/admin/models/refresh"),
};

// ── Bulk ───────────────────────────────────────────────────────────
export const bulk = {
	createAgents: (body: { agents: unknown[]; dry_run?: boolean }) =>
		post<BulkResult>("/bulk/agents", body),
};

// ── Insights ───────────────────────────────────────────────────────
export const insights = {
	generate: (agentId: string, periodDays?: number) =>
		post<InsightReportListItem>(
			`/insights/agents/${agentId}/generate`,
			periodDays ? { period_days: periodDays } : {},
		),
	listReports: (agentId: string) =>
		get<InsightReportListItem[]>(`/insights/agents/${agentId}/reports`),
	getReport: (reportId: string) =>
		get<InsightReport>(`/insights/reports/${reportId}`),
	exportHtml: async (reportId: string): Promise<void> => {
		const token = getAccessToken();
		const res = await fetch(`${API}/insights/reports/${reportId}/export/html`, {
			headers: token ? { Authorization: `Bearer ${token}` } : {},
		});
		if (!res.ok) throw new Error("Export failed");
		const blob = await res.blob();
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `insight-report-${reportId.slice(0, 8)}.html`;
		a.click();
		URL.revokeObjectURL(url);
	},
};

// ── Exec Dashboard ─────────────────────────────────────────────────
export const exec = {
	adoption: () => get<ExecAdoptionResponse>("/exec/adoption"),
	agentCounts: () => get<ExecAgentCounts>("/exec/agent-counts"),
	usageByCategory: (range?: string) =>
		get<ExecUsageByCategory[]>(
			`/exec/usage-by-category${range ? `?range=${range}` : ""}`,
		),
	platformCoverage: () =>
		get<ExecPlatformCoverage[]>("/exec/platform-coverage"),
	platforms: () => get<ExecPlatformScore[]>("/exec/platforms"),
	velocity: () => get<ExecVelocityResponse>("/exec/velocity"),
	topAgents: (limit?: number) =>
		get<ExecTopAgent[]>(`/exec/top-agents${limit ? `?limit=${limit}` : ""}`),
	departments: (range?: string) =>
		get<ExecDepartmentsResponse>(
			`/exec/departments${range ? `?range=${range}` : ""}`,
		),
	deptTokens: (range?: string) =>
		get<ExecDeptTokenItem[]>(
			`/exec/dept-tokens${range ? `?range=${range}` : ""}`,
		),
	costSummary: (range?: string) =>
		get<ExecCostSummary>(`/exec/cost-summary${range ? `?range=${range}` : ""}`),
	roiProjections: () =>
		get<ExecROIProjectionsResponse>("/exec/roi-projections"),
	strategicInsights: () =>
		get<ExecStrategicInsightsResponse>("/exec/strategic-insights"),
	developerBreakdown: (limit?: number) =>
		get<ExecDeveloperBreakdown>(
			`/exec/developer-breakdown${limit ? `?limit=${limit}` : ""}`,
		),
	inactivityAlerts: () => get<ExecInactivityAlerts>("/exec/inactivity-alerts"),
	timeToValue: () => get<ExecTimeToValueResponse>("/exec/time-to-value"),
	aiInsights: () => get<ExecAIInsightsResponse>("/exec/ai-insights"),
	config: () => get<ExecConfig | null>("/exec/config"),
	updateConfig: (data: Partial<ExecConfig>) =>
		put<ExecConfig>("/exec/config", data),
};

// ── Health ──────────────────────────────────────────────────────────
export const health = () => fetch("/health").then((r) => r.json());
