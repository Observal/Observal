"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowDownToLine, Puzzle, Star, Check, Copy, Terminal } from "lucide-react";
import { useState, useCallback } from "react";
import { toast } from "sonner";
import { useRegistryItem, useAgentDownloads } from "@/hooks/use-api";
import { PullCommand } from "@/components/registry/pull-command";
import { StatusBadge } from "@/components/registry/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/layouts/page-header";
import { DetailSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { compactNumber } from "@/lib/utils";

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

  const a = agent as any;
  const components = a?.component_links ?? a?.mcp_links ?? [];
  const goalTemplate = a?.goal_template;
  const agentName = a?.name ?? id.slice(0, 8);
  const totalDownloads = downloadData?.total ?? a?.downloads;

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

      <div className="p-6 lg:p-8 max-w-[1200px]">
        {isLoading ? (
          <DetailSkeleton />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : !agent ? (
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

              {/* Stats row (mobile only -- desktop shows in sidebar) */}
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
                  <TabsTrigger value="install">Install</TabsTrigger>
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
                        (sec: any, i: number) => (
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
                  {components.length === 0 ? (
                    <EmptyState
                      icon={Puzzle}
                      title="No components linked"
                      description="This agent does not have any linked MCP servers or components."
                    />
                  ) : (
                    <div className="space-y-2">
                      {components.map((comp: any, i: number) => {
                        const compName =
                          comp.mcp_name ??
                          comp.component_name ??
                          comp.name ??
                          "-";
                        const compType =
                          comp.component_type ?? "mcp";
                        const compId =
                          comp.component_id ?? comp.mcp_id;
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
                    <ConfigSnippet agentName={a.name} agentId={id} />
                  </div>
                </TabsContent>
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
  agentId,
}: {
  agentName: string;
  agentId: string;
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
