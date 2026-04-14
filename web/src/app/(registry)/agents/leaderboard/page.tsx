"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Trophy,
  ArrowDownToLine,
  Star,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { EmptyState } from "@/components/shared/empty-state";
import { useLeaderboard } from "@/hooks/use-api";
import { compactNumber } from "@/lib/utils";
import type { LeaderboardWindow } from "@/lib/types";

export default function LeaderboardPage() {
  const [window, setWindow] = useState<LeaderboardWindow>("7d");
  const { data: leaderboard, isLoading } = useLeaderboard(window, 50);

  return (
    <>
      <PageHeader
        title="Leaderboard"
        breadcrumbs={[
          { label: "Registry", href: "/" },
          { label: "Agents", href: "/agents" },
          { label: "Leaderboard" },
        ]}
      />

      <div className="p-6 lg:p-8 w-full max-w-[1200px] mx-auto space-y-6">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <p className="text-sm text-muted-foreground">
            Agents ranked by downloads within the selected time window.
          </p>
          <Tabs
            value={window}
            onValueChange={(v) => setWindow(v as LeaderboardWindow)}
          >
            <TabsList>
              <TabsTrigger value="24h">24h</TabsTrigger>
              <TabsTrigger value="7d">7 days</TabsTrigger>
              <TabsTrigger value="30d">30 days</TabsTrigger>
              <TabsTrigger value="all">All time</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        {isLoading ? (
          <TableSkeleton rows={10} cols={5} />
        ) : !leaderboard || leaderboard.length === 0 ? (
          <EmptyState
            icon={Trophy}
            title="No rankings yet"
            description="Install agents via the CLI or web UI to populate the leaderboard."
          />
        ) : (
          <div className="space-y-1 animate-in">
            {/* Header */}
            <div className="flex items-center gap-4 px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
              <span className="w-8 text-right">#</span>
              <span className="flex-1">Agent</span>
              <span className="w-24 text-right">Downloads</span>
              <span className="w-16 text-right">Rating</span>
              <span className="w-20 text-right">Version</span>
            </div>

            {leaderboard.map((item, i) => (
              <Link
                key={item.id}
                href={`/agents/${item.id}`}
                className="flex items-center gap-4 rounded-md px-3 py-3 transition-colors hover:bg-accent/40 group"
              >
                <span
                  className={`w-8 text-right font-mono font-semibold ${
                    i < 3 ? "text-foreground" : "text-muted-foreground"
                  }`}
                >
                  {i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium truncate block group-hover:underline underline-offset-4">
                    {item.name}
                  </span>
                  <span className="text-xs text-muted-foreground/70 truncate block">
                    {item.owner}
                    {item.description && ` — ${item.description}`}
                  </span>
                </div>
                <span className="w-24 text-right inline-flex items-center justify-end gap-1 text-sm text-muted-foreground font-mono">
                  <ArrowDownToLine className="h-3 w-3" />
                  {compactNumber(item.download_count)}
                </span>
                <span className="w-16 text-right inline-flex items-center justify-end gap-1 text-sm text-muted-foreground">
                  {item.average_rating != null ? (
                    <>
                      <Star className="h-3 w-3" />
                      {item.average_rating.toFixed(1)}
                    </>
                  ) : (
                    "-"
                  )}
                </span>
                <span className="w-20 text-right">
                  {item.version ? (
                    <Badge
                      variant="secondary"
                      className="text-[10px] px-1.5 py-0"
                    >
                      {item.version}
                    </Badge>
                  ) : (
                    <span className="text-sm text-muted-foreground">-</span>
                  )}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
