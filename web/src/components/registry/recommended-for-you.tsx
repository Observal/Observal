// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { Link } from "@tanstack/react-router";
import {
  BookOpenCheck,
  Box,
  GitBranch,
  MessageSquareText,
  PlugZap,
  X,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { REVERSE_TYPE_MAP } from "@/components/registry/agent-component-constants";
import {
  useDismissRecommendation,
  useMyRecommendations,
} from "@/hooks/use-recommendations-api";
import { registryItemPath } from "@/lib/registry-name";
import { compactNumber } from "@/lib/utils";

const TYPE_META: Record<
  string,
  { label: string; icon: LucideIcon; color: string }
> = {
  mcp: { label: "MCP", icon: PlugZap, color: "text-component-mcp" },
  skill: { label: "Skill", icon: BookOpenCheck, color: "text-component-skill" },
  hook: { label: "Hook", icon: GitBranch, color: "text-component-hook" },
  prompt: {
    label: "Prompt",
    icon: MessageSquareText,
    color: "text-component-prompt",
  },
  sandbox: {
    label: "Sandbox",
    icon: Box,
    color: "text-component-sandbox",
  },
};

function Header({
  personalized,
  sessions,
  loading = false,
}: {
  personalized: boolean;
  sessions: number;
  loading?: boolean;
}) {
  return (
    <header className="flex min-h-16 flex-col justify-center gap-1 border-b border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-5">
      <div className="min-w-0">
        <h2 className="text-base font-semibold tracking-tight text-foreground">
          {loading
            ? "Recommended for you"
            : personalized
              ? "Matches from your work"
              : "Popular components"}
        </h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {loading
            ? "Loading recommendations."
            : personalized
              ? `Evidence from ${sessions} captured session${sessions === 1 ? "" : "s"}.`
              : "Most-used components visible to you."}
        </p>
      </div>
      {!loading && personalized && (
        <span className="shrink-0 text-sm text-muted-foreground">
          Ranked by observed activity
        </span>
      )}
    </header>
  );
}

export function RecommendedForYou({ limit = 6 }: { limit?: number }) {
  const { data, isLoading, isError } = useMyRecommendations(limit);
  const dismiss = useDismissRecommendation();

  if (isError) return null;

  if (isLoading) {
    return (
      <section className="overflow-hidden rounded-md border border-border bg-card">
        <Header loading personalized={false} sessions={0} />
        <div className="p-3">
          <TableSkeleton rows={3} cols={3} />
        </div>
      </section>
    );
  }

  const items = data?.items ?? [];
  const personalized = data?.personalized ?? false;
  const sessions = data?.profile_sessions ?? 0;

  return (
    <section className="overflow-hidden rounded-md border border-border bg-card">
      <Header personalized={personalized} sessions={sessions} />

      {items.length === 0 ? (
        <p className="p-6 text-sm leading-6 text-muted-foreground">
          Nothing new to recommend. You may have already installed or dismissed
          the current matches.
        </p>
      ) : (
        <div>
          {items.map((item) => {
            const meta = TYPE_META[item.type] ?? TYPE_META.mcp;
            const Icon = meta.icon;
            return (
              <div
                key={`${item.type}:${item.id}`}
                className="group grid min-h-20 grid-cols-[1.25rem_minmax(0,1fr)_auto] gap-3 border-b border-border/75 px-4 py-3 last:border-b-0 hover:bg-accent/45"
              >
                <Icon
                  className={`mt-0.5 h-4 w-4 ${meta.color}`}
                  aria-hidden="true"
                />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <Link
                      to={registryItemPath(
                        item,
                        REVERSE_TYPE_MAP[item.type] ?? "mcps",
                        item.id,
                      )}
                      className="break-all text-sm font-semibold text-foreground underline-offset-4 hover:text-primary-accent hover:underline"
                    >
                      {item.name}
                    </Link>
                    <span className={`text-xs font-semibold ${meta.color}`}>
                      {meta.label}
                    </span>
                    <span className="font-mono text-xs text-muted-foreground">
                      v{item.latest_version}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-1 text-sm text-muted-foreground">
                    {item.description}
                  </p>
                  <p className="mt-1 text-sm text-foreground/85">{item.reason}</p>
                </div>
                <div className="flex items-start gap-2">
                  {item.download_count > 0 && (
                    <span className="hidden whitespace-nowrap text-xs text-muted-foreground sm:inline">
                      {compactNumber(item.download_count)} installs
                    </span>
                  )}
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Dismiss ${item.name}`}
                    title="Dismiss recommendation"
                    className="h-8 w-8 rounded-sm text-muted-foreground opacity-70 hover:opacity-100"
                    disabled={dismiss.isPending}
                    onClick={() =>
                      dismiss.mutate({ type: item.type, id: item.id })
                    }
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
