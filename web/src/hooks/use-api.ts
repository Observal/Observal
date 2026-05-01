"use client";

import { useEffect, useRef } from "react";
import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
import {
  auth,
  registry,
  review,
  dashboard,
  feedback,
  eval_,
  admin,
  telemetry,
  bulk,
  graphql,
  type RegistryType,
} from "@/lib/api";
import type { LeaderboardWindow } from "@/lib/types";

// ── Dashboard ───────────────────────────────────────────────────────

export function useOverviewStats(range?: string) {
  return useQuery({ queryKey: ["overview", "stats", range], queryFn: () => dashboard.stats(range) });
}

export function useTopMcps() {
  return useQuery({ queryKey: ["overview", "top-mcps"], queryFn: dashboard.topMcps });
}

export function useTopAgents(limit?: number) {
  return useQuery({ queryKey: ["overview", "top-agents", limit], queryFn: () => dashboard.topAgents(limit) });
}

export function useTrends(range?: string) {
  return useQuery({ queryKey: ["overview", "trends", range], queryFn: () => dashboard.trends(range) });
}

// ── Traces (GraphQL) ────────────────────────────────────────────────

export function useTraces(filters?: Record<string, unknown>) {
  const traceType = filters?.trace_type as string | undefined;
  const mcpId = filters?.mcp_id as string | undefined;
  const agentId = filters?.agent_id as string | undefined;
  const ide = filters?.ide as string | undefined;
  return useQuery({
    queryKey: ["traces", filters],
    queryFn: () =>
      graphql<{ traces: { items: Record<string, unknown>[]; totalCount: number; hasMore: boolean } }>(
        `query Traces($traceType: String, $mcpId: String, $agentId: String) {
          traces(traceType: $traceType, mcpId: $mcpId, agentId: $agentId) {
            items { traceId traceType name ide startTime endTime metrics { totalSpans errorCount } }
            totalCount hasMore
          }
        }`,
        { traceType, mcpId, agentId },
      ).then((d) => {
        const items = d.traces.items;
        return ide ? items.filter((t) => t.ide === ide) : items;
      }),
  });
}

export function useTrace(id: string | undefined) {
  return useQuery({
    queryKey: ["trace", id],
    enabled: !!id,
    queryFn: () =>
      graphql<{ trace: unknown }>(
        `query Trace($traceId: String!) {
          trace(traceId: $traceId) {
            traceId traceType name ide startTime endTime input output tags metadata
            spans { spanId name type startTime endTime status latencyMs }
            metrics { totalSpans errorCount totalLatencyMs toolCallCount tokenCountTotal }
          }
        }`,
        { traceId: id },
      ).then((d) => d.trace),
  });
}

export function useSessions() {
  return useQuery({
    queryKey: ["sessions"],
    queryFn: () =>
      graphql<{ traces: { items: unknown[]; totalCount: number; hasMore: boolean } }>(
        `query Sessions {
          traces { items { traceId traceType name ide sessionId startTime endTime } totalCount hasMore }
        }`,
      ).then((d) => d.traces.items),
  });
}

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

export function useAgentVersions(agentId: string | undefined) {
  return useQuery({
    queryKey: ["agent-versions", agentId],
    enabled: !!agentId,
    queryFn: () => registry.listVersions(agentId!),
  });
}

export function useAgentVersionDetail(agentId: string | undefined, version: string | null) {
  return useQuery({
    queryKey: ["agent-version-detail", agentId, version],
    enabled: !!agentId && !!version,
    queryFn: () => registry.getVersion(agentId!, version!),
  });
}

export function useVersionDiff(
  agentId: string | undefined,
  v1: string | undefined,
  v2: string | undefined,
) {
  return useQuery({
    queryKey: ["version-diff", agentId, v1, v2],
    enabled: !!agentId && !!v1 && !!v2,
    queryFn: () => registry.getVersionDiff(agentId!, v1!, v2!),
  });
}

// ── Review ──────────────────────────────────────────────────────────

export function useReviewList(typeFilter?: string) {
  const params = typeFilter ? { type: typeFilter } : undefined;
  return useQuery({
    queryKey: ["review", params],
    queryFn: async () => {
      const [components, agents] = await Promise.all([
        review.list(params),
        review.listAgents(),
      ]);
      return [...agents, ...components];
    },
  });
}

