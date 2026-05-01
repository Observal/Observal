"use client";

import { use } from "react";
import Link from "next/link";
import {
  ArrowDownToLine,
  Puzzle,
  Star,
  Check,
  Copy,
  Users,
  Download,
  BarChart3,
  Loader2,
  Activity,
  Trash2,
  Lock,
  Globe,
  Edit,
  Plus,
} from "lucide-react";
import { useState, useCallback, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import {
  useRegistryItem,
  useAgentDownloads,
  useFeedback,
  useFeedbackSummary,
  useEvalAggregate,
  useWhoami,
  useUpdateAgent,
  useAgentVersions,
  useAgentVersionDetail,
} from "@/hooks/use-api";
import { registry, getUserRole } from "@/lib/api";
import { hasMinRole } from "@/hooks/use-role-guard";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import type { FeedbackItem } from "@/lib/types";
import { PullCommand } from "@/components/registry/pull-command";
import { VersionDropdown } from "@/components/registry/version-dropdown";
import { StatusBadge } from "@/components/registry/status-badge";
import { IdeBadges } from "@/components/registry/ide-badges";
import { FEATURE_LABELS, type IdeFeature } from "@/lib/ide-features";
import { ReviewForm } from "@/components/registry/review-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/layouts/page-header";
import { DetailSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { AgentEditForm, type AgentEditFormProps } from "@/components/registry/agent-edit-form";
import { compactNumber, copyToClipboard } from "@/lib/utils";
import { DIMENSION_META } from "@/components/dashboard/score-overview";

interface AgentDetail {
  name: string;
  status?: string;
  version?: string;
  owner?: string;
  visibility?: string;
  team_accesses?: { group_name: string; permission: "view" | "edit" }[];
  user_permission?: string;
  description?: string;
  prompt?: string;
  model_name?: string;
  download_count?: number;
  created_by?: string;
  component_links?: ComponentLink[];
  mcp_links?: ComponentLink[];
  goal_template?: {
    description?: string;
    sections?: { name: string; description?: string }[];
  };
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
  status?: string;
}

function ExportButton({ agentId }: { agentId: string }) {
  const [exporting, setExporting] = useState(false);

  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      const manifest = await registry.manifest(agentId);
      const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `agent-${agentId.slice(0, 8)}.json`;
      link.click();
      URL.revokeObjectURL(url);
      toast.success("Agent manifest exported");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to export agent");
    } finally {
      setExporting(false);
    }
  }, [agentId]);

  return (
    <Button variant="outline" size="sm" className="h-8" onClick={handleExport} disabled={exporting}>
      {exporting ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Download className="mr-1 h-3.5 w-3.5" />}
      Export
    </Button>
  );
}

