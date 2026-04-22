"use client";

import { use } from "react";
import { useSearchParams } from "next/navigation";
import { useState, useCallback, useSyncExternalStore } from "react";
import { Star, Check, Copy, ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { useRegistryItem, useFeedback, useFeedbackSummary, useRegistryMetrics } from "@/hooks/use-api";
import type { RegistryType } from "@/lib/api";
import type { FeedbackItem, RegistryItem } from "@/lib/types";
import { copyToClipboard } from "@/lib/utils";
import Link from "next/link";
import { ReviewForm } from "@/components/registry/review-form";
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
  const singularType = type.replace(/s$/, "");
  const { data: item, isLoading, isError, error, refetch } = useRegistryItem(type, id);
  const { data: feedbackItems, refetch: refetchFeedback } = useFeedback(singularType, id);
  const { data: feedbackSummary, refetch: refetchSummary } = useFeedbackSummary(id);
  const { data: rawMetrics } = useRegistryMetrics(type, id);

  const storeSub = useCallback((cb: () => void) => {
    window.addEventListener("storage", cb);
    return () => window.removeEventListener("storage", cb);
  }, []);
  const isAuthenticated = useSyncExternalStore(
    storeSub,
    () => !!localStorage.getItem("observal_access_token"),
    () => false,
  );

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
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-2xl font-display font-bold tracking-tight">{item.name}</h1>
                <Badge variant="outline" className="text-xs">{singularType}</Badge>
                {item.status && <Badge variant={statusVariant(item.status)}>{item.status}</Badge>}
              </div>
              {item.description && (
                <p className="text-sm text-foreground/80 leading-relaxed max-w-2xl">{item.description}</p>
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
              </TabsList>

              <TabsContent value="overview" forceMount className="mt-6 data-[state=inactive]:hidden">
                <div className="space-y-6 w-full min-h-[400px]">
                  <ComponentMetadata item={item} />
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

  const promptText = "prompt_text" in item && item.prompt_text ? String(item.prompt_text) : null;

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
      {promptText && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Prompt Content</h3>
          <div className="rounded-md border border-border bg-muted/20 p-4">
            <pre className="text-xs font-[family-name:var(--font-mono)] whitespace-pre-wrap break-words text-foreground/80 leading-relaxed max-h-[400px] overflow-y-auto">
              {promptText}
            </pre>
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
          <Check className="h-3.5 w-3.5 text-green-500" />
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
