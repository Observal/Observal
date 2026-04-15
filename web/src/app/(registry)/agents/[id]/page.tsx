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
} from "lucide-react";
import { useState, useCallback } from "react";
import { toast } from "sonner";
import {
  useRegistryItem,
  useAgentDownloads,
  useFeedback,
  useFeedbackSummary,
  useEvalAggregate,
} from "@/hooks/use-api";
import { registry, getUserRole } from "@/lib/api";
import { hasMinRole } from "@/hooks/use-role-guard";
import type { FeedbackItem } from "@/lib/types";
import { PullCommand } from "@/components/registry/pull-command";
import { StatusBadge } from "@/components/registry/status-badge";
import { ReviewForm } from "@/components/registry/review-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/layouts/page-header";
import { DetailSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { compactNumber } from "@/lib/utils";

interface AgentDetail {
  name: string;
  status?: string;
  version?: string;
  owner?: string;
  description?: string;
  prompt?: string;
  model_name?: string;
  download_count?: number;
  component_links?: ComponentLink[];
  mcp_links?: ComponentLink[];
  goal_template?: {
    description?: string;
    sections?: { name: string; description?: string }[];
  };
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
          <div className="space-y-2">
            {Object.entries(dims).map(([dim, score]) => (
              <div key={dim} className="flex items-center gap-3">
                <span className="text-xs text-muted-foreground w-32 shrink-0 truncate">{dim}</span>
                <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary rounded-full transition-all"
                    style={{ width: `${Math.min(Number(score) * 10, 100)}%` }}
                  />
                </div>
                <span className="text-xs font-mono w-10 text-right">{Number(score).toFixed(1)}</span>
              </div>
            ))}
          </div>
          {aggregate.weakest_dimension && (
            <p className="text-xs text-muted-foreground">
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

  const isAuthenticated =
    typeof window !== "undefined" &&
    !!localStorage.getItem("observal_access_token");

  const isAdmin =
    typeof window !== "undefined" &&
    hasMinRole(getUserRole(), "admin");

  const a = agent as unknown as AgentDetail | undefined;
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
          !isLoading && a ? <ExportButton agentId={id} /> : undefined
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
                  {a.version && (
                    <Badge variant="secondary" className="text-xs">
                      {a.version}
                    </Badge>
                  )}
                </div>

                {a.owner && (
                  <p className="text-sm text-muted-foreground">{a.owner}</p>
                )}

                {a.description && (
                  <p className="text-sm text-foreground/80 leading-relaxed max-w-2xl">
                    {a.description}
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
                  {isAdmin && <TabsTrigger value="analytics">Analytics</TabsTrigger>}
                </TabsList>

                <TabsContent value="overview" className="space-y-6 mt-6">
                  {a.description && (
                    <div className="space-y-2">
                      <h3 className="text-sm font-semibold font-display">
                        About
                      </h3>
                      <p className="text-sm text-muted-foreground leading-relaxed">
                        {a.description}
                      </p>
                    </div>
                  )}

                  {a.model_name && (
                    <div className="space-y-1">
                      <h3 className="text-sm font-semibold font-display">
                        Model
                      </h3>
                      <p className="text-sm text-muted-foreground font-mono">
                        {a.model_name}
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

                  {!a.description && !goalTemplate && (
                    <p className="text-sm text-muted-foreground">
                      No additional details provided for this agent.
                    </p>
                  )}
                </TabsContent>

                <TabsContent value="components" className="mt-6">
                  <div className="min-h-[300px]">
                  {components.length === 0 ? (
                    a.prompt ? (
                      <div className="space-y-3">
                        <p className="text-xs text-muted-foreground">
                          This agent was registered via scan and uses an inline system prompt instead of linked components.
                        </p>
                        <div className="rounded-md border border-border bg-muted/20 p-4">
                          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">System Prompt</h4>
                          <pre className="text-xs font-[family-name:var(--font-mono)] whitespace-pre-wrap break-words text-foreground/80 leading-relaxed max-h-[400px] overflow-y-auto">
                            {String(a.prompt)}
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
                  {a.model_name && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Model</span>
                      <span className="font-mono text-xs truncate max-w-[140px]">
                        {a.model_name}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {a.owner && (
                <div className="border border-border rounded-md p-4 space-y-2">
                  <h3 className="text-xs font-semibold font-display uppercase tracking-wider text-muted-foreground">
                    Publisher
                  </h3>
                  <p className="text-sm">{a.owner}</p>
                </div>
              )}
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
    navigator.clipboard.writeText(snippet);
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