export function useReviewAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; type?: string; action: "approve" | "reject"; reason?: string }) => {
      if (vars.type === "agent") {
        return vars.action === "approve"
          ? review.approveAgent(vars.id)
          : review.rejectAgent(vars.id, { reason: vars.reason ?? "" });
      }
      return vars.action === "approve"
        ? review.approve(vars.id)
        : review.reject(vars.id, { reason: vars.reason ?? "" });
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success(vars.action === "approve" ? "Submission approved" : "Submission rejected");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Review action failed");
    },
  });
}

// ── Eval ────────────────────────────────────────────────────────────

export function useEvalRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { agentId: string; body?: unknown }) =>
      eval_.run(vars.agentId, vars.body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval"] });
      toast.success("Eval run started");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Eval run failed");
    },
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["feedback"] });
      toast.success("Feedback submitted");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to submit feedback");
    },
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

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: admin.createUser,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success("User created");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to create user");
    },
  });
}

export function useUpdateUserRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; role: string }) =>
      admin.updateRole(vars.id, { role: vars.role }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success("Role updated");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to update role");
    },
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => admin.deleteUser(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success("User deleted");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to delete user");
    },
  });
}

export function useResetPassword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => admin.resetPassword(id, { generate: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to reset password");
    },
  });
}

export function useAdminSettings() {
  return useQuery({ queryKey: ["admin", "settings"], queryFn: admin.settings });
}

// ── Audit & Security ────────────────────────────────────────────────

export function useAuditLog(filters?: Record<string, string>) {
  return useQuery({
    queryKey: ["admin", "audit-log", filters],
    queryFn: () => admin.auditLog(filters),
  });
}

export function useSecurityEvents(filters?: Record<string, string>) {
  return useQuery({
    queryKey: ["admin", "security-events", filters],
    queryFn: () => admin.securityEvents(filters),
  });
}

export function useDiagnostics() {
  return useQuery({
    queryKey: ["admin", "diagnostics"],
    queryFn: admin.diagnostics,
    refetchInterval: 30_000,
  });
}

// ── Telemetry ───────────────────────────────────────────────────────

export function useTelemetryStatus() {
  return useQuery({
    queryKey: ["telemetry", "status"],
    queryFn: telemetry.status,
  });
}

// ── New Dashboard Hooks ─────────────────────────────────────────────

export function useTokenStats(range?: string) {
  return useQuery({ queryKey: ['dashboard', 'tokens', range], queryFn: () => dashboard.tokenStats(range) });
}
export function useIdeUsage() {
  return useQuery({ queryKey: ['dashboard', 'ide-usage'], queryFn: dashboard.ideUsage });
}
// ── Sessions ───────────────────────────────────────────────────────

export function useSessions2(options?: {
  refetchInterval?: number | false;
  platform?: string;
  days?: number;
}) {
  return useQuery({
    queryKey: ['sessions', 'list', options?.platform, options?.days],
    queryFn: () =>
      dashboard.sessions({
        platform: options?.platform,
        days: options?.days,
      }),
    refetchInterval: options?.refetchInterval,
    refetchOnMount: "always",
    staleTime: 0,
  });
}
export function useSessionsSummary() {
  return useQuery({
    queryKey: ['sessions', 'summary'],
    queryFn: dashboard.sessionsSummary,
    refetchOnMount: "always",
    staleTime: 0,
  });
}
export function useSessionDetail(id: string | undefined) {
  return useQuery({ queryKey: ['sessions', 'detail', id], queryFn: () => dashboard.session(id!), enabled: !!id });
}
export function useSessionTraces() {
  return useQuery({ queryKey: ['sessions', 'traces'], queryFn: dashboard.traces });
}
export function useSessionTrace(id: string | undefined) {
  return useQuery({ queryKey: ['sessions', 'trace', id], queryFn: () => dashboard.trace(id!), enabled: !!id });
}
export function useSessionsStats() {
  return useQuery({ queryKey: ['sessions', 'stats'], queryFn: dashboard.sessionsStats });
}
export function useSessionErrors() {
  return useQuery({ queryKey: ['sessions', 'errors'], queryFn: dashboard.sessionsErrors });
}
export interface SessionEfficiencyData {
  efficiency_rating: number;
  efficiency_metrics: Record<string, number | null>;
  interpretation: Record<string, string>;
  warnings: string[];
  scorer_version: string;
  dag?: {
    nodes: { id: number; action_type: string; action_detail: string; status: "effective" | "reverted" | "waste"; parent_ids: number[]; trace_id: string | null; files_touched: string[]; latency_ms: number; reverted_by: number | null }[];
    edges: { source: number; target: number; type: "causal" | "cross_trace" }[];
    stats: { total_nodes: number; effective_nodes: number; reverted_nodes: number; waste_nodes: number };
  };
  waste_classifications?: { category: string; steps: number[] }[];
  error?: string;
}

