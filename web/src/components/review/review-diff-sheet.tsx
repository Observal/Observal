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
import { YamlDiffView } from "./yaml-diff-view";
import { useAgentVersions, useVersionDiff, useAgentVersionDetail, useComponentVersions, useComponentVersionDetail } from "@/hooks/use-api";
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

interface ReviewDiffSheetProps {
  item: ReviewItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApprove: (id: string, type?: string) => void;
  onReject: (id: string, reason: string, type?: string) => void;
}

export function ReviewDiffSheet({
  item,
  open,
  onOpenChange,
  onApprove,
  onReject,
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
}: {
  item: ReviewItem;
  onOpenChange: (open: boolean) => void;
  onApprove: (id: string, type?: string) => void;
  onReject: (id: string, reason: string, type?: string) => void;
}) {
  const [showRejectDialog, setShowRejectDialog] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

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

  // Only agents have a server-side diff endpoint
  const { data: diffData, isLoading: diffLoading } = useVersionDiff(
    isAgent ? item.id : undefined,
    isAgent ? previousVersion : undefined,
    isAgent ? item.version : undefined,
  );

  // Agent version detail
  const { data: agentDetail, isLoading: agentDetailLoading } = useAgentVersionDetail(
    isAgent ? item.id : undefined,
    isAgent ? (item.version ?? null) : null,
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
    const prev = JSON.stringify(compPrevDetail, null, 2);
    const curr = JSON.stringify(compDetail, null, 2);
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
    onApprove(item.id, item.type);
    onOpenChange(false);
  }, [item, onApprove, onOpenChange]);

  const handleRejectConfirm = useCallback(() => {
    if (!rejectReason.trim()) return;
    onReject(item.id, rejectReason, item.type);
    setShowRejectDialog(false);
    setRejectReason("");
    onOpenChange(false);
  }, [rejectReason, item, onReject, onOpenChange]);

  const disableApprove = item.components_ready === false;

  const isLoading = versionsLoading || detailLoading || (!!previousVersion && diffLoading);

  const detail = (isAgent ? agentDetail : compDetail) as Record<string, unknown> | undefined;
  const yamlSnapshot = isAgent
    ? (detail?.yaml_snapshot as string | null | undefined)
    : detail
      ? JSON.stringify(detail, null, 2)
      : null;
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
            {diffData?.component_changes?.length ? (
              <>
                <Separator />
                <div className="space-y-2">
                  <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                    Component Changes ({diffData.component_changes.length})
                  </h4>
                  <ComponentChangesList changes={diffData.component_changes} />
                </div>
              </>
            ) : components.length ? (
              <>
                <Separator />
                <div className="space-y-2">
                  <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                    Components ({components.length})
                  </h4>
                  <div className="space-y-2">
                    {components.map((c, i) => (
                      <div
                        key={i}
                        className="text-xs rounded bg-muted/40 overflow-hidden"
                      >
                        <div className="flex items-center gap-2 py-1.5 px-2">
                          <Badge variant="outline" className="text-[10px] shrink-0">
                            {c.component_type}
                          </Badge>
                          <span className="font-medium truncate">
                            {c.name || c.component_id}
                          </span>
                        </div>
                        {c.template && (
                          <pre className="px-3 pb-2 text-[11px] font-[family-name:var(--font-mono)] whitespace-pre-wrap break-words text-muted-foreground leading-relaxed">
                            {c.template}
                          </pre>
                        )}
                        {c.description && !c.template && (
                          <p className="px-3 pb-2 text-[11px] text-muted-foreground">
                            {c.description}
                          </p>
                        )}
                      </div>
                    ))}
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
          ) : diffData ? (
            <YamlDiffView
              diff={diffData.yaml_diff}
              versionA={diffData.version_a}
              versionB={diffData.version_b}
            />
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
                            <td className="px-3 whitespace-pre-wrap break-all text-foreground">
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
                          const structural = JSON.stringify(
                            {
                              description: item.description || undefined,
                              prompt: prompt || undefined,
                              model_name: modelName || undefined,
                              models_by_ide: modelsByIdeEntries.length
                                ? Object.fromEntries(modelsByIdeEntries)
                                : undefined,
                              supported_ides: supportedIdes.length ? supportedIdes : undefined,
                              components: components.length
                                ? components.map((c) => `${c.component_type}:${c.component_id}`)
                                : undefined,
                            },
                            null,
                            2,
                          );
                          return structural.split("\n").map((line, i) => (
                            <tr key={i} className="hover:bg-muted/30">
                              <td className="select-none w-10 shrink-0 px-2 text-right tabular-nums text-muted-foreground/50 border-r border-border/40">
                                {i + 1}
                              </td>
                              <td className="px-3 whitespace-pre-wrap break-all text-foreground">
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
      <div className="shrink-0 border-t border-border px-5 py-4">
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
