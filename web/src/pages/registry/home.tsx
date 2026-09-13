// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { Link, useRouter } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Blocks,
  Bot,
  Star,
} from "lucide-react";
import { PageHeader, PageIntro } from "@/components/layouts/page-header";
import { RecommendedForYou } from "@/components/registry/recommended-for-you";
import { RegistryName } from "@/components/registry/registry-name";
import { EntityGlyph } from "@/components/registry/entity-glyph";
import {
  Panel,
  CompactRow,
  IntentSearch,
  IntentChip,
  RegistryHomeGrid,
} from "@/components/registry/registry-primitives";
import { ErrorState } from "@/components/shared/error-state";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import {
  useMyAgents,
  useRegistryList,
  useSessions2,
  useTopAgents,
  useWhoami,
} from "@/hooks/use-api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { registryItemPath } from "@/lib/registry-name";
import { compactNumber } from "@/lib/utils";
import type { RegistryItem, Session, TopAgentItem } from "@/lib/types";

const TIME_FORMATTER = new Intl.DateTimeFormat("en", {
  hour: "numeric",
  minute: "2-digit",
});

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

function toNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

function formatTime(value?: string): string {
  if (!value) return "No activity";
  const parsed = new Date(
    value.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(value)
      ? value
      : `${value.replace(" ", "T")}Z`,
  );
  if (Number.isNaN(parsed.getTime())) return "No activity";
  return parsed.toDateString() === new Date().toDateString()
    ? TIME_FORMATTER.format(parsed)
    : DATE_TIME_FORMATTER.format(parsed);
}

function isApproved(agent: RegistryItem): boolean {
  return !agent.status || agent.status === "approved";
}

function sessionTitle(session: Session): string {
  const prompts = toNumber(session.prompt_count);
  return `${session.agent_name ? `${session.agent_name} · ` : ""}${prompts} ${prompts === 1 ? "prompt" : "prompts"}`;
}

function sessionPlatform(session: Session): string {
  return session.platform || session.service_name || "Unknown harness";
}

