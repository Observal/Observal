// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { use } from "react";
import { useSearchParams } from "next/navigation";
import { useState, useCallback, useSyncExternalStore } from "react";
import { Star, Check, Copy, ArrowLeft, History, Loader2 } from "lucide-react";
import { toast } from "sonner";
import {
  useRegistryItem,
  useFeedback,
  useFeedbackSummary,
  useRegistryMetrics,
  useComponentVersions,
  useComponentVersionDetail,
} from "@/hooks/use-api";
import type { RegistryType } from "@/lib/api";
import type { FeedbackItem, RegistryItem, ComponentVersionSummary } from "@/lib/types";
import { copyToClipboard } from "@/lib/utils";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ReviewForm } from "@/components/registry/review-form";
import { VersionDropdown } from "@/components/registry/version-dropdown";
import { ComponentEditForm } from "@/components/registry/component-edit-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/layouts/page-header";
import { DetailSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

function statusVariant(status?: string) {
  if (status === "approved") return "default" as const;
  if (status === "rejected") return "destructive" as const;
  return "secondary" as const;
}

export default function ComponentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const searchParams = useSearchParams();
  const type = (searchParams.get("type") ?? "mcps") as RegistryType;
  const singularType = type === "sandboxes" ? "sandbox" : type.replace(/s$/, "");
  const { data: item, isLoading, isError, error, refetch } = useRegistryItem(type, id);
  const { data: feedbackItems, refetch: refetchFeedback } = useFeedback(singularType, id);
  const { data: feedbackSummary, refetch: refetchSummary } = useFeedbackSummary(id);
  const { data: rawMetrics } = useRegistryMetrics(type, id);
  const { data: versionsData, isLoading: versionsLoading } = useComponentVersions(type, id);
  const [selectedVersion, setSelectedVersion] = useState<string | null>(null);
  const { data: versionDetail } = useComponentVersionDetail(type, id, selectedVersion);

  const storeSub = useCallback((cb: () => void) => {
    window.addEventListener("storage", cb);
    return () => window.removeEventListener("storage", cb);
  }, []);
  const isAuthenticated = useSyncExternalStore(
    storeSub,
    () => !!sessionStorage.getItem("observal_access_token"),
    () => false,
  );

  const versions = versionsData?.items ?? [];
  // VersionDropdown expects AgentVersionSummary shape; ComponentVersionSummary is compatible
  const versionsForDropdown = versions.filter((v) => v.status === "approved") as unknown as import("@/lib/types").AgentVersionSummary[];
  const latestApprovedVersion = versions.find((v) => v.status === "approved")?.version;
  const effectiveVersion = selectedVersion ?? latestApprovedVersion ?? (item?.version as string | undefined);
  // Overlay version-specific description when a version is selected
  const effectiveItem: RegistryItem | undefined = item
    ? versionDetail
      ? { ...item, ...(versionDetail as unknown as RegistryItem) }
      : item
    : undefined;

  const componentName = item?.name ?? id.slice(0, 8);
  const avgRating = feedbackSummary?.average_rating;
  const totalReviews = feedbackSummary?.total_reviews ?? 0;
  const metricsEntries: [string, string][] = rawMetrics && typeof rawMetrics === "object"
    ? Object.entries(rawMetrics as Record<string, unknown>).map(([k, v]) => [k, typeof v === "number" ? v.toLocaleString() : String(v ?? "")])
    : [];

  return (
    <>
      <PageHeader
        title={isLoading ? "Component" : componentName}
        breadcrumbs={[
          { label: "Registry", href: "/" },
          { label: "Components", href: "/components" },
          { label: isLoading ? "..." : componentName },
        ]}
        actionButtonsLeft={
          <Button variant="ghost" size="sm" className="h-7 px-2 gap-1 text-muted-foreground" asChild>
            <Link href="/components">
              <ArrowLeft className="h-3.5 w-3.5" />
              <span className="text-xs">Back</span>
            </Link>
          </Button>
        }
      />
      <div className="p-6 w-full mx-auto space-y-6">
        {isLoading ? (
          <DetailSkeleton />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : !item ? (
          <ErrorState message="Component not found" />
        ) : (
          <div className="animate-in space-y-6">
            {/* Header */}
            <div className="space-y-2">
              <div className="flex items-start gap-3 flex-wrap">
                <h1 className="text-2xl font-display font-bold tracking-tight">{item.name}</h1>
                <Badge variant="outline" className="text-xs">{singularType}</Badge>
                {item.status && <Badge variant={statusVariant(item.status)}>{item.status}</Badge>}
                {versionsForDropdown.length > 0 ? (
                  <VersionDropdown
                    versions={versionsForDropdown}
                    currentVersion={effectiveVersion ?? ""}
                    onSelect={setSelectedVersion}
                  />
                ) : effectiveVersion ? (
                  <Badge variant="secondary" className="text-xs">v{effectiveVersion}</Badge>
                ) : null}
              </div>
              {effectiveItem?.description && (
                <p className="text-sm text-foreground/80 leading-relaxed max-w-2xl">{effectiveItem.description as string}</p>
              )}
              {avgRating != null && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <div className="flex items-center gap-0.5">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <Star
                        key={i}
                        className={`h-3.5 w-3.5 ${i < Math.round(avgRating) ? "fill-current text-amber-500" : "text-muted-foreground/30"}`}
                      />
                    ))}
                  </div>
                  <span className="text-xs">{avgRating.toFixed(1)} ({totalReviews} review{totalReviews !== 1 ? "s" : ""})</span>
                </div>
              )}
            </div>

            {/* Tabs */}
            <Tabs defaultValue="overview">
              <TabsList>
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="reviews">
                  Reviews
                  {totalReviews > 0 && (
                    <span className="ml-1.5 text-[10px] bg-muted px-1.5 py-0.5 rounded-full">
                      {totalReviews}
                    </span>
                  )}
                </TabsTrigger>
                <TabsTrigger value="install">Add to Agent</TabsTrigger>
                <TabsTrigger value="versions">
                  Versions
                  {versions.length > 0 && (
                    <span className="ml-1.5 text-[10px] bg-muted px-1.5 py-0.5 rounded-full">
                      {versions.length}
                    </span>
                  )}
                </TabsTrigger>
                {isAuthenticated && <TabsTrigger value="edit">Edit</TabsTrigger>}
              </TabsList>

              <TabsContent value="overview" forceMount className="mt-6 data-[state=inactive]:hidden">
                <div className="space-y-6 w-full min-h-[400px]">
                  <ComponentMetadata item={effectiveItem ?? item} />
                  <MetricsSection entries={metricsEntries} />
                </div>
              </TabsContent>

              <TabsContent value="reviews" forceMount className="mt-6 data-[state=inactive]:hidden">
                <div className="space-y-6 w-full min-h-[400px]">
                {isAuthenticated && (
                  <>
                    <ReviewForm
                      listingId={id}
                      listingType={singularType}
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
                        ? `Be the first to review this ${singularType}.`
                        : "Log in to leave a review."
                    }
                  />
                ) : (
                  <div className="space-y-4">
                    {feedbackItems.map((fb: FeedbackItem) => (
                      <div key={fb.id} className="rounded-md border border-border p-4 space-y-2">
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
                            {fb.created_at && ` · ${new Date(fb.created_at).toLocaleDateString()}`}
                          </span>
                        </div>
                        {fb.comment && (
                          <p className="text-sm text-muted-foreground leading-relaxed">{fb.comment}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                </div>
              </TabsContent>

              <TabsContent value="install" forceMount className="mt-6 data-[state=inactive]:hidden">
                <div className="space-y-6 w-full min-h-[400px]">
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold font-display">Add to Agent</h3>
                  <p className="text-xs text-muted-foreground">
                    Add this {singularType} to a local agent configuration. Run this inside a directory with an <code className="font-mono text-foreground/70">observal-agent.yaml</code> file.
                  </p>
                </div>
                <InstallSnippet type={singularType} name={item.name} />

                {"git_url" in item && item.git_url ? (
                  <>
                    <Separator />
                    <div className="space-y-2">
                      <h3 className="text-sm font-semibold font-display">From Source</h3>
                      <p className="text-xs text-muted-foreground">
                        Clone directly from the source repository.
                      </p>
                      <code className="block rounded-md border border-border bg-muted/20 p-3 text-xs font-[family-name:var(--font-mono)]">
                        git clone {String(item.git_url)}
                      </code>
                    </div>
                  </>
                ) : null}
                </div>
              </TabsContent>

              <TabsContent value="versions" forceMount className="mt-6 data-[state=inactive]:hidden">
                <div className="space-y-4 w-full min-h-[400px]">
                  {versionsLoading ? (
                    <div className="flex items-center justify-center py-12">
                      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                    </div>
                  ) : versions.length === 0 ? (
                    <EmptyState
                      icon={History}
                      title="No versions yet"
                      description="Release a new version from the Edit tab to start tracking version history."
                    />
                  ) : (
                    <div className="space-y-2">
                      {versions.map((v: ComponentVersionSummary) => (
                        <div
                          key={v.id}
                          className="flex items-start justify-between gap-4 rounded-md border border-border px-4 py-3"
                        >
                          <div className="space-y-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-mono text-sm font-medium">v{v.version}</span>
                              <Badge variant={statusVariant(v.status)} className="text-[10px]">
                                {v.status}
                              </Badge>
                            </div>
                            {v.description && (
                              <p className="text-xs text-muted-foreground truncate max-w-xl">{v.description}</p>
                            )}
                            {v.changelog && (
                              <p className="text-xs text-muted-foreground/70 italic truncate max-w-xl">{v.changelog}</p>
                            )}
                          </div>
                          <div className="shrink-0 text-right space-y-0.5">
                            {v.released_by && (
                              <p className="text-xs text-muted-foreground">{v.released_by}</p>
                            )}
                            {v.released_at && (
                              <p className="text-xs text-muted-foreground">
                                {new Date(v.released_at).toLocaleDateString()}
                              </p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </TabsContent>

              {isAuthenticated && (
                <TabsContent value="edit" forceMount className="mt-6 data-[state=inactive]:hidden">
                  <div className="w-full min-h-[400px]">
                    <ComponentEditForm
                      listingId={id}
                      type={type}
                      currentVersion={effectiveVersion ?? "1.0.0"}
                      item={effectiveItem ?? item}
                      onSuccess={() => refetch()}
                    />
                  </div>
                </TabsContent>
              )}
            </Tabs>
          </div>
        )}
      </div>
    </>
  );
}

function ComponentMetadata({ item }: { item: RegistryItem }) {
  const fields: { label: string; value: string; mono?: boolean; href?: string }[] = [];
  if ("version" in item && item.version != null) fields.push({ label: "Version", value: String(item.version), mono: true });
  if ("git_url" in item && item.git_url != null) fields.push({ label: "Source", value: String(item.git_url), href: String(item.git_url) });
  if ("transport" in item && item.transport != null) fields.push({ label: "Transport", value: String(item.transport) });
  if (item.created_at) fields.push({ label: "Created", value: new Date(item.created_at).toLocaleDateString() });
  if ("owner" in item && item.owner != null) fields.push({ label: "Owner", value: String(item.owner) });
  if ("hook_type" in item && item.hook_type != null) fields.push({ label: "Hook Type", value: String(item.hook_type) });
  if ("trigger_event" in item && item.trigger_event != null) fields.push({ label: "Trigger Event", value: String(item.trigger_event) });
  if ("runtime" in item && item.runtime != null) fields.push({ label: "Runtime", value: String(item.runtime) });
  if ("image" in item && item.image != null) fields.push({ label: "Image", value: String(item.image), mono: true });

  const skillMd = "skill_md_content" in item && item.skill_md_content ? String(item.skill_md_content) : null;
  const promptTemplate = "template" in item && item.template ? String(item.template) : null;
  const promptText = "prompt_text" in item && item.prompt_text ? String(item.prompt_text) : null;
  const markdownContent = skillMd || promptTemplate || promptText;

  return (
    <>
      {fields.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          {fields.map((f) => (
            <div key={f.label} className="rounded-md border border-border p-3 space-y-1">
              <span className="text-xs text-muted-foreground">{f.label}</span>
              {f.href ? (
                <p><a href={f.href} className="text-sm text-primary hover:underline break-all" target="_blank" rel="noopener noreferrer">{f.value}</a></p>
              ) : (
                <p className={f.mono ? "font-mono text-sm" : "text-sm"}>{f.value}</p>
              )}
            </div>
          ))}
        </div>
      )}
      {markdownContent && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {skillMd ? "Skill File" : "Prompt Template"}
          </h3>
          <div className="rounded-md border border-border bg-muted/20 p-4 overflow-y-auto max-h-[600px]">
            <div className="prose prose-sm dark:prose-invert max-w-none text-foreground/90 leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdownContent}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function MetricsSection({ entries }: { entries: [string, string][] }) {
  if (entries.length === 0) return null;
  return (
    <div className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Usage</h3>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {entries.map(([key, display]) => (
          <div key={key} className="rounded-md border border-border p-3 space-y-1">
            <span className="text-xs text-muted-foreground">{key.replace(/_/g, " ")}</span>
            <p className="text-lg font-mono font-bold">{display}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function InstallSnippet({ type, name }: { type: string; name: string }) {
  const [copied, setCopied] = useState(false);
  const cmd = `observal agent add ${type} ${name}`;

  const handleCopy = useCallback(() => {
    copyToClipboard(cmd);
    setCopied(true);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  }, [cmd]);

  return (
    <div className="relative rounded-md border border-border bg-surface-sunken">
      <Button
        variant="ghost"
        size="icon"
        className="absolute top-2 right-2 h-7 w-7"
        onClick={handleCopy}
        aria-label="Copy command"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-success" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </Button>
      <pre className="p-4 text-xs font-mono leading-relaxed overflow-x-auto text-foreground/80">
        $ {cmd}
      </pre>
    </div>
  );
}