function DeleteButton({ agentId, agentName }: { agentId: string; agentName: string }) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const router = useRouter();
  const qc = useQueryClient();

  async function handleDelete() {
    setDeleting(true);
    try {
      await registry.delete("agents", agentId);
      qc.invalidateQueries({ queryKey: ["registry", "agents"] });
      toast.success("Agent deleted");
      router.push("/agents");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete agent");
      setDeleting(false);
      setConfirmOpen(false);
    }
  }

  return (
    <>
      <Button variant="destructive" size="sm" className="h-8" onClick={() => setConfirmOpen(true)}>
        <Trash2 className="mr-1 h-3.5 w-3.5" />
        Delete
      </Button>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {agentName}?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This will permanently delete this agent and all associated data. This action cannot be undone.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />Deleting...</> : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function AnalyticsTab({ agentId }: { agentId: string }) {
  const { data: aggregate, isLoading } = useEvalAggregate(agentId);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!aggregate) {
    return (
      <EmptyState
        icon={BarChart3}
        title="No analytics yet"
        description="Run evaluations on this agent to generate analytics data. Traces and spans will be collected as the agent is used."
      />
    );
  }

  const dims = aggregate.dimension_averages ?? {};
  const trend = aggregate.trend ?? [];

  return (
    <div className="space-y-6">
      {/* Score overview */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="rounded-md border border-border p-3 space-y-1">
          <span className="text-xs text-muted-foreground">Composite Score</span>
          <p className="text-xl font-mono font-bold">{aggregate.mean.toFixed(1)}</p>
        </div>
        <div className="rounded-md border border-border p-3 space-y-1">
          <span className="text-xs text-muted-foreground">Std Dev</span>
          <p className="text-xl font-mono font-bold">{aggregate.std.toFixed(2)}</p>
        </div>
        <div className="rounded-md border border-border p-3 space-y-1">
          <span className="text-xs text-muted-foreground">95% CI</span>
          <p className="text-sm font-mono font-medium">{aggregate.ci_low.toFixed(1)} - {aggregate.ci_high.toFixed(1)}</p>
        </div>
        <div className="rounded-md border border-border p-3 space-y-1">
          <span className="text-xs text-muted-foreground">Drift Alert</span>
          <p className="text-sm font-medium">
            {aggregate.drift_alert ? (
              <Badge variant="destructive" className="text-[10px]">Drift detected</Badge>
            ) : (
              <Badge variant="outline" className="text-[10px]">Stable</Badge>
            )}
          </p>
        </div>
      </div>

      {/* Dimension scores */}
      {Object.keys(dims).length > 0 && (
        <div className="space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Dimension Averages</h4>
          <div className="space-y-2.5">
            {Object.entries(dims).map(([dim, score]) => {
              const meta = DIMENSION_META[dim];
              const clampedScore = Math.max(0, Math.min(100, Number(score)));
              return (
                <div key={dim} className="space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">{meta?.label ?? dim}</span>
                    <span className="text-xs font-mono tabular-nums">{Math.round(clampedScore)}<span className="text-muted-foreground">/100</span></span>
                  </div>
                  <div className="h-2 bg-muted rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${meta?.color ?? "bg-primary"}`}
                      style={{ width: `${clampedScore}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          {aggregate.weakest_dimension && (
            <p className="text-xs text-muted-foreground mt-2">
              Weakest: <span className="text-foreground font-medium">{aggregate.weakest_dimension}</span>
            </p>
          )}
        </div>
      )}

      {/* Score trend */}
      {trend.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Score Trend</h4>
          <div className="rounded-md border border-border p-4 overflow-x-auto">
            <div className="flex items-end gap-1 h-24 min-w-[200px]">
              {trend.map((t, i) => {
                const height = Math.max(t.composite * 10, 2);
                return (
                  <div key={i} className="flex-1 flex flex-col items-center gap-1" title={`${new Date(t.timestamp).toLocaleDateString()}: ${t.composite.toFixed(1)}`}>
                    <div
                      className="w-full bg-primary/70 rounded-t transition-all hover:bg-primary"
                      style={{ height: `${height}%` }}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Link to traces */}
      <div className="rounded-md border border-border p-4 space-y-2">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-muted-foreground" />
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Traces & Spans</h4>
        </div>
        <p className="text-xs text-muted-foreground">View detailed trace and span data for this agent in the admin dashboard.</p>
        <Link href="/traces" className="text-xs text-primary hover:underline inline-flex items-center gap-1">
          View traces →
        </Link>
      </div>
    </div>
  );
}

function AccessSettingsWidget({ agentId, visibility, teamAccesses, canEdit }: { agentId: string; visibility?: string; teamAccesses?: { group_name: string; permission: "view" | "edit" }[]; canEdit: boolean }) {
  const { deploymentMode } = useDeploymentConfig();
  const [isEditing, setIsEditing] = useState(false);
  const [editVisibility, setEditVisibility] = useState<"public" | "private">(visibility === "public" ? "public" : "private");
  const [editTeamAccesses, setEditTeamAccesses] = useState<{ group_name: string; permission: "view" | "edit" }[]>(teamAccesses ?? []);
  const updateAgent = useUpdateAgent();

  if (deploymentMode !== "enterprise") return null;

  async function handleSave() {
    try {
      await updateAgent.mutateAsync({
        id: agentId,
        body: {
          visibility: editVisibility,
          team_accesses: editTeamAccesses,
        },
      });
      setIsEditing(false);
    } catch (e) {
      // toast is handled in the mutation
    }
  }

  if (!isEditing) {
    return (
      <div className="border border-border rounded-md p-4 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold font-display uppercase tracking-wider text-muted-foreground">
            Access Settings
          </h3>
          {canEdit && (
            <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:text-foreground" onClick={() => {
              setEditVisibility(visibility === "public" ? "public" : "private");
              setEditTeamAccesses(teamAccesses ?? []);
              setIsEditing(true);
            }}>
              <Edit className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
        
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm">
            {visibility === "public" ? <Globe className="h-4 w-4 text-muted-foreground" /> : <Lock className="h-4 w-4 text-muted-foreground" />}
            <span className="font-medium">{visibility === "public" ? "Public" : "Private"}</span>
          </div>

          {teamAccesses && teamAccesses.length > 0 && (
            <div className="space-y-1.5 pt-2 border-t border-border/50">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Groups</span>
              {teamAccesses.map((acc, i) => (
                <div key={i} className="flex items-center justify-between text-xs">
                  <span className="font-mono">{acc.group_name}</span>
                  <Badge variant="outline" className="text-[10px]">{acc.permission}</Badge>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="border border-border rounded-md p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold font-display uppercase tracking-wider text-muted-foreground">
          Edit Access Settings
        </h3>
      </div>
      
      <div className="space-y-3">
        <select
          className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          value={editVisibility}
          onChange={(e) => setEditVisibility(e.target.value as "public" | "private")}
        >
          <option value="private">Private (Team Access Only)</option>
          <option value="public">Public (Visible to All)</option>
        </select>

        {editVisibility === "private" && (
          <div className="space-y-2 pt-2 border-t border-border/50">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Team Permissions</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() =>
                  setEditTeamAccesses([
                    ...editTeamAccesses,
                    { group_name: "", permission: "view" },
                  ])
                }
                className="h-6 text-xs px-2"
              >
                <Plus className="mr-1 h-3 w-3" />
                Add
              </Button>
            </div>

            <div className="space-y-2">
              {editTeamAccesses.map((access, i) => (
                <div key={i} className="flex items-center gap-1.5">
                  <Input
                    placeholder="Group"
                    value={access.group_name}
                    onChange={(e) => {
                      const newAccess = [...editTeamAccesses];
                      newAccess[i].group_name = e.target.value;
                      setEditTeamAccesses(newAccess);
                    }}
                    className="h-7 flex-1 text-xs px-2"
                  />
                  <select
                    className="flex h-7 w-16 rounded-md border border-input bg-transparent px-1.5 py-0 text-xs shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    value={access.permission}
                    onChange={(e) => {
                      const newAccess = [...editTeamAccesses];
                      newAccess[i].permission = e.target.value as "view" | "edit";
                      setEditTeamAccesses(newAccess);
                    }}
                  >
                    <option value="view">View</option>
                    <option value="edit">Edit</option>
                  </select>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => {
                      const newAccess = [...editTeamAccesses];
                      newAccess.splice(i, 1);
                      setEditTeamAccesses(newAccess);
                    }}
                    className="h-7 w-7 text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="flex gap-2 justify-end pt-2">
        <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => {
          setIsEditing(false);
          setEditVisibility(visibility === "public" ? "public" : "private");
          setEditTeamAccesses(teamAccesses ?? []);
        }}>Cancel</Button>
        <Button size="sm" className="h-7 text-xs" disabled={updateAgent.isPending} onClick={handleSave}>
          {updateAgent.isPending ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : "Save"}
        </Button>
      </div>
    </div>
  );
}

export default function AgentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
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

  const { data: whoami } = useWhoami();
  const { data: versionsData } = useAgentVersions(id);
  const [selectedVersion, setSelectedVersion] = useState<string | null>(null);
  const { data: versionDetail } = useAgentVersionDetail(id, selectedVersion);

  const storeSub = useCallback((cb: () => void) => {
    window.addEventListener("storage", cb);
    return () => window.removeEventListener("storage", cb);
  }, []);
  const isAuthenticated = useSyncExternalStore(
    storeSub,
    () => !!localStorage.getItem("observal_access_token"),
    () => false,
  );
  const isAdmin = useSyncExternalStore(
    storeSub,
    () => hasMinRole(getUserRole(), "admin"),
    () => false,
  );

  const a = agent as unknown as AgentDetail | undefined;
  const versions = versionsData?.items ?? [];
  const latestApprovedVersion = versions.find((v) => v.status === "approved")?.version;
  const effectiveVersion = selectedVersion ?? latestApprovedVersion ?? a?.version;
  // Overlay version-specific fields when viewing a non-default version
  const vd = versionDetail as Record<string, unknown> | undefined;
  const versionDescription = (vd?.description as string) ?? a?.description;
  const versionPrompt = (vd?.prompt as string) ?? a?.prompt;
  const versionModelName = (vd?.model_name as string) ?? a?.model_name;
  const versionSupportedIdes = (vd?.supported_ides as string[]) ?? a?.supported_ides;
  const versionRequiredFeatures = (vd?.required_ide_features as string[]) ?? a?.required_ide_features;
  const versionInferredIdes = (vd?.inferred_supported_ides as string[]) ?? a?.inferred_supported_ides;
  const canDelete = isAdmin || (whoami?.id && a?.created_by && whoami.id === String(a.created_by));
  const canEdit = isAdmin || a?.user_permission === "owner" || a?.user_permission === "edit";
  const components: ComponentLink[] = a?.component_links ?? a?.mcp_links ?? [];
  const goalTemplate = a?.goal_template;
  const agentName = a?.name ?? id.slice(0, 8);
  const totalDownloads = downloadData?.total ?? a?.download_count;
  const uniqueUsers = downloadData?.unique_users;
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
        actionButtonsRight={
          !isLoading && a ? (
            <div className="flex items-center gap-2">
              <ExportButton agentId={id} />
              {canDelete && <DeleteButton agentId={id} agentName={agentName} />}
            </div>
          ) : undefined
        }
      />

      <div className="p-6 lg:p-8 max-w-[1200px]">
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
                  {components.length} components
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
                <PullCommand agentName={a.name} />
              </div>

              {/* Tabs */}
              <Tabs defaultValue="overview">
                <TabsList>
                  <TabsTrigger value="overview">Overview</TabsTrigger>
                  <TabsTrigger value="components">
                    Components
                    {components.length > 0 && (
                      <span className="ml-1.5 text-[10px] bg-muted px-1.5 py-0.5 rounded-full">
                        {components.length}
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
                  <TabsTrigger value="install">Install</TabsTrigger>
                  {canEdit && <TabsTrigger value="edit">Edit</TabsTrigger>}
                  {isAdmin && <TabsTrigger value="analytics">Analytics</TabsTrigger>}
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

                  {goalTemplate && (
                    <div className="space-y-4">
                      <h3 className="text-sm font-semibold font-display">
                        Goal Template
                      </h3>
                      {goalTemplate.description && (
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          {goalTemplate.description}
                        </p>
                      )}
                      {goalTemplate.sections?.map(
                        (sec: { name: string; description?: string }, i: number) => (
                          <div key={i} className="space-y-1">
                            <h4 className="text-sm font-medium text-foreground">
                              {sec.name}
                            </h4>
                            {sec.description && (
                              <p className="text-xs text-muted-foreground leading-relaxed pl-3 border-l-2 border-border">
                                {sec.description}
                              </p>
                            )}
                          </div>
                        ),
                      )}
                    </div>
                  )}

                  {!versionDescription && !goalTemplate && (
                    <p className="text-sm text-muted-foreground">
                      No additional details provided for this agent.
                    </p>
                  )}
                </TabsContent>

                <TabsContent value="components" className="mt-6">
                  <div className="min-h-[300px]">
                  {components.length === 0 ? (
                    versionPrompt ? (
                      <div className="space-y-3">
                        <p className="text-xs text-muted-foreground">
                          This agent was registered via scan and uses an inline system prompt instead of linked components.
                        </p>
                        <div className="rounded-md border border-border bg-muted/20 p-4">
                          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">System Prompt</h4>
                          <pre className="text-xs font-[family-name:var(--font-mono)] whitespace-pre-wrap break-words text-foreground/80 leading-relaxed max-h-[400px] overflow-y-auto">
                            {String(versionPrompt)}
                          </pre>
                        </div>
                      </div>
                    ) : (
                      <EmptyState
                        icon={Puzzle}
                        title="No components linked"
                        description="This agent does not have any linked MCP servers or components."
                      />
                    )
                  ) : (
                    <div className="space-y-2">
                      {components.map((comp: ComponentLink, i: number) => {
                        const compName =
                          comp.mcp_name ??
                          comp.component_name ??
                          comp.name ??
                          "-";
                        const compType = comp.component_type ?? "mcp";
                        const compId = comp.component_id ?? comp.mcp_id;
                        const content = (
                          <div
                            className={[
                              "flex items-center justify-between gap-3 px-4 py-3 rounded-md border border-border",
                              "transition-colors",
                              compId
                                ? "hover:bg-accent/40 cursor-pointer"
                                : "",
                            ].join(" ")}
                          >
                            <div className="flex items-center gap-3 min-w-0">
                              <Badge
                                variant="outline"
                                className="text-[10px] shrink-0"
                              >
                                {compType}
                              </Badge>
                              <span className="text-sm font-medium truncate">
                                {compName}
                              </span>
                            </div>
                            {comp.status && (
                              <StatusBadge status={comp.status} />
                            )}
                          </div>
                        );

                        return compId ? (
                          <Link
                            key={i}
                            href={`/components/${compId}?type=${compType}s`}
                          >
                            {content}
                          </Link>
                        ) : (
                          <div key={i}>{content}</div>
                        );
                      })}
                    </div>
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
                      {feedbackItems.map((fb: FeedbackItem) => (
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

                <TabsContent value="install" className="mt-6 space-y-6">
                  <div className="space-y-2">
                    <h3 className="text-sm font-semibold font-display">
                      Quick Install
                    </h3>
                    <p className="text-xs text-muted-foreground">
                      Use the Observal CLI to pull this agent into your project.
                    </p>
                  </div>
                  <PullCommand agentName={a.name} />

                  <Separator />

                  <div className="space-y-3">
                    <h3 className="text-sm font-semibold font-display">
                      Manual Configuration
                    </h3>
                    <p className="text-xs text-muted-foreground">
                      Add the following to your IDE configuration to use this
                      agent directly.
                    </p>
                    <ConfigSnippet agentName={a.name} />
                  </div>
                </TabsContent>

                {canEdit && (
                  <TabsContent value="edit" className="mt-6">
                    <AgentEditForm
                      agentId={id}
                      agent={a as unknown as AgentEditFormProps["agent"]}
                      versionDetail={vd}
                      currentVersion={effectiveVersion ?? "1.0.0"}
                    />
                  </TabsContent>
                )}
                {isAdmin && (
                  <TabsContent value="analytics" className="mt-6">
                    <AnalyticsTab agentId={id} />
                  </TabsContent>
                )}
              </Tabs>
            </div>

            {/* Sidebar (desktop) */}
            <aside className="hidden lg:block space-y-5 animate-in stagger-1">
              <PullCommand agentName={a.name} />

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
                      {components.length}
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
                          {FEATURE_LABELS[f as IdeFeature] ?? f}
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

              <AccessSettingsWidget
                agentId={id}
                visibility={a.visibility}
                teamAccesses={a.team_accesses}
                canEdit={isAdmin || a.user_permission === "owner" || a.user_permission === "edit"}
              />
            </aside>
          </div>
        )}
      </div>
    </>
  );
}

function ConfigSnippet({
  agentName,
}: {
  agentName: string;
}) {
  const [copied, setCopied] = useState(false);

  const snippet = JSON.stringify(
    {
      observal: {
        agent: agentName,
        registry: "https://registry.observal.dev",
      },
    },
    null,
    2,
  );

  const handleCopy = useCallback(() => {
    copyToClipboard(snippet);
    setCopied(true);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  }, [snippet]);

  return (
    <div className="relative rounded-md border border-border bg-surface-sunken">
      <Button
        variant="ghost"
        size="icon"
        className="absolute top-2 right-2 h-7 w-7"
        onClick={handleCopy}
        aria-label="Copy config"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-success" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </Button>
      <pre className="p-4 text-xs font-mono leading-relaxed overflow-x-auto text-foreground/80">
        {snippet}
      </pre>
    </div>
  );
}
