// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { useState, useCallback, useMemo } from "react";
import { ArrowRight, Plus, Minus, RefreshCw } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import yaml from "js-yaml";
import { YamlDiffView } from "./yaml-diff-view";
import { useAgentVersions, useAgentVersionDetail, useComponentVersions, useComponentVersionDetail, useRegistryItem } from "@/hooks/use-api";
import { registry } from "@/lib/api";
import type { RegistryType } from "@/lib/api";
import type { ReviewItem, ComponentChange } from "@/lib/types";

function pluralizeType(type: string): string {
  if (type === "agent") return "agents";
  return `${type}s`;
}

function semverBumpType(from: string, to: string): "major" | "minor" | "patch" | null {
  const parse = (v: string) => v.replace(/^v/, "").split(".").map(Number);
  const [fa, fb, fc] = parse(from);
  const [ta, tb, tc] = parse(to);
  if (isNaN(fa) || isNaN(ta)) return null;
  if (ta > fa) return "major";
  if (tb > fb) return "minor";
  if (tc > fc) return "patch";
  return null;
}

const bumpBadgeClasses: Record<string, string> = {
  major: "bg-destructive/10 text-destructive border-destructive/25",
  minor: "bg-warning/10 text-warning border-warning/25",
  patch: "bg-success/10 text-success border-success/25",
};

const changeBadgeClasses: Record<string, string> = {
  added: "bg-success/10 text-success border-success/25",
  removed: "bg-destructive/10 text-destructive border-destructive/25",
  updated: "bg-warning/10 text-warning border-warning/25",
};

const changeIcon: Record<string, React.ReactNode> = {
  added: <Plus className="h-3 w-3" />,
  removed: <Minus className="h-3 w-3" />,
  updated: <RefreshCw className="h-3 w-3" />,
};