export function useSessionEfficiency(sessionId: string | undefined) {
  return useQuery<SessionEfficiencyData>({
    queryKey: ["session-efficiency", sessionId],
    queryFn: () => dashboard.sessionEfficiency(sessionId!) as unknown as Promise<SessionEfficiencyData>,
    enabled: !!sessionId,
  });
}

export function useSessionSubscription() {
  const qc = useQueryClient();
  const listDebounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    let unsubscribe: (() => void) | undefined;

    import("@/lib/graphql-ws").then(({ subscribeToSessionUpdates }) => {
      unsubscribe = subscribeToSessionUpdates((sessionId) => {
        // Debounce the list refetch (many events → one list refresh)
        clearTimeout(listDebounceRef.current);
        listDebounceRef.current = setTimeout(() => {
          qc.invalidateQueries({ queryKey: ["sessions", "list"] });
        }, 300);
        // Session detail: invalidate immediately so new turns appear
        qc.invalidateQueries({ queryKey: ["sessions", "detail", sessionId] });
      });
    });

    return () => {
      clearTimeout(listDebounceRef.current);
      unsubscribe?.();
    };
  }, [qc]);
}

// ── Agent-specific ──────────────────────────────────────────────────

export function useMyAgents() {
  return useQuery({
    queryKey: ["registry", "agents", "my"],
    queryFn: () => registry.my(),
  });
}

export function useAgentResolve(id: string) {
  return useQuery({
    queryKey: ["agent-resolve", id],
    queryFn: () => registry.resolve(id),
    enabled: !!id,
  });
}

export function useAgentDownloads(id: string) {
  return useQuery({
    queryKey: ["agent-downloads", id],
    queryFn: () => registry.downloads(id),
    enabled: !!id,
  });
}

export function useEvalAggregate(agentId: string) {
  return useQuery({
    queryKey: ["eval-aggregate", agentId],
    queryFn: () => eval_.aggregate(agentId),
    enabled: !!agentId,
  });
}

export function useLeaderboard(window?: LeaderboardWindow, limit?: number, user?: string) {
  return useQuery({
    queryKey: ["leaderboard", window, limit, user],
    queryFn: () => dashboard.leaderboard(window, limit, user),
  });
}

export function useComponentLeaderboard(window?: LeaderboardWindow, limit?: number) {
  return useQuery({
    queryKey: ["component-leaderboard", window, limit],
    queryFn: () => dashboard.componentLeaderboard(window, limit),
  });
}

export function useAgentValidation() {
  return useMutation({
    mutationFn: registry.validate,
  });
}

export function useFeedbackSummary(listingId: string | undefined) {
  return useQuery({
    queryKey: ["feedback", "summary", listingId],
    enabled: !!listingId,
    queryFn: () => feedback.summary(listingId!),
  });
}

export function useEvalPenalties(scorecardId: string | undefined) {
  return useQuery({
    queryKey: ["eval", "penalties", scorecardId],
    enabled: !!scorecardId,
    queryFn: () => eval_.penalties(scorecardId!),
  });
}

export function useEvalScorecard(scorecardId: string | undefined) {
  return useQuery({
    queryKey: ["eval", "scorecard", scorecardId],
    enabled: !!scorecardId,
    queryFn: () => eval_.show(scorecardId!),
  });
}

// ── Archive ────────────────────────────────────────────────────────

export function useArchiveAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.archive(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success("Agent archived");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to archive agent");
    },
  });
}

export function useUnarchiveAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.unarchive(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success("Agent restored");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to restore agent");
    },
  });
}

// ── Draft ──────────────────────────────────────────────────────────

export function useSaveDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) => registry.draft(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success("Draft saved");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to save draft");
    },
  });
}

export function useUpdateDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; body: unknown }) => registry.updateDraft(vars.id, vars.body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success("Draft updated");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to update draft");
    },
  });
}

