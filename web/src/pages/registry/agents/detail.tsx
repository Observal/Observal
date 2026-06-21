// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { Link, useParams } from "@tanstack/react-router";
import {
  ArrowDownToLine,
  Puzzle,
  Star,
  Users,
  Loader2,
  Archive,
  ArchiveRestore,
  Trash2,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Sparkles,
  AlertTriangle,
} from "lucide-react";
import { useState, useEffect, useCallback, useMemo, useSyncExternalStore } from "react";

import {
  useRegistryItem,
  useAgentDownloads,
  useFeedback,
  useFeedbackSummary,
  useMyFeedback,
  useWhoami,
  useAgentVersions,
  useAgentVersionDetail,
  useInsightReports,
  useInsightSessionCount,
  useGenerateInsight,
  useInsightsStatus,
  useArchiveAgent,
  useUnarchiveAgent,
} from "@/hooks/use-api";
import { getUserRole } from "@/lib/api";
import { hasMinRole } from "@/hooks/use-role-guard";
import type {
  AgentComponentReference,
  AgentVersionSummary,
  FeedbackItem,
  InsightReportListItem,
} from "@/lib/types";
import { PullCommand } from "@/components/registry/pull-command";
import { VersionDropdown } from "@/components/registry/version-dropdown";
import { StatusBadge } from "@/components/registry/status-badge";
import { IdeBadges } from "@/components/registry/ide-badges";
import { ReviewForm } from "@/components/registry/review-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/layouts/page-header";
import { DetailSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { AgentEditForm, type AgentEditFormProps } from "@/components/registry/agent-edit-form";
import { CoAuthorInput, type CoAuthor } from "@/components/registry/co-author-input";
import { compactNumber } from "@/lib/utils";
import { DIMENSION_META } from "@/components/dashboard/score-overview";

const FEATURE_LABELS: Record<string, string> = {
  skills: "Slash-command skills",
  superpowers: "Kiro superpowers",
  hook_bridge: "Hook bridge",
  mcp_servers: "MCP servers",
  rules: "Rules / system prompt",
  steering_files: "Steering files",
  otlp_telemetry: "OTLP telemetry",
};

const COMPONENT_TYPES = [
  { value: "mcps", singular: "mcp", label: "MCPs" },
  { value: "skills", singular: "skill", label: "Skills" },
  { value: "hooks", singular: "hook", label: "Hooks" },
  { value: "prompts", singular: "prompt", label: "Prompts" },
  { value: "sandboxes", singular: "sandbox", label: "Sandboxes" },
] as const;

type ComponentGroupKey = (typeof COMPONENT_TYPES)[number]["value"];

const COMPONENT_GROUP_BY_TYPE: Record<string, ComponentGroupKey> = {
  mcp: "mcps",
  mcps: "mcps",
  skill: "skills",
  skills: "skills",
  hook: "hooks",
  hooks: "hooks",
  prompt: "prompts",
  prompts: "prompts",
  sandbox: "sandboxes",
  sandboxes: "sandboxes",
};

function semverCompareDesc(a: string, b: string): number {
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  for (let i = 0; i < 3; i += 1) {
    const diff = (pb[i] ?? 0) - (pa[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return b.localeCompare(a);
}

function getLatestApprovedVersion(versions: AgentVersionSummary[]): string | undefined {
  return [...versions]
    .filter((v) => v.status === "approved")
    .sort((a, b) => semverCompareDesc(a.version, b.version))[0]?.version;
}

function normalizeVersionComponents(components?: AgentComponentReference[]): ComponentLink[] | undefined {
  if (!components) return undefined;
  return components.map((component) => ({
    component_type: component.component_type,
    component_id: component.component_id,
    component_name: component.component_name,
    mcp_name: component.mcp_name,
    name: component.name,
    resolved_version: component.resolved_version,
    status: component.status,
  }));
}

function getComponentName(component: ComponentLink): string {
  return component.mcp_name ?? component.component_name ?? component.name ?? component.component_id ?? component.mcp_id ?? "Unnamed";
}

function getComponentType(component: ComponentLink): string {
  return component.component_type ?? "mcp";
}

function getComponentGroup(component: ComponentLink): ComponentGroupKey {
  return COMPONENT_GROUP_BY_TYPE[getComponentType(component)] ?? "mcps";
}

function groupComponents(components: ComponentLink[]): Record<ComponentGroupKey, ComponentLink[]> {
  return components.reduce<Record<ComponentGroupKey, ComponentLink[]>>(
    (groups, component) => {
      groups[getComponentGroup(component)].push(component);
      return groups;
    },
    { mcps: [], skills: [], hooks: [], prompts: [], sandboxes: [] },
  );
}

interface AgentDetail {
  name: string;
  status?: string;
  version?: string;
  owner?: string;
  user_permission?: string;
  description?: string;
  prompt?: string;
  model_name?: string;
  download_count?: number;
  created_by?: string;
  component_links?: ComponentLink[];
  mcp_links?: ComponentLink[];
  supported_ides?: string[];
  required_ide_features?: string[];
  inferred_supported_ides?: string[];
  [key: string]: unknown;
}

interface ComponentLink {
  mcp_name?: string;
  component_name?: string;
  name?: string;
  component_type?: string;
  component_id?: string;
  mcp_id?: string;
  resolved_version?: string;
  status?: string;
}

function VersionContentLoading() {
  return (
    <div className="flex items-center gap-2 rounded-md border border-border p-4 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />
      Loading version contents...
    </div>
  );
}

function ArchivedComponentsBanner({ components }: { components: ComponentLink[] }) {
  const names = components.slice(0, 3).map(getComponentName).join(", ");
  const extra = components.length > 3 ? ` and ${components.length - 3} more` : "";

  return (
    <div className="flex items-start gap-3 rounded-md border border-dark-yellow/30 bg-light-yellow px-4 py-3 text-dark-yellow">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="space-y-1 text-sm">
        <p className="font-medium">
          This agent includes archived components: {names}{extra}.
        </p>
        <p className="text-xs text-dark-yellow/80">
          Users can still pull the agent, but installs will show archived component warnings.
        </p>
      </div>
    </div>
  );
}

function AgentVersionContents({
  description,
  modelName,
  prompt,
  components,
}: {
  description?: string;
  modelName?: string;
  prompt?: string;
  components: ComponentLink[];
}) {
  const [activeTab, setActiveTab] = useState<ComponentGroupKey>("mcps");
  const groupedComponents = useMemo(() => groupComponents(components), [components]);

  return (
    <div className="space-y-6">
      <section className="space-y-4">
        <div className="space-y-2">
          <h3 className="text-sm font-medium">Description</h3>
          <div className="min-h-20 max-w-lg select-text rounded-md border border-border bg-surface-sunken px-3 py-2 text-sm leading-relaxed text-foreground cursor-default">
            {description ? (
              <p className="whitespace-pre-wrap">{description}</p>
            ) : (
              <p className="text-muted-foreground">No description provided.</p>
            )}
          </div>
        </div>

        <div className="space-y-2 max-w-xs">
          <h3 className="text-sm font-medium">Model</h3>
          <div className="select-text rounded-md border border-border bg-surface-sunken px-3 py-2 text-sm cursor-default">
            {modelName ? (
              <code className="font-mono text-foreground">{modelName}</code>
            ) : (
              <span className="text-muted-foreground">No model specified.</span>
            )}
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-medium">Agent Prompt</h3>
        <div className="min-h-40 select-text rounded-md border border-border bg-surface-sunken px-3 py-2 text-sm cursor-default">
          {prompt ? (
            <pre className="whitespace-pre-wrap break-words font-mono leading-relaxed text-foreground">{prompt}</pre>
          ) : (
            <p className="text-muted-foreground">No inline prompt provided.</p>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Version-specific system prompt. Prompt components, when linked, are listed below.
        </p>
      </section>

      <Separator />

      <section className="space-y-4">
        <div>
          <h3 className="text-sm font-medium font-display">Components</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            MCPs, skills, hooks, prompts, and sandboxes linked to this agent version.
          </p>
        </div>

        {components.length === 0 ? (
          <EmptyState
            icon={Puzzle}
            title="No components linked"
            description="This version does not have any linked MCP servers or components."
          />
        ) : (
          <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as ComponentGroupKey)}>
            <TabsList>
              {COMPONENT_TYPES.map((componentType) => {
                const count = groupedComponents[componentType.value].length;
                return (
                  <TabsTrigger key={componentType.value} value={componentType.value}>
                    {componentType.label}
                    {count > 0 && (
                      <span className="ml-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-medium text-primary-foreground">
                        {count}
                      </span>
                    )}
                  </TabsTrigger>
                );
              })}
            </TabsList>

            {COMPONENT_TYPES.map((componentType) => {
              const items = groupedComponents[componentType.value];
              return (
                <TabsContent key={componentType.value} value={componentType.value} className="mt-3">
                  {items.length === 0 ? (
                    <p className="py-6 text-center text-sm text-muted-foreground">
                      No {componentType.label} linked to this version.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {items.map((component, index) => {
                        const componentName = getComponentName(component);
                        const componentId = component.component_id ?? component.mcp_id;
                        const row = (
                          <div className="flex items-center justify-between gap-3 rounded-md border border-border px-4 py-3 transition-colors hover:bg-accent/40">
                            <div className="flex min-w-0 items-center gap-3">
                              <Badge variant="outline" className="shrink-0 text-[10px]">
                                {componentType.singular}
                              </Badge>
                              {component.status === "archived" && (
                                <StatusBadge status="archived" className="shrink-0" />
                              )}
                              <span className="truncate text-sm font-medium">{componentName}</span>
                              {component.resolved_version && (
                                <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                                  {component.resolved_version === "latest" ? "latest" : `v${component.resolved_version}`}
                                </span>
                              )}
                            </div>
                            {component.status && component.status !== "archived" && <StatusBadge status={component.status} />}
                          </div>
                        );

                        return componentId ? (
                          <Link
                            key={`${componentType.value}-${componentId}-${index}`}
                            to="/components/$componentId"
                            params={{ componentId }}
                            search={{ type: componentType.value }}
                          >
                            {row}
                          </Link>
                        ) : (
                          <div key={`${componentType.value}-${componentName}-${index}`}>{row}</div>
                        );
                      })}
                    </div>
                  )}
                </TabsContent>
              );
            })}
          </Tabs>
        )}
      </section>
    </div>
  );
}

function AgentDeleteButton({ agentId, agentName, onSuccess }: { agentId: string; agentName: string; onSuccess: () => void }) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const archiveMutation = useArchiveAgent();

  function submit() {
    archiveMutation.mutate(agentId, {
      onSuccess: () => {
        setConfirmOpen(false);
        onSuccess();
      },
    });
  }

  return (
    <>
      <Button variant="destructive" size="sm" className="h-8" onClick={() => setConfirmOpen(true)} disabled={archiveMutation.isPending}>
        <Trash2 className="mr-1 h-3.5 w-3.5" />
        Delete
      </Button>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {agentName}?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This archives the agent and hides it from registry lists. It can be restored later.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={submit} disabled={archiveMutation.isPending}>
              {archiveMutation.isPending ? <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />Deleting...</> : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function AgentArchiveButton({ agentId, agentName, status, onSuccess }: { agentId: string; agentName: string; status?: string; onSuccess: () => void }) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const archiveMutation = useArchiveAgent();
  const unarchiveMutation = useUnarchiveAgent();
  const isArchived = status === "archived";
  const isBusy = archiveMutation.isPending || unarchiveMutation.isPending;

  function submit() {
    const mutation = isArchived ? unarchiveMutation : archiveMutation;
    mutation.mutate(agentId, {
      onSuccess: () => {
        setConfirmOpen(false);
        onSuccess();
      },
    });
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className={isArchived ? "h-8" : "h-8 border-dark-yellow/40 bg-light-yellow text-dark-yellow hover:bg-light-yellow/80"}
        onClick={() => setConfirmOpen(true)}
        disabled={isBusy}
      >
        {isArchived ? <ArchiveRestore className="mr-1 h-3.5 w-3.5" /> : <Archive className="mr-1 h-3.5 w-3.5" />}
        {isArchived ? "Restore" : "Archive"}
      </Button>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{isArchived ? `Restore ${agentName}?` : `Archive ${agentName}?`}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {isArchived
              ? "This makes the agent discoverable again."
              : "Archived agents stop appearing in registry lists. Direct pulls still work by ID."}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button
              variant={isArchived ? "default" : "outline"}
              className={isArchived ? undefined : "border-dark-yellow/40 bg-light-yellow text-dark-yellow hover:bg-light-yellow/80"}
              onClick={submit}
              disabled={isBusy}
            >
              {isBusy ? <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />Saving...</> : isArchived ? "Restore" : "Archive"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}


function InsightStatusBadge({ status }: { status: InsightReportListItem["status"] }) {
  switch (status) {
    case "completed":
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-dark-green bg-light-green px-2 py-0.5 rounded-full">
          <CheckCircle2 className="h-3 w-3" /> Completed
        </span>
      );
    case "running":
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-dark-blue bg-light-blue px-2 py-0.5 rounded-full">
          <Loader2 className="h-3 w-3 animate-spin" /> Running
        </span>
      );
    case "pending":
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
          <Clock className="h-3 w-3" /> Queued
        </span>
      );
    case "failed":
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-dark-red bg-light-red px-2 py-0.5 rounded-full">
          <XCircle className="h-3 w-3" /> Failed
        </span>
      );
  }
}

function InsightsTab({ agentId, agentVersion }: { agentId: string; agentVersion?: string | null }) {
  const { data: reports, isLoading: reportsLoading } = useInsightReports(agentId);
  const { data: sessionCountData, isLoading: countLoading } = useInsightSessionCount(agentId, agentVersion);
  const { data: insightsStatus } = useInsightsStatus();
  const generateInsight = useGenerateInsight();

  const availableSessions = sessionCountData?.session_count ?? 0;
  const notConfigured = insightsStatus && !insightsStatus.available;
  const hasRunning = (reports ?? []).some((r) => r.status === "pending" || r.status === "running");

  return (
    <div className="space-y-6">
      {/* Status / Generate bar */}
      <div className="flex items-center justify-between gap-4 rounded-md border border-border p-4">
        <div className="space-y-1">
          <h3 className="text-sm font-semibold font-display flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            Agent Insights
          </h3>
          <p className="text-xs text-muted-foreground">
            {countLoading
              ? "Checking sessions..."
              : `${availableSessions} session${availableSessions !== 1 ? "s" : ""} available for ${sessionCountData?.agent_version ?? agentVersion ?? "latest approved"} (last 14 days)`}
          </p>
        </div>
        <Button
          size="sm"
          className="gap-1.5"
          disabled={
            !!notConfigured ||
            (!countLoading && availableSessions === 0) ||
            generateInsight.isPending ||
            hasRunning
          }
          onClick={() => generateInsight.mutate({ agentId, agentVersion: agentVersion ?? undefined })}
        >
          {generateInsight.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
          Generate
        </Button>
      </div>

      {notConfigured && (
        <p className="text-xs text-muted-foreground">
          Insights are not configured on this server. Contact your admin.
        </p>
      )}

      {/* Reports list */}
      {reportsLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading reports...
        </div>
      ) : !reports || reports.length === 0 ? (
        <EmptyState
          icon={Sparkles}
          title="No insights yet"
          description="Generate your first insight report to see how this agent is performing."
        />
      ) : (
        <div className="space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Reports</h4>
          <div className="space-y-2">
            {reports.map((report) => (
              <Link
                key={report.id}
                to="/agents/$agentId/insights/$reportId"
                params={{ agentId, reportId: report.id }}
                className="flex items-center justify-between gap-4 rounded-md border border-border p-3 hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <InsightStatusBadge status={report.status} />
                  <span className="text-xs text-muted-foreground font-mono tabular-nums">
                    {new Date(report.created_at).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                    })}
                  </span>
                  {report.agent_version && (
                    <span className="text-xs text-muted-foreground">
                      v{report.agent_version}
                    </span>
                  )}
                  {report.sessions_analyzed > 0 && (
                    <span className="text-xs text-muted-foreground">
                      {report.sessions_analyzed} sessions analyzed
                    </span>
                  )}
                  {(report.status === "pending" || report.status === "running") && report.progress_phase && (
                    <span className="text-xs text-muted-foreground">
                      {report.progress_phase.replace(/_/g, " ")}
                    </span>
                  )}
                </div>
                {report.status === "completed" && (
                  <span className="text-xs text-primary">View →</span>
                )}
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


export default function AgentDetailPage() {
  const { agentId: id } = useParams({ from: "/_authed/agents/$agentId" });
  const {
    data: agent,
    isLoading,
    isError,
    error,
    refetch,
  } = useRegistryItem("agents", id);
  const { data: downloadData } = useAgentDownloads(id);
  const { data: feedbackItems, refetch: refetchFeedback } = useFeedback(
    "agent",
    id,
  );
  const { data: feedbackSummary, refetch: refetchSummary } =
    useFeedbackSummary(id);
  const { data: myReview } = useMyFeedback("agent", id);

  const { data: whoami } = useWhoami();
  const { data: versionsData } = useAgentVersions(id);
  const [selectedVersion, setSelectedVersion] = useState<string | null>(null);
  const { data: versionDetail, isLoading: isVersionDetailLoading } = useAgentVersionDetail(id, selectedVersion);

  // Co-authors
  const [coAuthors, setCoAuthors] = useState<CoAuthor[]>([]);
  useEffect(() => {
    const token = sessionStorage.getItem("observal_access_token");
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    fetch(`/api/v1/agents/${id}/co-authors`, { headers })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setCoAuthors(data))
      .catch(() => {});
  }, [id]);

  const storeSub = useCallback((cb: () => void) => {
    window.addEventListener("storage", cb);
    return () => window.removeEventListener("storage", cb);
  }, []);
  const isAuthenticated = useSyncExternalStore(
    storeSub,
    () => !!sessionStorage.getItem("observal_access_token"),
    () => false,
  );
  const isAdmin = useSyncExternalStore(
    storeSub,
    () => hasMinRole(getUserRole(), "admin"),
    () => false,
  );

  const a = agent as unknown as AgentDetail | undefined;
  const versions = versionsData?.items ?? [];
  const latestApprovedVersion = useMemo(() => getLatestApprovedVersion(versions), [versions]);
  const effectiveVersion = selectedVersion ?? latestApprovedVersion ?? a?.version;
  const selectedVersionSummary = versions.find((v) => v.version === effectiveVersion);
  const vd = versionDetail;
  const isVersionContentLoading = !!selectedVersion && !vd && isVersionDetailLoading;
  const baseComponents: ComponentLink[] = a?.component_links ?? a?.mcp_links ?? [];
  const versionComponents = selectedVersion ? normalizeVersionComponents(vd?.components) : undefined;
  const components: ComponentLink[] = selectedVersion ? (versionComponents ?? []) : baseComponents;
  const displayComponentCount = selectedVersion
    ? (versionComponents?.length ?? selectedVersionSummary?.component_count ?? 0)
    : components.length;
  const versionDescription = vd?.description ?? selectedVersionSummary?.description ?? a?.description;
  const versionPrompt = vd?.prompt ?? (selectedVersion ? undefined : a?.prompt);
  const versionModelName = vd?.model_name ?? (selectedVersion ? undefined : a?.model_name);
  const versionSupportedIdes = vd?.supported_ides ?? selectedVersionSummary?.supported_ides ?? a?.supported_ides;
  const versionRequiredFeatures = vd?.required_ide_features ?? (selectedVersion ? undefined : a?.required_ide_features);
  const versionInferredIdes = vd?.inferred_supported_ides ?? (selectedVersion ? undefined : a?.inferred_supported_ides);
  const isOwner = !!(whoami?.id && a?.created_by && whoami.id === String(a.created_by));
  const canTransferOwnership = isOwner;
  const canManageLifecycle = isAdmin || isOwner;
  const agentStatus = a?.status as string | undefined;
  const canEdit = (isAdmin || a?.user_permission === "owner" || a?.user_permission === "edit") && ["approved", "pending", "draft", "rejected"].includes(agentStatus ?? "");
  const agentName = a?.name ?? id.slice(0, 8);
  const totalDownloads = downloadData?.total ?? a?.download_count;
  const uniqueUsers = downloadData?.unique_users;
  const archivedComponents = components.filter((component) => component.status === "archived");
  const avgRating = feedbackSummary?.average_rating;
  const totalReviews = feedbackSummary?.total_reviews ?? 0;

  return (
    <>
      <PageHeader
        title={isLoading ? "Agent" : agentName}
        breadcrumbs={[
          { label: "Registry", href: "/" },
          { label: "Agents", href: "/agents" },
          { label: isLoading ? "..." : agentName },
        ]}
      />

      <div className="p-6 lg:p-8 w-full">
        {isLoading ? (
          <DetailSkeleton />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : !a ? (
          <ErrorState message="Agent not found" />
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-8 items-start">
            {/* Main content */}
            <div className="space-y-6 min-w-0 animate-in">
              {canEdit && archivedComponents.length > 0 && (
                <ArchivedComponentsBanner components={archivedComponents} />
              )}

              {/* Header */}
              <div className="space-y-2">
                <div className="flex items-start gap-3 flex-wrap">
                  <h1 className="text-2xl font-display font-bold tracking-tight">
                    {a.name}
                  </h1>
                  {a.status && <StatusBadge status={a.status} />}
                  {versions.length > 0 ? (
                    <VersionDropdown
                      versions={versions}
                      currentVersion={effectiveVersion ?? ""}
                      onSelect={setSelectedVersion}
                    />
                  ) : a?.version ? (
                    <Badge variant="secondary" className="text-xs">
                      {a.version}
                    </Badge>
                  ) : null}
                </div>

                {a.owner && (
                  <p className="text-sm text-muted-foreground">{a.owner}</p>
                )}

                {versionDescription && (
                  <p className="text-sm text-foreground/80 leading-relaxed max-w-2xl">
                    {versionDescription}
                  </p>
                )}
              </div>

              {/* Stats row (mobile only) */}
              <div className="flex items-center gap-6 text-sm text-muted-foreground lg:hidden">
                {totalDownloads != null && (
                  <span className="inline-flex items-center gap-1.5">
                    <ArrowDownToLine className="h-4 w-4" />
                    {compactNumber(totalDownloads)} downloads
                  </span>
                )}
                <span className="inline-flex items-center gap-1.5">
                  <Puzzle className="h-4 w-4" />
                  {displayComponentCount} components
                </span>
                {avgRating != null && (
                  <span className="inline-flex items-center gap-1.5">
                    <Star className="h-4 w-4" />
                    {avgRating.toFixed(1)}
                  </span>
                )}
              </div>

              {/* Pull command (mobile only) */}
              <div className="lg:hidden">
                <PullCommand
                  agentName={a.name}
                  currentVersion={effectiveVersion}
                  latestVersion={latestApprovedVersion ?? a.version}
                />
              </div>

              {/* Tabs */}
              <Tabs defaultValue="overview">
                <TabsList>
                  <TabsTrigger value="overview">Overview</TabsTrigger>
                  <TabsTrigger value="components">
                    Components
                    {displayComponentCount > 0 && (
                      <span className="ml-1.5 text-[10px] bg-muted px-1.5 py-0.5 rounded-full">
                        {displayComponentCount}
                      </span>
                    )}
                  </TabsTrigger>
                  <TabsTrigger value="reviews">
                    Reviews
                    {totalReviews > 0 && (
                      <span className="ml-1.5 text-[10px] bg-muted px-1.5 py-0.5 rounded-full">
                        {totalReviews}
                      </span>
                    )}
                  </TabsTrigger>
                  {canEdit && <TabsTrigger value="edit">Edit</TabsTrigger>}
                  {canEdit && <TabsTrigger value="insights">Insights</TabsTrigger>}

                </TabsList>

                <TabsContent value="overview" className="space-y-6 mt-6">
                  {versionDescription && (
                    <div className="space-y-2">
                      <h3 className="text-sm font-semibold font-display">
                        About
                      </h3>
                      <p className="text-sm text-muted-foreground leading-relaxed">
                        {versionDescription}
                      </p>
                    </div>
                  )}

                  {versionModelName && (
                    <div className="space-y-1">
                      <h3 className="text-sm font-semibold font-display">
                        Model
                      </h3>
                      <p className="text-sm text-muted-foreground font-mono">
                        {versionModelName}
                      </p>
                    </div>
                  )}


                  {!versionDescription && (
                    <p className="text-sm text-muted-foreground">
                      No additional details provided for this agent.
                    </p>
                  )}
                </TabsContent>

                <TabsContent value="components" className="mt-6">
                  <div className="min-h-[300px]">
                    {isVersionContentLoading ? (
                      <VersionContentLoading />
                    ) : (
                      <AgentVersionContents
                        description={versionDescription}
                        modelName={versionModelName}
                        prompt={versionPrompt}
                        components={components}
                      />
                    )}
                  </div>
                </TabsContent>

                <TabsContent value="reviews" className="mt-6 space-y-6">
                  {isAuthenticated && (
                    <>
                      <ReviewForm
                        listingId={id}
                        listingType="agent"
                        onSuccess={() => {
                          refetchFeedback();
                          refetchSummary();
                        }}
                      />
                      <Separator />
                    </>
                  )}

                  {!feedbackItems || feedbackItems.length === 0 ? (
                    <EmptyState
                      icon={Star}
                      title="No reviews yet"
                      description={
                        isAuthenticated
                          ? "Be the first to review this agent."
                          : "Log in to leave a review."
                      }
                    />
                  ) : (
                    <div className="space-y-4">
                      {feedbackItems
                        .filter((fb: FeedbackItem) => !myReview || fb.id !== myReview.id)
                        .map((fb: FeedbackItem) => (
                        <div
                          key={fb.id}
                          className="rounded-md border border-border p-4 space-y-2"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-1">
                              {Array.from({ length: 5 }).map((_, i) => (
                                <Star
                                  key={i}
                                  className={`h-3.5 w-3.5 ${
                                    i < fb.rating
                                      ? "fill-current text-amber-500"
                                      : "text-muted-foreground/30"
                                  }`}
                                />
                              ))}
                            </div>
                            <span className="text-xs text-muted-foreground">
                              {fb.username ?? fb.user ?? "Anonymous"}
                              {fb.created_at &&
                                ` · ${new Date(fb.created_at).toLocaleDateString()}`}
                            </span>
                          </div>
                          {fb.comment && (
                            <p className="text-sm text-muted-foreground leading-relaxed">
                              {fb.comment}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </TabsContent>

                {canEdit && (
                  <TabsContent value="edit" className="mt-6">
                    {isVersionContentLoading ? (
                      <VersionContentLoading />
                    ) : (
                      <AgentEditForm
                        agentId={id}
                        agent={a as unknown as AgentEditFormProps["agent"]}
                        versionDetail={vd}
                        currentVersion={effectiveVersion ?? "1.0.0"}
                      />
                    )}
                  </TabsContent>
                )}
                {canEdit && (
                  <TabsContent value="insights" className="mt-6">
                    <InsightsTab agentId={id} agentVersion={effectiveVersion} />
                  </TabsContent>
                )}

              </Tabs>
            </div>

            {/* Sidebar (desktop) */}
            <aside className="hidden lg:block space-y-5 animate-in stagger-1">
              <PullCommand
                agentName={a.name}
                currentVersion={effectiveVersion}
                latestVersion={latestApprovedVersion ?? a.version}
              />

              <div className="border border-border rounded-md p-4 space-y-4">
                <h3 className="text-xs font-semibold font-display uppercase tracking-wider text-muted-foreground">
                  Stats
                </h3>
                <div className="space-y-3">
                  {totalDownloads != null && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="inline-flex items-center gap-2 text-muted-foreground">
                        <ArrowDownToLine className="h-3.5 w-3.5" />
                        Downloads
                      </span>
                      <span className="font-mono font-medium">
                        {compactNumber(totalDownloads)}
                      </span>
                    </div>
                  )}
                  {uniqueUsers != null && uniqueUsers > 0 && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="inline-flex items-center gap-2 text-muted-foreground">
                        <Users className="h-3.5 w-3.5" />
                        Unique users
                      </span>
                      <span className="font-mono font-medium">
                        {compactNumber(uniqueUsers)}
                      </span>
                    </div>
                  )}
                  {avgRating != null && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="inline-flex items-center gap-2 text-muted-foreground">
                        <Star className="h-3.5 w-3.5" />
                        Rating
                      </span>
                      <span className="font-mono font-medium">
                        {avgRating.toFixed(1)}{" "}
                        <span className="text-xs text-muted-foreground font-normal">
                          ({totalReviews})
                        </span>
                      </span>
                    </div>
                  )}
                  <div className="flex items-center justify-between text-sm">
                    <span className="inline-flex items-center gap-2 text-muted-foreground">
                      <Puzzle className="h-3.5 w-3.5" />
                      Components
                    </span>
                    <span className="font-mono font-medium">
                      {displayComponentCount}
                    </span>
                  </div>
                  {versionModelName && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Model</span>
                      <span className="font-mono text-xs truncate max-w-[140px]">
                        {versionModelName}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              <div className="border border-border rounded-md p-4 space-y-3">
                <h3 className="text-xs font-semibold font-display uppercase tracking-wider text-muted-foreground">
                  IDE Compatibility
                </h3>
                <IdeBadges
                  supportedIdes={versionSupportedIdes}
                  inferredSupportedIdes={versionInferredIdes}
                  max={7}
                />
                {versionRequiredFeatures && versionRequiredFeatures.length > 0 && (
                  <div className="space-y-1">
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground/60">
                      Required features
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {versionRequiredFeatures.map((f: string) => (
                        <span key={f} className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                          {FEATURE_LABELS[f] ?? f}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {a.owner && (
                <div className="border border-border rounded-md p-4 space-y-2">
                  <h3 className="text-xs font-semibold font-display uppercase tracking-wider text-muted-foreground">
                    Publisher
                  </h3>
                  <p className="text-sm">{a.owner}</p>
                </div>
              )}

              {(a?.user_permission === "owner" || coAuthors.length > 0 || canManageLifecycle) && (
                <div className="border border-border rounded-md p-4 space-y-4">
                  <h3 className="text-xs font-semibold font-display uppercase tracking-wider text-muted-foreground">
                    Danger zone
                  </h3>

                  {(a?.user_permission === "owner" || coAuthors.length > 0) && (
                    <CoAuthorInput
                      entityType="agents"
                      entityId={id}
                      coAuthors={coAuthors}
                      onChange={setCoAuthors}
                      canManage={a?.user_permission === "owner"}
                      canTransferOwnership={canTransferOwnership}
                      onTransferOwnership={() => refetch()}
                    />
                  )}

                  {canManageLifecycle && (agentStatus === "approved" || agentStatus === "archived") && (
                    <div className="border-t border-border pt-3 space-y-2">
                      <p className="text-sm font-medium">Lifecycle</p>
                      <div className="flex flex-wrap gap-2">
                        <AgentArchiveButton agentId={id} agentName={agentName} status={agentStatus} onSuccess={() => refetch()} />
                        {agentStatus === "approved" && (
                          <AgentDeleteButton agentId={id} agentName={agentName} onSuccess={() => refetch()} />
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </aside>
          </div>
        )}
      </div>
    </>
  );
}


