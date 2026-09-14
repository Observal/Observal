// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

/** Registry rankings based exclusively on live leaderboard data. */

import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { PageHeader, PageIntro } from "@/components/layouts/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import {
  LeaderFeatureCard,
  RankingHead,
  RankingRow,
  SegmentedControl,
} from "@/components/registry/registry-primitives";
import { useComponentLeaderboard, useLeaderboard } from "@/hooks/use-api";
import { registryItemPath, type RegistryRouteType } from "@/lib/registry-name";
import { compactNumber } from "@/lib/utils";
import type { LeaderboardWindow } from "@/lib/types";

type TopTab = "agents" | "components";

function componentRouteType(type: string): RegistryRouteType {
  return (
    {
      mcp: "mcps",
      skill: "skills",
      hook: "hooks",
      prompt: "prompts",
      sandbox: "sandboxes",
    } as const
  )[type] ?? "mcps";
}

export default function LeaderboardPage() {
  const [topTab, setTopTab] = useState<TopTab>("agents");
  const [window, setWindow] = useState<LeaderboardWindow>("7d");

  const { data: leaderboard, isLoading: agentsLoading } = useLeaderboard(window, 50);
  const { data: componentLeaderboard, isLoading: componentsLoading } = useComponentLeaderboard(window, 50);
  const isLoading = topTab === "agents" ? agentsLoading : componentsLoading;

  const rankings = useMemo(() => {
    if (topTab === "agents") {
      if (!leaderboard?.length) return [];
      return [...leaderboard]
        .sort((a, b) => b.download_count - a.download_count)
        .map((item, index) => ({
          id: item.id,
          name: item.name,
          handle: item.namespace ? `${item.namespace}/${item.slug ?? item.name}` : item.name,
          description: item.description ?? "",
          downloads: compactNumber(item.download_count),
          rating: item.average_rating?.toFixed(1) ?? "New",
          href: registryItemPath(item, "agents", item.id),
          position: index + 1,
        }));
    }

    if (!componentLeaderboard?.length) return [];
    return [...componentLeaderboard]
      .sort((a, b) => b.download_count - a.download_count)
      .map((item, index) => ({
        id: item.id,
        name: item.name,
        handle: item.namespace ? `${item.namespace}/${item.slug ?? item.name}` : item.name,
        description: item.description,
        downloads: compactNumber(item.download_count),
        rating: item.average_rating?.toFixed(1) ?? "New",
        href: registryItemPath(item, componentRouteType(item.component_type), item.id),
        position: index + 1,
      }));
  }, [componentLeaderboard, leaderboard, topTab]);

  const featuredItem = rankings[0];
  const entityLabel = topTab === "agents" ? "Agent" : "Component";

  return (
    <>
      <PageHeader
        title="Leaderboard"
        breadcrumbs={[
          { label: "Registry", href: "/" },
          { label: "Leaderboard" },
        ]}
      />

      <div className="page-body w-full mx-auto space-y-0">
        <PageIntro
          eyebrow="Registry"
          title="Leaderboard"
          subtitle="See what developers are adopting across the Registry."
        />

        <div className="mb-4 flex flex-wrap items-center gap-2.5">
          <SegmentedControl
            options={[
              { value: "agents", label: "Agents" },
              { value: "components", label: "Components" },
            ]}
            value={topTab}
            onChange={(value) => setTopTab(value as TopTab)}
          />
          <div className="ml-auto">
            <SegmentedControl
              options={[
                { value: "24h", label: "24h" },
                { value: "7d", label: "7 days" },
                { value: "30d", label: "30 days" },
                { value: "all", label: "All time" },
              ]}
              value={window}
              onChange={(value) => setWindow(value as LeaderboardWindow)}
            />
          </div>
        </div>

        {isLoading ? (
          <TableSkeleton rows={8} cols={4} />
        ) : rankings.length === 0 ? (
          <EmptyState
            title={`No ${topTab} rankings yet`}
            description={`Approved ${topTab} will appear once they have recorded downloads in this period.`}
          />
        ) : (
          <>
            <section className="mb-3.5">
              <LeaderFeatureCard
                rank="Most adopted in this period"
                title={featuredItem.name}
                handle={featuredItem.handle}
                description={featuredItem.description || `${entityLabel} adoption is based on recorded Registry downloads.`}
                stats={[
                  { label: "Downloads", value: featuredItem.downloads },
                  { label: "Rating", value: featuredItem.rating },
                ]}
              />
            </section>

            <section className="overflow-hidden rounded-xl bg-card shadow-sm">
              <div className="flex items-center justify-between border-b border-border px-5 py-4">
                <div>
                  <h2 className="text-sm font-medium">{entityLabel} rankings</h2>
                  <p className="mt-0.5 text-2xs text-muted-foreground">
                    Approved {topTab} ranked by downloads in the selected period.
                  </p>
                </div>
              </div>
              <RankingHead entityLabel={entityLabel} />
              {rankings.map((ranking) => (
                <RankingRow
                  key={ranking.id}
                  position={ranking.position}
                  downloads={ranking.downloads}
                  rating={ranking.rating}
                  isTop={ranking.position <= 3}
                >
                  <Link
                    to={ranking.href}
                    className="block rounded-sm outline-none hover:text-primary focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <strong className="block text-xs font-medium">{ranking.name}</strong>
                    <span className="block mt-0.5 font-mono text-[10px] text-muted-foreground">
                      {ranking.handle}
                    </span>
                  </Link>
                </RankingRow>
              ))}
            </section>
          </>
        )}
      </div>
    </>
  );
}