export function useUpdateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; body: unknown }) => registry.updateAgent(vars.id, vars.body),
    onSuccess: (_data: unknown, vars: { id: string; body: unknown }) => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      qc.invalidateQueries({ queryKey: ["registry", "agents", vars.id] });
      toast.success("Agent updated successfully");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to update agent");
    },
  });
}

export function useSubmitDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.submitDraft(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success("Agent submitted for review");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to submit draft");
    },
  });
}

// ── Component Draft/Submit (generic) ──────────────────────────────

export function useMyComponents(type: RegistryType) {
  return useQuery({
    queryKey: ["registry", type, "my"],
    queryFn: () => registry.my(type),
  });
}

export function useComponentSubmit(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) => registry.submit(type, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", type] });
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success("Submitted for review");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to submit");
    },
  });
}

export function useComponentSaveDraft(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) => registry.draft(body, type),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", type] });
      toast.success("Draft saved");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to save draft");
    },
  });
}

export function useComponentUpdateDraft(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; body: unknown }) =>
      registry.updateDraft(vars.id, vars.body, type),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", type] });
      toast.success("Draft updated");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to update draft");
    },
  });
}

export function useComponentSubmitDraft(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.submitDraft(id, type),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", type] });
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success("Submitted for review");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to submit");
    },
  });
}

export function useComponentDelete(type: RegistryType) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => registry.delete(type, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry", type] });
      toast.success("Deleted");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to delete");
    },
  });
}

// ── Version ────────────────────────────────────────────────────────

export function useCreateAgentVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { agentId: string; body: unknown }) =>
      registry.createVersion(vars.agentId, vars.body),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["agent-versions", vars.agentId] });
      qc.invalidateQueries({ queryKey: ["registry", "agents", vars.agentId] });
      toast.success("New version released successfully");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to release version");
    },
  });
}

export function useVersionSuggestions(id: string | undefined) {
  return useQuery({
    queryKey: ["version-suggestions", id],
    enabled: !!id,
    queryFn: () => registry.versionSuggestions(id!),
  });
}

// ── Bundle Review ──────────────────────────────────────────────────

export function useBundleReviewAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; action: "approve" | "reject"; reason?: string }) =>
      vars.action === "approve"
        ? review.approveBundle(vars.id)
        : review.rejectBundle(vars.id, { reason: vars.reason ?? "" }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success(vars.action === "approve" ? "Bundle approved" : "Bundle rejected");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Bundle review action failed");
    },
  });
}

// ── Bulk ───────────────────────────────────────────────────────────

export function useBulkCreateAgents() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: bulk.createAgents,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success(`Created ${data.created} agents`);
    },
    onError: (err: Error) => {
      toast.error(err.message || "Bulk create failed");
    },
  });
}

// ── Review (agents-only list) ──────────────────────────────────────

export function useReviewAgents() {
  return useQuery({
    queryKey: ["review", "agents"],
    queryFn: () => review.listAgents(),
  });
}

export function useReviewDetail(id: string | undefined) {
  return useQuery({
    queryKey: ["review", "detail", id],
    enabled: !!id,
    queryFn: () => review.get(id!),
  });
}

export function useRelatedSkills(id: string | undefined) {
  return useQuery({
    queryKey: ["review", "related-skills", id],
    enabled: !!id,
    queryFn: () => review.relatedSkills(id!).then((r) => r.skills),
  });
}

export function useApproveWithSkills() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; skillIds: string[] }) =>
      review.approveWithSkills(vars.id, { skill_ids: vars.skillIds }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success("MCP and related skills approved");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Bulk approve failed");
    },
  });
}

export function useReviewComponents(typeFilter?: string) {
  const params: Record<string, string> = { tab: "components" };
  if (typeFilter) params.type = typeFilter;
  return useQuery({
    queryKey: ["review", "components", params],
    queryFn: () => review.list(params),
  });
}

export function useReviewDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; type?: string }) => {
      const typeMap: Record<string, RegistryType> = {
        mcp: "mcps",
        skill: "skills",
        hook: "hooks",
        prompt: "prompts",
        sandbox: "sandboxes",
        agent: "agents",
      };
      const registryType = typeMap[vars.type ?? "agent"] ?? "agents";
      return registry.delete(registryType, vars.id);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review"] });
      toast.success("Submission withdrawn");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to delete submission");
    },
  });
}

