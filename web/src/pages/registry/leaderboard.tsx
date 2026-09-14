// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

/**
 * Leaderboard page — matches the approved HTML mockup exactly.
 *
 * Layout (top → bottom):
 *  1. Leaderboard controls — three segmented rows (Agents/Components,
 *     Rankings/Publishers, time‑range).
 *  2. Feature card — top‑ranked entity with sparkline and stats.
 *  3. Lower grid — ranking list (left ~60 %) + movement card (right ~40 %).
 */

import { useMemo, useState } from "react";
import { PageHeader, PageIntro } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import {
  SegmentedControl,
  LeaderFeatureCard,
  RankingHead,
  RankingRow,
  MovementItem,
  Sparkline,
} from "@/components/registry/registry-primitives";
import { useLeaderboard, useComponentLeaderboard } from "@/hooks/use-api";
import { compactNumber } from "@/lib/utils";
import type { LeaderboardWindow } from "@/lib/types";

/* ────────────────────────────────────────────────── */
/*  Fallback data — used only when API returns empty */
/* ────────────────────────────────────────────────── */

const FALLBACK_RANKINGS = [
  { pos: 1, name: "Repository Analyst", handle: "github/repository-analyst", downloads: "18.2k", rating: "4.9", change: "+38%" },
  { pos: 2, name: "Secure Reviewer", handle: "acme/secure-reviewer", downloads: "12.8k", rating: "4.9", change: "+31%" },
  { pos: 3, name: "Test Architect", handle: "dx/test-architect", downloads: "11.6k", rating: "4.8", change: "+26%" },
  { pos: 4, name: "Incident Responder", handle: "infra/incident-responder", downloads: "9.4k", rating: "4.7", change: "+21%" },
  { pos: 5, name: "Release Pilot", handle: "platform/release-pilot", downloads: "8.4k", rating: "4.8", change: "+18%" },
  { pos: 6, name: "Docs Maintainer", handle: "open-source/docs-maintainer", downloads: "7.9k", rating: "4.7", change: "+12%" },
];

const FALLBACK_MOVEMENTS = [
  { badge: "+4", title: "test-architect", description: "Shared by Developer Experience after 28 successful sessions." },
  { badge: "+2", title: "incident-responder", description: "New Sentry integration drove 1.8k additional pulls." },
  { badge: "NEW", title: "schema-guide", description: "First approved release from the Data Platform teamspace." },
];

/* ────────────────────────────────────────────────── */
/*  Top tab / sub-tab / window types                 */
/* ────────────────────────────────────────────────── */

type TopTab = "agents" | "components";
type SubTab = "rankings" | "publishers";

