// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { Link, useParams, useSearch } from "@tanstack/react-router";
import { useState, useEffect, useCallback, useSyncExternalStore } from "react";
import { Star, ArrowLeft, History, Loader2, ArrowDownToLine, Archive, ArchiveRestore, AlertTriangle } from "lucide-react";
import {
  useRegistryItem,
  useFeedback,
  useFeedbackSummary,
  useMyFeedback,
  useRegistryMetrics,
  useComponentVersions,
  useComponentVersionDetail,
  useComponentArchive,
  useComponentUnarchive,
  useWhoami,
} from "@/hooks/use-api";
import type { RegistryType } from "@/lib/api";
import type { FeedbackItem, RegistryItem, ComponentVersionSummary } from "@/lib/types";
import { compactNumber } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ReviewForm } from "@/components/registry/review-form";
import { VersionDropdown } from "@/components/registry/version-dropdown";
import { ComponentEditForm } from "@/components/registry/component-edit-form";
import { ComponentInstallCommand } from "@/components/registry/component-install-command";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/layouts/page-header";
import { DetailSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { IdeBadges } from "@/components/registry/ide-badges";
import { CoAuthorInput, type CoAuthor } from "@/components/registry/co-author-input";

function statusVariant(status?: string) {
  if (status === "approved") return "default" as const;
  if (status === "rejected") return "destructive" as const;
  return "secondary" as const;
}

function formatArchiveDate(item: RegistryItem) {
  const value = item.updated_at ?? item.created_at;
  return value ? new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : null;
}

function ArchivedComponentBanner({ item, type, canRestore }: { item: RegistryItem; type: string; canRestore: boolean }) {
  const date = formatArchiveDate(item);

  return (
    <div className="flex items-start justify-between gap-4 rounded-md border border-dark-yellow/30 bg-light-yellow px-4 py-3 text-dark-yellow">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="space-y-1 text-sm">
          <p className="font-medium">
            This {type} was archived{date ? ` on ${date}` : ""}. It is hidden from registry lists.
          </p>
          <p className="text-xs text-dark-yellow/80">
            Installs still work by direct reference, but users will see an archived component warning.
            {canRestore ? " Restore it from the lifecycle panel when it should be discoverable again." : ""}
          </p>
        </div>
      </div>
      <Archive className="mt-0.5 h-4 w-4 shrink-0" />
    </div>
  );
}

export default function ComponentDetailPage() {
  const { componentId: id } = useParams({ from: "/_authed/components/$componentId" });
  const { type: typeParam } = useSearch({ from: "/_authed/components/$componentId" });
  const type = (typeParam ?? "mcps") as RegistryType;
  const singularType = type === "sandboxes" ? "sandbox" : type.replace(/s$/, "");
  const { data: item, isLoading, isError, error, refetch } = useRegistryItem(type, id);
  const { data: feedbackItems, refetch: refetchFeedback } = useFeedback(singularType, id);
  const { data: feedbackSummary, refetch: refetchSummary } = useFeedbackSummary(id);
  const { data: myReview } = useMyFeedback(singularType, id);
  const { data: rawMetrics } = useRegistryMetrics(type, id);
  const { data: versionsData, isLoading: versionsLoading } = useComponentVersions(type, id);
  const [selectedVersion, setSelectedVersion] = useState<string | null>(null);
  const { data: versionDetail } = useComponentVersionDetail(type, id, selectedVersion);
  const { data: whoami } = useWhoami();

  const storeSub = useCallback((cb: () => void) => {
    window.addEventListener("storage", cb);
    return () => window.removeEventListener("storage", cb);
  }, []);
  const isAuthenticated = useSyncExternalStore(
    storeSub,
    () => !!sessionStorage.getItem("observal_access_token"),
    () => false,
  );
  const canEdit = isAuthenticated && (item?.user_permission === "owner");
  const canTransferOwnership = !!(whoami?.id && item?.submitted_by && whoami.id === String(item.submitted_by));

  // Co-authors
  const [coAuthors, setCoAuthors] = useState<CoAuthor[]>([]);
  useEffect(() => {
    const token = sessionStorage.getItem("observal_access_token");
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    fetch(`/api/v1/${type}/${id}/co-authors`, { headers })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setCoAuthors(data))
      .catch(() => {});
  }, [type, id]);

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
            <Link to="/components">
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
            {item.status === "archived" && (
              <ArchivedComponentBanner item={item} type={singularType} canRestore={canEdit} />
            )}

            {/* Header */}
            <div className="space-y-2">
              <div className="flex items-start gap-3 flex-wrap">
                <h1 className="text-2xl font-display font-bold tracking-tight">{item.name}</h1>
                <Badge variant="outline" className="text-xs">{singularType}</Badge>
                {item.status && (
                  <Badge
                    variant={statusVariant(item.status)}
                    className={item.status === "archived" ? "bg-light-yellow text-dark-yellow" : undefined}
                  >
                    {item.status}
                  </Badge>
                )}
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

            {/* Grid: Main + Sidebar */}
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-8 items-start">
            {/* Tabs */}
            <Tabs defaultValue="overview" className="min-w-0">
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
                <TabsTrigger value="versions">
                  Versions
                  {versions.length > 0 && (
                    <span className="ml-1.5 text-[10px] bg-muted px-1.5 py-0.5 rounded-full">
                      {versions.length}
                    </span>
                  )}
                </TabsTrigger>
                {canEdit && <TabsTrigger value="edit">Edit</TabsTrigger>}
              </TabsList>

              <TabsContent value="overview" forceMount className="mt-6 data-[state=inactive]:hidden">
                <div className="space-y-6 w-full min-h-[400px]">
                  <ComponentMetadata item={effectiveItem ?? item} />
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
                    {feedbackItems
                      .filter((fb: FeedbackItem) => !myReview || fb.id !== myReview.id)
                      .map((fb: FeedbackItem) => (
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

              {canEdit && (
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

            {/* Sidebar */}
            <aside className="hidden lg:block space-y-5">
              {/* Install command (MCPs, Skills, Hooks only) */}
              {(singularType === "mcp" || singularType === "skill" || singularType === "hook") && (
                <ComponentInstallCommand componentType={singularType} componentName={item.name} />
              )}

              {/* Stats */}
              <div className="border border-border rounded-md p-4 space-y-4">
                <h3 className="text-xs font-semibold font-display uppercase tracking-wider text-muted-foreground">
                  Stats
                </h3>
                <div className="space-y-3">
                  {effectiveVersion && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Version</span>
                      <span className="font-mono font-medium">{effectiveVersion}</span>
                    </div>
                  )}
                  {item.created_at && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Created</span>
                      <span className="font-mono font-medium text-xs">{new Date(item.created_at).toLocaleDateString()}</span>
                    </div>
                  )}
                  {(item as Record<string, unknown>).download_count != null && (item as Record<string, unknown>).download_count !== 0 && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="inline-flex items-center gap-2 text-muted-foreground">
                        <ArrowDownToLine className="h-3.5 w-3.5" />
                        Downloads
                      </span>
                      <span className="font-mono font-medium">
                        {compactNumber((item as Record<string, unknown>).download_count as number)}
                      </span>
                    </div>
                  )}
                  {metricsEntries.map(([key, val]) => (
                    <div key={key} className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground capitalize">{key.replace(/_/g, " ")}</span>
                      <span className="font-mono font-medium">{val}</span>
                    </div>
                  ))}
                  {avgRating != null && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="inline-flex items-center gap-2 text-muted-foreground">
                        <Star className="h-3.5 w-3.5" />
                        Rating
                      </span>
                      <span className="font-mono font-medium">
                        {avgRating.toFixed(1)}{" "}
                        <span className="text-xs text-muted-foreground font-normal">({totalReviews})</span>
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* IDE Compatibility */}
              {Array.isArray(item.supported_ides) && (item.supported_ides as string[]).length > 0 && (
                <div className="border border-border rounded-md p-4 space-y-3">
                  <h3 className="text-xs font-semibold font-display uppercase tracking-wider text-muted-foreground">
                    IDE Compatibility
                  </h3>
                  <IdeBadges supportedIdes={item.supported_ides as string[]} max={7} />
                </div>
              )}

              {/* Publisher */}
              {!!item.owner && (
                <div className="border border-border rounded-md p-4 space-y-2">
                  <h3 className="text-xs font-semibold font-display uppercase tracking-wider text-muted-foreground">
                    Publisher
                  </h3>
                  <p className="text-sm">{String(item.owner)}</p>
                </div>
              )}

              {(canEdit || coAuthors.length > 0) && (
                <div className="border border-border rounded-md p-4 space-y-4">
                  <h3 className="text-xs font-semibold font-display uppercase tracking-wider text-muted-foreground">
                    Danger zone
                  </h3>

                  <CoAuthorInput
                    entityType={type}
                    entityId={id}
                    coAuthors={coAuthors}
                    onChange={setCoAuthors}
                    canManage={canEdit}
                    canTransferOwnership={canTransferOwnership}
                    onTransferOwnership={() => refetch()}
                  />

                  {canEdit && (
                    <div className="border-t border-border pt-3 space-y-2">
                      <p className="text-sm font-medium">Lifecycle</p>
                      <ComponentArchiveButton type={type} item={item} onSuccess={() => refetch()} />
                    </div>
                  )}
                </div>
              )}
            </aside>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function ComponentArchiveButton({
  type,
  item,
  onSuccess,
}: {
  type: RegistryType;
  item: RegistryItem;
  onSuccess: () => void;
}) {
  const [open, setOpen] = useState(false);
  const archiveMutation = useComponentArchive(type);
  const unarchiveMutation = useComponentUnarchive(type);
  const isArchived = item.status === "archived";
  const isBusy = archiveMutation.isPending || unarchiveMutation.isPending;

  function submit() {
    const mutation = isArchived ? unarchiveMutation : archiveMutation;
    mutation.mutate(item.id, {
      onSuccess: () => {
        setOpen(false);
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
        onClick={() => setOpen(true)}
        disabled={isBusy}
      >
        {isArchived ? <ArchiveRestore className="mr-1 h-3.5 w-3.5" /> : <Archive className="mr-1 h-3.5 w-3.5" />}
        {isArchived ? "Restore" : "Archive"}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{isArchived ? `Restore ${item.name}?` : `Archive ${item.name}?`}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {isArchived
              ? "This makes the component discoverable again and removes archived install warnings."
              : "Archived components stop appearing in registry lists and insight suggestions. Direct installs and agent pulls still work, but users will see a warning."}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
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

function ComponentMetadata({ item }: { item: RegistryItem }) {
  const fields: { label: string; value: string; mono?: boolean; href?: string }[] = [];
  if ("git_url" in item && item.git_url != null) fields.push({ label: "Source", value: String(item.git_url), href: String(item.git_url) });
  if ("command" in item && item.command != null) fields.push({ label: "Command", value: String(item.command), mono: true });
  if ("url" in item && item.url != null) fields.push({ label: "URL", value: String(item.url), href: String(item.url) });
  if ("transport" in item && item.transport != null) fields.push({ label: "Transport", value: String(item.transport) });
  if ("framework" in item && item.framework != null) fields.push({ label: "Framework", value: String(item.framework) });
  if ("docker_image" in item && item.docker_image != null) fields.push({ label: "Docker Image", value: String(item.docker_image), mono: true });
  if ("hook_type" in item && item.hook_type != null) fields.push({ label: "Hook Type", value: String(item.hook_type) });
  if ("trigger_event" in item && item.trigger_event != null) fields.push({ label: "Trigger Event", value: String(item.trigger_event) });
  if ("runtime" in item && item.runtime != null) fields.push({ label: "Runtime", value: String(item.runtime) });
  if ("image" in item && item.image != null) fields.push({ label: "Image", value: String(item.image), mono: true });

  const setupInstructions = "setup_instructions" in item && item.setup_instructions ? String(item.setup_instructions) : null;
  const changelog = "changelog" in item && item.changelog ? String(item.changelog) : null;
  const skillMd = "skill_md_content" in item && item.skill_md_content ? String(item.skill_md_content) : null;
  const promptTemplate = "template" in item && item.template ? String(item.template) : null;
  const promptText = "prompt_text" in item && item.prompt_text ? String(item.prompt_text) : null;
  const markdownContent = skillMd || promptTemplate || promptText;
  const envVars = "environment_variables" in item && Array.isArray(item.environment_variables) ? item.environment_variables as { name: string; description?: string; required?: boolean }[] : [];

  const hasContent = fields.length > 0 || markdownContent || setupInstructions || changelog || envVars.length > 0;

  if (!hasContent) {
    return (
      <div className="rounded-md border border-dashed border-border p-8 text-center">
        <p className="text-sm text-muted-foreground">No additional details available for this component.</p>
      </div>
    );
  }

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
      {envVars.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Environment Variables</h3>
          <div className="rounded-md border border-border divide-y divide-border">
            {envVars.map((ev) => (
              <div key={ev.name} className="px-3 py-2 flex items-center justify-between text-sm">
                <code className="font-mono text-xs">{ev.name}</code>
                <div className="flex items-center gap-2">
                  {ev.description && <span className="text-xs text-muted-foreground">{ev.description}</span>}
                  {ev.required && <Badge variant="secondary" className="text-[10px]">required</Badge>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {setupInstructions && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Setup Instructions</h3>
          <div className="rounded-md border border-border bg-muted/20 p-4 overflow-y-auto max-h-[400px]">
            <div className="prose prose-sm dark:prose-invert max-w-none text-foreground/90 leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{setupInstructions}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}
      {markdownContent && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {skillMd ? "Skill File" : "Prompt Template"}
          </h3>
          <div className="rounded-md border border-border bg-muted/20 p-4 overflow-y-auto max-h-[360px]">
            <div className="prose prose-sm dark:prose-invert max-w-none text-foreground/90 leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdownContent}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}
      {changelog && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Changelog</h3>
          <div className="rounded-md border border-border bg-muted/20 p-4 overflow-y-auto max-h-[300px]">
            <div className="prose prose-sm dark:prose-invert max-w-none text-foreground/90 leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{changelog}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}
    </>
  );
}