function ComponentChangesList({ changes }: { changes: ComponentChange[] }) {
  if (!changes.length) return null;

  return (
    <div className="space-y-2">
      {changes.map((c, i) => (
        <div
          key={i}
          className="flex items-start gap-2 text-xs py-1.5 px-2 rounded bg-muted/40"
        >
          <Badge
            variant="outline"
            className={`text-[10px] shrink-0 flex items-center gap-1 ${changeBadgeClasses[c.change] ?? ""}`}
          >
            {changeIcon[c.change]}
            {c.change}
          </Badge>
          <div className="min-w-0 flex-1">
            <span className="font-medium truncate block">{c.name}</span>
            <span className="text-muted-foreground">{c.type}</span>
            {c.from && c.to && (
              <span className="ml-1 text-muted-foreground">
                {c.from} <ArrowRight className="h-2.5 w-2.5 inline" /> {c.to}
              </span>
            )}
            {c.version && !c.from && (
              <span className="ml-1 text-muted-foreground">v{c.version}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

const DIFF_METADATA_FIELDS = new Set([
  "id", "listing_id", "download_count", "released_by", "released_at",
  "created_at", "status", "rejection_reason", "is_prerelease", "promoted_from",
]);

function stripMeta(obj: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(obj).filter(([k, v]) => !DIFF_METADATA_FIELDS.has(k) && v !== null && v !== undefined && v !== ""),
  );
}

function toReviewYaml(obj: Record<string, unknown>): string {
  try {
    return yaml.dump(stripMeta(obj), { lineWidth: 120, indent: 2, noRefs: true }).trimEnd();
  } catch {
    return JSON.stringify(stripMeta(obj), null, 2);
  }
}


const COMPONENT_CONTENT_KEYS = ["template", "skill_md_content", "handler_config", "input_schema", "output_schema", "source_url", "git_url", "config_json", "event", "execution_mode", "task_type", "slash_command"];

// For non-agent component submissions — include all content fields
const COMPONENT_SNAPSHOT_META = new Set([
  "id", "listing_id", "download_count", "released_by", "released_at",
  "created_at", "status", "rejection_reason", "is_prerelease",
]);

function buildComponentYaml(detail: Record<string, unknown>): string {
  const obj = Object.fromEntries(
    Object.entries(detail).filter(([k, v]) =>
      !COMPONENT_SNAPSHOT_META.has(k) && v !== null && v !== undefined && v !== "" &&
      !(Array.isArray(v) && (v as unknown[]).length === 0) &&
      !(typeof v === "object" && !Array.isArray(v) && Object.keys(v as object).length === 0)
    )
  );
  try {
    return yaml.dump(obj, { lineWidth: 120, indent: 2, noRefs: true }).trimEnd();
  } catch {
    return JSON.stringify(obj, null, 2);
  }
}


function buildCleanYaml(detail: Record<string, unknown>, componentDataMap?: Map<string, Record<string, unknown>>): string {
  const comps = (detail.components as Array<Record<string, unknown>> | undefined) ?? [];
  const obj: Record<string, unknown> = {};
  if (detail.version) obj.version = detail.version;
  if (detail.description) obj.description = detail.description;
  if (detail.prompt) obj.prompt = detail.prompt;
  if (detail.model_name) obj.model_name = detail.model_name;
  const byIde = detail.models_by_ide as Record<string, unknown> | undefined;
  if (byIde && Object.keys(byIde).length) obj.models_by_ide = byIde;
  const ides = detail.supported_ides as string[] | undefined;
  if (ides?.length) obj.supported_ides = ides;
  if (comps.length) {
    obj.components = comps.map((c) => {
      const cached = componentDataMap?.get(String(c.component_id ?? "")) as Record<string, unknown> | undefined;
      const merged = cached ? { ...cached, ...c } : c;
      const entry: Record<string, unknown> = {};
      if (merged.component_type) entry.type = merged.component_type;
      entry.name = merged.name || merged.component_name || c.name || c.component_name || "(pending)";
      const desc = merged.description ?? merged.component_description;
      if (desc) entry.description = desc;
      if (merged.version) entry.version = merged.version;
      for (const k of COMPONENT_CONTENT_KEYS) {
        if (merged[k]) entry[k] = merged[k];
      }
      return entry;
    });
  }
  try {
    return yaml.dump(obj, { lineWidth: 120, indent: 2, noRefs: true }).trimEnd();
  } catch {
    return JSON.stringify(obj, null, 2);
  }
}


const CONTENT_KEYS = ["template", "skill_md_content", "handler_config", "input_schema", "output_schema", "source_url", "config_json"] as const;
const TYPE_MAP: Record<string, string> = { mcp: "mcps", skill: "skills", hook: "hooks", prompt: "prompts", sandbox: "sandboxes" };

function LinkedComponentDetail({ componentType, componentId, onPendingClick, isPending }: { componentType: string; componentId: string; onPendingClick?: (id: string, type: string) => void; isPending?: boolean }) {
  const registryType = (TYPE_MAP[componentType] ?? `${componentType}s`) as import("@/lib/api").RegistryType;
  const { data: item } = useRegistryItem(registryType, componentId);
  const name = item?.name ?? componentType;
  const description = item?.description;
  const contentEntries = item
    ? CONTENT_KEYS.flatMap((k) => {
        const v = (item as Record<string, unknown>)[k];
        return v ? [[k, v] as [string, unknown]] : [];
      })
    : [];
  const href = `/components/${componentId}?type=${registryType}`;

  return (
    <div className="rounded border border-border overflow-hidden text-xs">
      <div className="flex items-center gap-2 px-3 py-2 bg-muted/50">
        <Badge variant="outline" className="text-[10px] shrink-0">{componentType}</Badge>
        {isPending && onPendingClick ? (
          <button type="button" onClick={() => onPendingClick(componentId, componentType)} className="font-medium hover:underline text-amber-500 text-left">
            {name}
            <span className="ml-1 text-[9px] opacity-70">(pending)</span>
          </button>
        ) : (
          <Link href={href} className="font-medium hover:underline text-primary">{name}</Link>
        )}
      </div>
      {description && (
        <p className="px-3 py-1.5 text-[11px] text-muted-foreground border-b border-border/50">{description}</p>
      )}
      {contentEntries.length > 0 && (
        <details open className="group">
          <summary className="cursor-pointer select-none px-3 py-1.5 text-[10px] font-medium text-muted-foreground hover:text-foreground list-none flex items-center gap-1">
            <span className="group-open:rotate-90 transition-transform inline-block">▶</span>
            Content
          </summary>
          <pre className="px-3 py-2 text-[11px] font-mono leading-relaxed overflow-auto max-h-60 bg-background border-t border-border/50 break-words whitespace-pre-wrap">
            {contentEntries.map(([k, v]) => k + ":\n" + (typeof v === "string" ? v : yaml.dump(v, { lineWidth: 80, indent: 2 }))).join("\n\n")}
          </pre>
        </details>
      )}
    </div>
  );
}



interface ReviewDiffSheetProps {
  item: ReviewItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApprove: (id: string, type?: string, category?: string) => void;
  onReject: (id: string, reason: string, type?: string) => void;
  onOpenComponentReview?: (id: string, type: string) => void;
}

export function ReviewDiffSheet({
  item,
  open,
  onOpenChange,
  onApprove,
  onReject,
  onOpenComponentReview,
}: ReviewDiffSheetProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-7xl w-[95vw] h-[85vh] flex flex-col p-0 gap-0 overflow-hidden">
        {item ? (
          <DiffDialogBody
            key={item.id}
            item={item}
            onOpenChange={onOpenChange}
            onApprove={onApprove}
            onReject={onReject}
            onOpenComponentReview={onOpenComponentReview}
          />
        ) : (
          <div className="p-6 space-y-4">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-4 w-full" />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DiffDialogBody({
  item,
  onOpenChange,
  onApprove,
  onReject,
  onOpenComponentReview,
}: {
  item: ReviewItem;
  onOpenChange: (open: boolean) => void;
  onApprove: (id: string, type?: string, category?: string) => void;
  onReject: (id: string, reason: string, type?: string) => void;
  onOpenComponentReview?: (id: string, type: string) => void;
}) {
  const [showRejectDialog, setShowRejectDialog] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [approveCategory, setApproveCategory] = useState("");

  const isAgent = item.type === "agent";
  const registryType = !isAgent && item.type ? pluralizeType(item.type) as RegistryType : undefined;

  // Agent versions
  const { data: agentVersionsData, isLoading: agentVersionsLoading } = useAgentVersions(
    isAgent ? item.id : undefined,
  );

  // Component versions
  const { data: compVersionsData, isLoading: compVersionsLoading } = useComponentVersions(
    registryType,
    !isAgent ? item.id : undefined,
  );

  const versionsLoading = isAgent ? agentVersionsLoading : compVersionsLoading;
  const versionsItems = isAgent ? agentVersionsData?.items : compVersionsData?.items;

  // Find the most recent approved version before the pending one.
  // Versions are returned newest-first (created_at DESC), so [0] is the most recent.
  const previousVersion = useMemo(() => {
    if (!versionsItems || !item.version) return undefined;
    const approved = versionsItems.filter(
      (v) => v.status === "approved" && v.version !== item.version,
    );
    return approved[0]?.version;
  }, [versionsItems, item.version]);

  // Agent version detail (current + previous for client-side diff)
  const { data: agentDetail, isLoading: agentDetailLoading } = useAgentVersionDetail(
    isAgent ? item.id : undefined,
    isAgent ? (item.version ?? null) : null,
  );
  const { data: agentPrevDetail } = useAgentVersionDetail(
    isAgent ? item.id : undefined,
    isAgent ? (previousVersion ?? null) : null,
  );

  // Component version detail
  const { data: compDetail, isLoading: compDetailLoading } = useComponentVersionDetail(
    registryType,
    !isAgent ? item.id : undefined,
    !isAgent ? (item.version ?? null) : null,
  );

  // Also fetch previous approved version detail for component diff
  const { data: compPrevDetail } = useComponentVersionDetail(
    registryType,
    !isAgent ? item.id : undefined,
    !isAgent ? (previousVersion ?? null) : null,
  );

  const detailLoading = isAgent ? agentDetailLoading : compDetailLoading;


  const bumpType = useMemo(() => {
    if (!previousVersion || !item.version) return null;
    return semverBumpType(previousVersion, item.version);
  }, [previousVersion, item.version]);

  const componentDiff = useMemo(() => {
    if (isAgent || !compDetail || !compPrevDetail || !previousVersion) return null;
    const prev = buildComponentYaml(compPrevDetail as unknown as Record<string, unknown>);
    const curr = buildComponentYaml(compDetail as unknown as Record<string, unknown>);
    if (prev === curr) return "";
    const prevLines = prev.split("\n");
    const currLines = curr.split("\n");
    const lines: string[] = [`--- v${previousVersion}`, `+++ v${item.version}`];
    const hunks: string[] = [];
    const maxLen = Math.max(prevLines.length, currLines.length);
    let inHunk = false;
    for (let i = 0; i < maxLen; i++) {
      const pl = prevLines[i] ?? "";
      const cl = currLines[i] ?? "";
      if (pl !== cl) {
        if (!inHunk) {
          hunks.push(`@@ -${i + 1} +${i + 1} @@`);
          inHunk = true;
        }
        if (pl) hunks.push(`-${pl}`);
        if (cl) hunks.push(`+${cl}`);
      } else {
        if (inHunk) {
          hunks.push(` ${cl}`);
          inHunk = false;
        }
      }
    }
    return [...lines, ...hunks].join("\n");
  }, [isAgent, compDetail, compPrevDetail, previousVersion, item.version]);

  const handleApprove = useCallback(() => {
    onApprove(item.id, item.type, approveCategory || undefined);
    onOpenChange(false);
  }, [item, onApprove, onOpenChange, approveCategory]);

  const handleRejectConfirm = useCallback(() => {
    if (!rejectReason.trim()) return;
    onReject(item.id, rejectReason, item.type);
    setShowRejectDialog(false);
    setRejectReason("");
    onOpenChange(false);
  }, [rejectReason, item, onReject, onOpenChange]);

  const disableApprove = item.components_ready === false;

  const isLoading = versionsLoading || detailLoading;

  const detail = (isAgent ? agentDetail : compDetail) as Record<string, unknown> | undefined;
  // Prefer version detail fields over the sparse review item fields
  const prompt = (detail?.prompt as string) || item.prompt || "";
  const modelName = (detail?.model_name as string) || item.model_name || "";
  const modelsByIdeRaw = detail?.models_by_ide;
  const modelsByIde =
    modelsByIdeRaw && typeof modelsByIdeRaw === "object" && !Array.isArray(modelsByIdeRaw)
      ? (modelsByIdeRaw as Record<string, string>)
      : {};
  const modelsByIdeEntries = Object.entries(modelsByIde).filter(
    ([, value]) => typeof value === "string" && value.trim().length > 0,
  );
  const supportedIdes = (detail?.supported_ides as string[]) || item.supported_ides || [];
  const components = (detail?.components as { component_type: string; component_id: string; name?: string; template?: string; description?: string; category?: string }[]) || item.components || [];
  const queryClient = useQueryClient();
  const componentKey = components.map((c) => c.component_id).join(",");
  const cachedComponentData = useMemo(() => {
    const dataMap = new Map<string, Record<string, unknown>>();
    components.forEach((comp) => {
      const pluralType = TYPE_MAP[comp.component_type] ?? `${comp.component_type}s`;
      const cached = queryClient.getQueryData(["registry", pluralType, comp.component_id]);
      if (cached) dataMap.set(comp.component_id, cached as Record<string, unknown>);
    });
    return dataMap;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [componentKey, queryClient]);

  // Build client-side diff for agents using clean YAML (no UUIDs, no metadata)
  const agentDiff = useMemo(() => {
    if (!isAgent || !agentDetail) return null;
    const curr = buildCleanYaml(agentDetail as unknown as Record<string, unknown>, cachedComponentData);
    if (!agentPrevDetail) return null;
    const prev = buildCleanYaml(agentPrevDetail as unknown as Record<string, unknown>, cachedComponentData);
    if (prev === curr) return "";
    const prevLines = prev.split("\n");
    const currLines = curr.split("\n");
    const lines: string[] = [`--- v${previousVersion}`, `+++ v${item.version}`];
    const hunks: string[] = [];
    const maxLen = Math.max(prevLines.length, currLines.length);
    let inHunk = false;
    for (let i = 0; i < maxLen; i++) {
      const pl = prevLines[i] ?? "";
      const cl = currLines[i] ?? "";
      if (pl !== cl) {
        if (!inHunk) { hunks.push(`@@ -${i + 1} +${i + 1} @@`); inHunk = true; }
        if (pl) hunks.push(`-${pl}`);
        if (cl) hunks.push(`+${cl}`);
      } else {
        if (inHunk) { hunks.push(` ${cl}`); inHunk = false; }
      }
    }
    return [...lines, ...hunks].join("\n");
  }, [isAgent, agentDetail, agentPrevDetail, previousVersion, item.version]);
  const yamlSnapshot = detail ? (isAgent ? buildCleanYaml(detail, cachedComponentData) : buildComponentYaml(detail)) : null;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="shrink-0 px-5 py-4 border-b border-border">
        <DialogHeader className="space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant="outline" className="text-[10px]">
              {item.type}
            </Badge>
            {bumpType && (
              <Badge
                variant="outline"
                className={`text-[10px] ${bumpBadgeClasses[bumpType]}`}
              >
                {bumpType}
              </Badge>
            )}
            {item.submitted_by && (
              <span className="text-xs text-muted-foreground">
                by {item.submitted_by}
              </span>
            )}
          </div>
          <DialogTitle className="text-base font-[family-name:var(--font-display)] leading-tight">
            {item.name ?? "Unnamed"}
            {previousVersion && item.version ? (
              <span className="ml-2 text-sm font-normal text-muted-foreground font-mono">
                v{previousVersion}
                <ArrowRight className="h-3 w-3 inline mx-1" />
                v{item.version}
              </span>
            ) : item.version ? (
              <span className="ml-2 text-sm font-normal text-muted-foreground font-mono">
                v{item.version} — first release
              </span>
            ) : null}
          </DialogTitle>
          {item.description && (
            <p className="text-xs text-muted-foreground line-clamp-2">{item.description}</p>
          )}
        </DialogHeader>
      </div>

      {/* Body: left details pane + right diff/snapshot pane */}
      <div className="flex flex-1 min-h-0">
        {/* Left pane: version details (~40%) */}
        <ScrollArea className="w-[40%] shrink-0 border-r border-border">
          <div className="p-5 space-y-5">
            {/* Submission metadata */}
            <div className="space-y-2">
              <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                Submission
              </h4>
              <dl className="space-y-1.5 text-xs">
                {item.submitted_by && (
                  <div>
                    <dt className="text-muted-foreground">Submitted by</dt>
                    <dd className="font-medium">{item.submitted_by}</dd>
                  </div>
                )}
                {(item.submitted_at || item.created_at) && (
                  <div>
                    <dt className="text-muted-foreground">Date</dt>
                    <dd className="font-medium">
                      {new Date(
                        (item.submitted_at ?? item.created_at)!,
                      ).toLocaleDateString()}
                    </dd>
                  </div>
                )}
                {bumpType && (
                  <div>
                    <dt className="text-muted-foreground">Bump type</dt>
                    <dd>
                      <Badge
                        variant="outline"
                        className={`text-[10px] ${bumpBadgeClasses[bumpType]}`}
                      >
                        {bumpType}
                      </Badge>
                    </dd>
                  </div>
                )}
              </dl>
            </div>

            {/* Model */}
            {(modelName || modelsByIdeEntries.length > 0) && (
              <>
                <Separator />
                <div className="space-y-2">
                  <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                    Model
                  </h4>
                  {modelName && (
                    <p className="text-xs font-[family-name:var(--font-mono)]">{modelName}</p>
                  )}
                  {modelsByIdeEntries.length > 0 && (
                    <dl className="space-y-1 text-xs">
                      <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">
                        Per-IDE overrides
                      </dt>
                      {modelsByIdeEntries.map(([ide, value]) => (
                        <div key={ide} className="flex items-baseline gap-2">
                          <dd className="font-medium">{ide}</dd>
                          <dd className="font-[family-name:var(--font-mono)] text-muted-foreground">
                            {value}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </div>
              </>
            )}

            {/* Supported IDEs */}
            {supportedIdes.length > 0 && (
              <>
                <Separator />
                <div className="space-y-2">
                  <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                    Supported IDEs
                  </h4>
                  <p className="text-xs font-medium">{supportedIdes.join(", ")}</p>
                </div>
              </>
            )}

            {/* Prompt */}
            {prompt && (
              <>
                <Separator />
                <div className="space-y-2">
                  <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                    Prompt
                  </h4>
                  <pre className="text-xs font-[family-name:var(--font-mono)] whitespace-pre-wrap break-words bg-muted/40 rounded p-3 leading-relaxed max-h-64 overflow-y-auto">
                    {prompt}
                  </pre>
                </div>
              </>
            )}

            {/* Component-specific fields */}
            {!isAgent && detail && (
              <>
                {(detail.template as string) && (
                  <>
                    <Separator />
                    <div className="space-y-2">
                      <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                        Template
                      </h4>
                      <pre className="text-xs font-[family-name:var(--font-mono)] whitespace-pre-wrap break-words bg-muted/40 rounded p-3 leading-relaxed max-h-64 overflow-y-auto">
                        {detail.template as string}
                      </pre>
                    </div>
                  </>
                )}
                {(detail.category as string) && (
                  <>
                    <Separator />
                    <div className="space-y-2">
                      <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                        Category
                      </h4>
                      <p className="text-xs font-medium">{detail.category as string}</p>
                    </div>
                  </>
                )}
                {(detail.event as string) && (
                  <>
                    <Separator />
                    <div className="space-y-2">
                      <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                        Event
                      </h4>
                      <p className="text-xs font-medium">{detail.event as string}</p>
                    </div>
                  </>
                )}
                {(detail.handler_type as string) && (
                  <>
                    <Separator />
                    <div className="space-y-2">
                      <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                        Handler
                      </h4>
                      <p className="text-xs font-medium">{detail.handler_type as string}</p>
                    </div>
                  </>
                )}
                {(detail.changelog as string) && (
                  <>
                    <Separator />
                    <div className="space-y-2">
                      <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                        Changelog
                      </h4>
                      <pre className="text-xs font-[family-name:var(--font-mono)] whitespace-pre-wrap break-words bg-muted/40 rounded p-3 leading-relaxed max-h-32 overflow-y-auto">
                        {detail.changelog as string}
                      </pre>
                    </div>
                  </>
                )}
              </>
            )}

            {/* Component changes (from diff) or component list */}
            {components.length ? (
              <>
                <Separator />
                <div className="space-y-2">
                  <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                    {`Components (${components.length})`}
                  </h4>
                  <div className="space-y-2">
                    {components.map((ch, i) => {
                      const change = (ch as { change?: string }).change;
                      return (
                        <div key={i}>
                          {change && change !== "context" && (
                            <Badge variant="outline" className={`mb-1 text-[10px] flex items-center gap-1 w-fit ${changeBadgeClasses[change as keyof typeof changeBadgeClasses] ?? ""}`}>
                              {changeIcon[change as keyof typeof changeIcon]}
                              {change}
                            </Badge>
                          )}
                          <LinkedComponentDetail
                            componentType={(ch as {component_type?: string; type?: string}).component_type ?? (ch as {type?: string}).type ?? ""}
                            componentId={(ch as {component_id?: string}).component_id ?? ""}
                            onPendingClick={onOpenComponentReview}
                            isPending={item.component_blockers?.some(
                              (b) => b.component_id === (ch as {component_id?: string}).component_id
                            ) ?? false}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              </>
            ) : null}
          </div>
        </ScrollArea>

        {/* Right pane: diff or YAML snapshot (~60%) */}
        <div className="flex-1 min-w-0 flex flex-col min-h-0">
          {isLoading ? (
            <div className="flex-1 p-4 space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-4/6" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
            </div>
          ) : agentDiff !== null && isAgent ? (
            agentDiff ? (
              <YamlDiffView
                diff={agentDiff}
                versionA={previousVersion ?? ""}
                versionB={item.version ?? ""}
              />
            ) : (
              <div className="flex items-center justify-center flex-1 text-sm text-muted-foreground">No changes detected.</div>
            )
          ) : !previousVersion && !versionsLoading ? (
            <div className="flex flex-col h-full min-h-0">
              <div className="shrink-0 flex items-center px-4 py-2 border-b border-border text-xs font-medium text-muted-foreground">
                <span>v{item.version}</span>
                <span className="ml-2 italic">— initial release</span>
              </div>
              {yamlSnapshot ? (
                <div className="flex-1 min-h-0 overflow-y-auto">
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse font-[family-name:var(--font-mono)] text-xs leading-5">
                      <tbody>
                        {yamlSnapshot.split("\n").map((line, i) => (
                          <tr key={i} className="hover:bg-muted/30">
                            <td className="select-none w-10 shrink-0 px-2 text-right tabular-nums text-muted-foreground/50 border-r border-border/40">
                              {i + 1}
                            </td>
                            <td className="px-3 whitespace-pre-wrap break-words text-foreground leading-relaxed">
                              {line}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className="flex-1 min-h-0 overflow-y-auto">
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse font-[family-name:var(--font-mono)] text-xs leading-5">
                      <tbody>
                        {(() => {
                          const structural = toReviewYaml({
                              description: item.description || undefined,
                              prompt: prompt || undefined,
                              model_name: modelName || undefined,
                              models_by_ide: modelsByIdeEntries.length
                                ? Object.fromEntries(modelsByIdeEntries)
                                : undefined,
                              supported_ides: supportedIdes.length ? supportedIdes : undefined,
                              components: components.length
                                ? components.map((c) => `${c.component_type}: ${(c as Record<string, unknown>).name as string || c.component_id}`)
                                : undefined,
                          } as Record<string, unknown>);
                          return structural.split("\n").map((line: string, i: number) => (
                            <tr key={i} className="hover:bg-muted/30">
                              <td className="select-none w-10 shrink-0 px-2 text-right tabular-nums text-muted-foreground/50 border-r border-border/40">
                                {i + 1}
                              </td>
                              <td className="px-3 whitespace-pre-wrap break-words text-foreground leading-relaxed">
                                {line}
                              </td>
                            </tr>
                          ));
                        })()}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          ) : componentDiff !== null ? (
            <YamlDiffView
              diff={componentDiff}
              versionA={previousVersion ?? ""}
              versionB={item.version ?? ""}
            />
          ) : (
            <div className="flex items-center justify-center flex-1 text-sm text-muted-foreground">
              Unable to load diff.
            </div>
          )}
        </div>
      </div>

      {/* Footer actions */}
      <div className="shrink-0 border-t border-border px-5 py-4 space-y-3">
        {isAgent && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground whitespace-nowrap">Category:</span>
            <select
              value={approveCategory}
              onChange={(e) => setApproveCategory(e.target.value)}
              className="flex h-7 flex-1 rounded-md border border-input bg-transparent px-2 py-1 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="">None (keep existing)</option>
              <option value="Code Review">Code Review</option>
              <option value="Testing">Testing</option>
              <option value="Documentation">Documentation</option>
              <option value="DevOps">DevOps</option>
              <option value="Security">Security</option>
              <option value="Data">Data</option>
              <option value="Incident Response">Incident Response</option>
              <option value="Deployment">Deployment</option>
              <option value="Cost Optimization">Cost Optimization</option>
              <option value="Other">Other</option>
            </select>
          </div>
        )}
        <div className="flex items-center gap-2">
          {disableApprove ? (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="flex-1">
                    <Button
                      size="sm"
                      className="h-8 text-xs w-full bg-success/10 text-success border border-success/25 shadow-none opacity-50 cursor-not-allowed"
                      disabled
                    >
                      Approve
                    </Button>
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  <p>Cannot approve until all required components are ready</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          ) : (
            <Button
              size="sm"
              className="h-8 text-xs flex-1 bg-success/10 hover:bg-success/20 text-success border border-success/25 shadow-none"
              onClick={handleApprove}
            >
              Approve
            </Button>
          )}
          <Button
            size="sm"
            className="h-8 text-xs flex-1 bg-destructive/10 hover:bg-destructive/20 text-destructive border border-destructive/25 shadow-none"
            onClick={() => setShowRejectDialog(true)}
          >
            Reject
          </Button>
        </div>
      </div>

      {/* Reject reason dialog */}
      <Dialog open={showRejectDialog} onOpenChange={setShowRejectDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-sm font-[family-name:var(--font-display)]">
              Reject {item.name ?? "submission"}
            </DialogTitle>
          </DialogHeader>
          <Textarea
            placeholder="Why is this being rejected? Be specific so the submitter can fix and resubmit."
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            className="min-h-[100px] text-sm"
            autoFocus
          />
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setShowRejectDialog(false);
                setRejectReason("");
              }}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              className="bg-destructive hover:bg-destructive/90 text-destructive-foreground"
              disabled={!rejectReason.trim()}
              onClick={handleRejectConfirm}
            >
              Reject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