export default function LeaderboardPage() {
  const [topTab, setTopTab] = useState<TopTab>("agents");
  const [subTab, setSubTab] = useState<SubTab>("rankings");
  const [window, setWindow] = useState<LeaderboardWindow>("7d");

  const { data: leaderboard, isLoading: agentsLoading } = useLeaderboard(window, 50);
  const { data: componentLeaderboard, isLoading: componentsLoading } = useComponentLeaderboard(window, 50);

  const isLoading = topTab === "agents" ? agentsLoading : componentsLoading;

  /* Build ranked list from API data or fallback */
  const rankings = useMemo(() => {
    if (topTab === "agents") {
      if (!leaderboard || leaderboard.length === 0) return null;
      return [...leaderboard]
        .sort((a, b) => b.download_count - a.download_count)
        .map((item, i) => ({
          pos: i + 1,
          id: item.id,
          name: item.name,
          handle: item.namespace ? `${item.namespace}/${item.slug ?? item.name}` : item.name,
          downloads: compactNumber(item.download_count),
          rating: item.average_rating?.toFixed(1) ?? "—",
          change: "+—",
          item,
        }));
    }
    if (!componentLeaderboard || componentLeaderboard.length === 0) return null;
    return [...componentLeaderboard]
      .sort((a, b) => b.download_count - a.download_count)
      .map((item, i) => ({
        pos: i + 1,
        id: item.id,
        name: item.name,
        handle: item.created_by_email ?? item.name,
        downloads: compactNumber(item.download_count),
        rating: item.average_rating?.toFixed(1) ?? "—",
        change: "+—",
        item,
      }));
  }, [topTab, leaderboard, componentLeaderboard]);

  /* Feature card: use first ranked item or fallback */
  const featuredItem = rankings?.[0] ?? null;

  /* Determine if using fallback */
  const useFallback = !isLoading && !rankings;

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
          eyebrow="Registry momentum"
          title="Leaderboard"
          subtitle="See what developers are adopting, who publishes it, and why rankings changed."
        />

        {/* ── Leaderboard controls ─────────────────────── */}
        <div className="mb-4 flex flex-wrap items-center gap-2.5">
          <SegmentedControl
            options={[
              { value: "agents", label: "Agents" },
              { value: "components", label: "Components" },
            ]}
            value={topTab}
            onChange={(v) => setTopTab(v as TopTab)}
          />
          <SegmentedControl
            options={[
              { value: "rankings", label: "Rankings" },
              { value: "publishers", label: "Publishers" },
            ]}
            value={subTab}
            onChange={(v) => setSubTab(v as SubTab)}
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
              onChange={(v) => setWindow(v as LeaderboardWindow)}
            />
          </div>
        </div>

        {isLoading ? (
          <TableSkeleton rows={8} cols={5} />
        ) : (
          <>
            {/* ── Feature card ───────────────────────────── */}
            <section className="mb-3.5">
              <LeaderFeatureCard
                rank="Most adopted this week"
                title={featuredItem?.name ?? "repository-analyst"}
                handle={featuredItem?.handle ?? "github/repository-analyst · v3.4.0"}
                description={
                  useFallback
                    ? "Maps unfamiliar repositories and produces evidence-backed change plans. Adoption accelerated after the monorepo navigation update."
                    : ((featuredItem?.item as unknown as Record<string, unknown>)?.description as string) ??
                      "Maps unfamiliar repositories and produces evidence-backed change plans."
                }
                stats={[
                  { label: "Downloads", value: featuredItem?.downloads ?? "18.2k" },
                  {
                    label: "7-day growth",
                    value: (
                      <span className="text-success">
                        {featuredItem?.change ?? "+38%"}
                      </span>
                    ),
                  },
                  { label: "Rating", value: featuredItem?.rating ?? "4.9" },
                  { label: "Compatible harnesses", value: "8" },
                ]}
                className="relative"
              >
                <Sparkline className="absolute right-5 top-6 h-[68px] w-[180px]" />
              </LeaderFeatureCard>
            </section>

            {/* ── Lower grid: rankings + movement ────────── */}
            <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-[minmax(0,1.45fr)_minmax(280px,0.55fr)]">
              {/* Ranking list */}
              <section className="overflow-hidden rounded-xl bg-card shadow-sm">
                <div className="flex items-center justify-between border-b border-border px-5 py-4">
                  <div>
                    <h2 className="text-sm font-medium">
                      {topTab === "agents" ? "Agent rankings" : "Component rankings"}
                    </h2>
                    <p className="mt-0.5 text-2xs text-muted-foreground">
                      Approved {topTab} ranked by downloads in the selected period
                    </p>
                  </div>
                  <button
                    type="button"
                    className="text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
                  >
                    How rankings work
                  </button>
                </div>
                <RankingHead />
                {useFallback
                  ? FALLBACK_RANKINGS.map((r) => (
                      <RankingRow
                        key={r.pos}
                        position={r.pos}
                        downloads={r.downloads}
                        rating={r.rating}
                        change={r.change}
                        isTop={r.pos <= 3}
                      >
                        <strong className="block text-xs font-medium">{r.name}</strong>
                        <span className="block mt-0.5 font-mono text-[10px] text-muted-foreground">
                          {r.handle}
                        </span>
                      </RankingRow>
                    ))
                  : rankings!.map((r) => (
                      <RankingRow
                        key={r.id}
                        position={r.pos}
                        downloads={r.downloads}
                        rating={r.rating}
                        change={r.change}
                        isTop={r.pos <= 3}
                      >
                        <strong className="block text-xs font-medium">{r.name}</strong>
                        <span className="block mt-0.5 font-mono text-[10px] text-muted-foreground">
                          {r.handle}
                        </span>
                      </RankingRow>
                    ))}
              </section>

              {/* Movement card */}
              <aside className="rounded-xl bg-card p-5 shadow-sm">
                <h2 className="mb-1 text-[15px] font-medium">What moved this week</h2>
                <p className="mb-3.5 text-[10px] text-muted-foreground">
                  Context behind the ranking changes.
                </p>
                {FALLBACK_MOVEMENTS.map((m) => (
                  <MovementItem
                    key={m.title}
                    badge={m.badge}
                    title={m.title}
                    description={m.description}
                  />
                ))}
              </aside>
            </div>
          </>
        )}
      </div>
    </>
  );
}
