"use client";

import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import {
  auth,
  registry,
  review,
  dashboard,
  feedback,
  eval_,
  admin,
  telemetry,
  graphql,
  type RegistryType,
} from "@/lib/api";

// ── Dashboard ───────────────────────────────────────────────────────

export function useOverviewStats() {
  return useQuery({ queryKey: ["overview", "stats"], queryFn: dashboard.stats });
}

export function useTopMcps() {
  return useQuery({ queryKey: ["overview", "top-mcps"], queryFn: dashboard.topMcps });
}

export function useTopAgents() {
  return useQuery({ queryKey: ["overview", "top-agents"], queryFn: dashboard.topAgents });
}

export function useTrends() {
  return useQuery({ queryKey: ["overview", "trends"], queryFn: dashboard.trends });
}

// ── Traces (GraphQL) ────────────────────────────────────────────────

export function useTraces(filters?: Record<string, unknown>) {
  return useQuery({
    queryKey: ["traces", filters],
    queryFn: () =>
      graphql<{ traces: unknown[] }>(
        `query Traces($filters: TraceFilters) { traces(filters: $filters) { id traceId startTime endTime status spanCount } }`,
        { filters },
      ).then((d) => d.traces),
  });
}

export function useTrace(id: string | undefined) {
  return useQuery({
    queryKey: ["trace", id],
    enabled: !!id,
    queryFn: () =>
      graphql<{ trace: unknown }>(
        `query Trace($id: String!) { trace(id: $id) { id traceId startTime endTime status spans { spanId name startTime endTime attributes } } }`,
        { id },
      ).then((d) => d.trace),
  });
}

export function useSessions() {
  return useQuery({
    queryKey: ["sessions"],
    queryFn: () =>
      graphql<{ traces: unknown[] }>(
        `query Sessions { traces { id traceId startTime endTime status spanCount } }`,
      ).then((d) => d.traces),
  });
}

// ── Registry ────────────────────────────────────────────────────────

export function useRegistryList(
  type: RegistryType,
  filters?: Record<string, string>,
) {
  return useQuery({
    queryKey: ["registry", type, filters],
    queryFn: () => registry.list(type, filters),
  });
}

export function useRegistryItem(type: RegistryType, id: string | undefined) {
  return useQuery({
    queryKey: ["registry", type, id],
    enabled: !!id,
    queryFn: () => registry.get(type, id!),
  });
}

export function useRegistryMetrics(type: RegistryType, id: string | undefined) {
  return useQuery({
    queryKey: ["registry", type, id, "metrics"],
    enabled: !!id,
    queryFn: () => registry.metrics(type, id!),
  });
}

// ── Review ──────────────────────────────────────────────────────────

export function useReviewList(typeFilter?: string) {
  const params = typeFilter ? { type: typeFilter } : undefined;
  return useQuery({
    queryKey: ["review", params],
    queryFn: () => review.list(params),
  });
}

export function useReviewAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; action: "approve" | "reject"; reason?: string }) =>
      vars.action === "approve"
        ? review.approve(vars.id)
        : review.reject(vars.id, { reason: vars.reason ?? "" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["review"] }),
  });
}

// ── Eval ────────────────────────────────────────────────────────────

export function useEvalRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { agentId: string; body?: unknown }) =>
      eval_.run(vars.agentId, vars.body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["eval"] }),
  });
}

export function useEvalScorecards(
  agentId: string | undefined,
  params?: Record<string, string>,
) {
  return useQuery({
    queryKey: ["eval", "scorecards", agentId, params],
    enabled: !!agentId,
    queryFn: () => eval_.scorecards(agentId!, params),
  });
}

export function useEvalCompare(
  agentId: string | undefined,
  params: Record<string, string>,
) {
  return useQuery({
    queryKey: ["eval", "compare", agentId, params],
    enabled: !!agentId && !!params.a && !!params.b,
    queryFn: () => eval_.compare(agentId!, params),
  });
}

// ── Feedback ────────────────────────────────────────────────────────

export function useFeedback(type: string | undefined, id: string | undefined) {
  return useQuery({
    queryKey: ["feedback", type, id],
    enabled: !!type && !!id,
    queryFn: () => feedback.get(type!, id!),
  });
}

export function useSubmitFeedback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: feedback.submit,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["feedback"] }),
  });
}

// ── Auth ────────────────────────────────────────────────────────────

export function useWhoami() {
  return useQuery({
    queryKey: ["auth", "whoami"],
    queryFn: auth.whoami,
    retry: false,
  });
}

// ── Admin ───────────────────────────────────────────────────────────

export function useAdminUsers() {
  return useQuery({ queryKey: ["admin", "users"], queryFn: admin.users });
}

export function useAdminSettings() {
  return useQuery({ queryKey: ["admin", "settings"], queryFn: admin.settings });
}

// ── Telemetry ───────────────────────────────────────────────────────

export function useTelemetryStatus() {
  return useQuery({
    queryKey: ["telemetry", "status"],
    queryFn: telemetry.status,
  });
}

// ── New Dashboard Hooks ─────────────────────────────────────────────

export function useTokenStats() {
  return useQuery({ queryKey: ['dashboard', 'tokens'], queryFn: dashboard.tokenStats });
}
export function useIdeUsage() {
  return useQuery({ queryKey: ['dashboard', 'ide-usage'], queryFn: dashboard.ideUsage });
}
export function useSandboxMetrics() {
  return useQuery({ queryKey: ['dashboard', 'sandbox-metrics'], queryFn: dashboard.sandboxMetrics });
}
export function useGraphragMetrics() {
  return useQuery({ queryKey: ['dashboard', 'graphrag-metrics'], queryFn: dashboard.graphragMetrics });
}
export function useLatencyHeatmap() {
  return useQuery({ queryKey: ['dashboard', 'latency-heatmap'], queryFn: dashboard.latencyHeatmap });
}
export function useUnannotatedTraces() {
  return useQuery({ queryKey: ['dashboard', 'unannotated-traces'], queryFn: dashboard.unannotatedTraces });
}

// ── OTel ────────────────────────────────────────────────────────────

export function useOtelSessions() {
  return useQuery({ queryKey: ['otel', 'sessions'], queryFn: dashboard.otelSessions });
}
export function useOtelSession(id: string | undefined) {
  return useQuery({ queryKey: ['otel', 'session', id], queryFn: () => dashboard.otelSession(id!), enabled: !!id });
}
export function useOtelTraces() {
  return useQuery({ queryKey: ['otel', 'traces'], queryFn: dashboard.otelTraces });
}
export function useOtelTrace(id: string | undefined) {
  return useQuery({ queryKey: ['otel', 'trace', id], queryFn: () => dashboard.otelTrace(id!), enabled: !!id });
}
export function useOtelStats() {
  return useQuery({ queryKey: ['otel', 'stats'], queryFn: dashboard.otelStats });
}