export default function RegistryHome() {
  const [search, setSearch] = useState("");
  const router = useRouter();
  const { data: whoami } = useWhoami();
  const { brandingAppName } = useDeploymentConfig();
  const { data: sessions, isLoading: sessionsLoading } = useSessions2({
    days: 7,
    limit: 8,
    mine: true,
    refetchInterval: 30_000,
  });
  const { data: myAgents, isLoading: myAgentsLoading } = useMyAgents();
  const { data: topAgents, isLoading: topAgentsLoading } = useTopAgents(6);
  const {
    data: agents,
    isLoading: agentsLoading,
    isError: agentsError,
    error: agentsErrorDetail,
    refetch: refetchAgents,
  } = useRegistryList("agents");

  const approvedAgents = useMemo(
    () => (agents ?? []).filter(isApproved),
    [agents],
  );
  const workInProgress = useMemo(
    () =>
      (myAgents ?? []).filter((agent) =>
        ["draft", "pending", "rejected"].includes(
          typeof agent.status === "string" ? agent.status : "",
        ),
      ),
    [myAgents],
  );
  const trustedAgents = useMemo(
    () => approvedAgents.slice(0, 5),
    [approvedAgents],
  );
  const recentSessions = (sessions ?? []).slice(0, 4);
  const displayName =
    whoami?.name || whoami?.username || whoami?.email || "Welcome back";

  function handleSearch() {
    const query = search.trim();
    if (query) router.navigate({ to: "/agents", search: { search: query } });
  }

  return (
    <>
      <PageHeader
        title="Registry"
        breadcrumbs={[
          { label: "Registry" },
          { label: "Home" },
        ]}
      />

      <div className="page-body w-full">
        {/* ── Intent box ── */}
        <section className="mb-7 rounded-xl bg-card p-[30px] shadow-sm animate-in">
          <p className="mb-1.5 text-2xs font-medium uppercase tracking-[0.06em] text-muted-foreground">
            Start with intent
          </p>
          <h1 className="max-w-3xl text-balance text-[28px] font-medium tracking-[-0.03em]">
            What are you working on?
          </h1>
          <p className="mt-2 max-w-[680px] text-sm text-muted-foreground">
            Find an approved agent, inspect a trace, or assemble a workflow from
            trusted components.
          </p>

          <IntentSearch
            value={search}
            onChange={setSearch}
            onSubmit={handleSearch}
            placeholder='Try "review a Python service" or paste a trace ID'
            className="mt-5 max-w-[780px]"
          />

          <nav
            aria-label="Quick actions"
            className="mt-3 flex flex-wrap gap-1.5"
          >
            <IntentChip href="/agents">Browse agents</IntentChip>
            <IntentChip href="/agents/builder">Build from components</IntentChip>
            <IntentChip href="/traces">Inspect a trace</IntentChip>
            <IntentChip href="/review">Review submissions</IntentChip>
          </nav>
        </section>

        {/* ── Main grid ── */}
        <RegistryHomeGrid>
          {/* Recommendations */}
          <div className="col-span-full xl:col-span-1">
            <RecommendedForYou limit={3} />
          </div>

          {/* Your work */}
          <Panel
            title="Your work"
            subtitle="Publishing and maintenance that needs you"
            action={
              <Link
                to="/agents"
                className="text-2xs font-medium text-muted-foreground hover:text-foreground"
              >
                View all →
              </Link>
            }
          >
            <CompactRow
              icon={
                <EntityGlyph type="agent" size="sm" labelled={false} />
              }
              title={
                myAgentsLoading
                  ? "Loading your work…"
                  : workInProgress.length > 0
                    ? `${workInProgress.length} item${workInProgress.length === 1 ? "" : "s"} need attention`
                    : "Your agents are up to date"
              }
              description={
                workInProgress.length > 0
                  ? "Open drafts, pending reviews, and rejected submissions."
                  : "Review published agents or start a new release."
              }
              href="/agents"
            />
            <CompactRow
              icon={<EntityGlyph type="agent" size="sm" labelled={false} />}
              title="Build an agent"
              description="Bundle components into a portable agent."
              href="/agents/builder"
            />
            <CompactRow
              icon={<EntityGlyph type="mcp" size="sm" labelled={false} />}
              title="Browse components"
              description="Find approved reusable building blocks."
              href="/components"
            />
          </Panel>

          {/* Agents gaining adoption */}
          <Panel
            title={
              topAgents?.length
                ? "Agents gaining adoption"
                : "Trusted agents"
            }
            subtitle={
              topAgents?.length
                ? "Frequently installed agents from across the registry"
                : "Approved agents available to install now."
            }
            action={
              <Link
                to="/leaderboard"
                className="text-2xs font-medium text-muted-foreground hover:text-foreground"
              >
                Leaderboard →
              </Link>
            }
            wide
          >
            {topAgentsLoading || agentsLoading ? (
              <TableSkeleton rows={3} cols={3} />
            ) : topAgents?.length ? (
              topAgents.slice(0, 3).map((agent) => (
                <CompactRow
                  key={agent.id}
                  icon={<EntityGlyph type="agent" size="sm" labelled={false} />}
                  title={
                    agent.namespace && agent.slug
                      ? `${agent.namespace}/${agent.slug}`
                      : agent.name
                  }
                  description={agent.description}
                  meta={
                    <>
                      {compactNumber(agent.download_count)} pulls
                      <br />★{" "}
                      {agent.average_rating
                        ? agent.average_rating.toFixed(1)
                        : "New"}
                    </>
                  }
                  href={registryItemPath(agent, "agents", agent.id)}
                />
              ))
            ) : agentsError ? (
              <ErrorState
                message={agentsErrorDetail?.message}
                onRetry={() => refetchAgents()}
              />
            ) : trustedAgents.length > 0 ? (
              trustedAgents.slice(0, 3).map((agent) => (
                <CompactRow
                  key={agent.id}
                  icon={<EntityGlyph type="agent" size="sm" labelled={false} />}
                  title={
                    agent.namespace && agent.slug
                      ? `${agent.namespace}/${agent.slug}`
                      : agent.name
                  }
                  description={
                    typeof agent.description === "string"
                      ? agent.description
                      : "Approved agent"
                  }
                  href={registryItemPath(agent, "agents", agent.id)}
                />
              ))
            ) : (
              <p className="text-xs text-muted-foreground">
                Approved agents will appear here when your registry starts
                publishing.
              </p>
            )}
          </Panel>

          {/* Recent execution */}
          <Panel
            title="Recent execution"
            subtitle="Your latest captured coding sessions"
            action={
              <Link
                to="/traces"
                className="text-2xs font-medium text-muted-foreground hover:text-foreground"
              >
                All traces →
              </Link>
            }
          >
            {sessionsLoading ? (
              <TableSkeleton rows={3} cols={2} />
            ) : recentSessions.length === 0 ? (
              <div className="flex gap-3 text-xs leading-6 text-muted-foreground">
                <Activity className="mt-0.5 h-4 w-4 shrink-0" />
                Enable telemetry in a supported harness to connect registry
                assets with execution evidence.
              </div>
            ) : (
              recentSessions.map((session) => (
                <CompactRow
                  key={session.session_id}
                  icon={
                    <span className="inline-grid h-6 w-6 shrink-0 place-items-center rounded-md bg-surface-raised font-mono text-[9px] font-medium text-muted-foreground">
                      {(sessionPlatform(session) || "?")
                        .slice(0, 2)
                        .toUpperCase()}
                    </span>
                  }
                  title={sessionTitle(session)}
                  description={`${sessionPlatform(session)} · ${session.model || "Unknown model"}`}
                  meta={
                    <>
                      {formatTime(session.last_event_time)}
                      <br />
                      {compactNumber(toNumber(session.tool_result_count))} tools
                    </>
                  }
                  href={`/traces/${session.session_id}`}
                />
              ))
            )}
          </Panel>
        </RegistryHomeGrid>
      </div>
    </>
  );
}
