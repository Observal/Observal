// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { Link } from "@tanstack/react-router";
import { Play, Loader2, CheckCircle2, XCircle, Clock, AlertTriangle } from "lucide-react";
import {
	useRegistryList,
	useInsightReports,
	useGenerateInsight,
	useInsightsStatus,
	useInsightSessionCount,
} from "@/hooks/use-api";
import type { RegistryItem, InsightReportListItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layouts/page-header";
import { CardSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

function StatusBadge({ status }: { status: InsightReportListItem["status"] }) {
	switch (status) {
		case "completed":
			return (
				<span className="inline-flex items-center gap-1 text-xs font-medium text-success bg-success/10 px-2 py-0.5 rounded-full">
					<CheckCircle2 className="h-3 w-3" /> Completed
				</span>
			);
		case "running":
			return (
				<span className="inline-flex items-center gap-1 text-xs font-medium text-info bg-info/10 px-2 py-0.5 rounded-full">
					<Loader2 className="h-3 w-3 animate-spin" /> Running
				</span>
			);
		case "pending":
			return (
				<span className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
					<Clock className="h-3 w-3" /> Pending
				</span>
			);
		case "failed":
			return (
				<span className="inline-flex items-center gap-1 text-xs font-medium text-destructive bg-destructive/10 px-2 py-0.5 rounded-full">
					<XCircle className="h-3 w-3" /> Failed
				</span>
			);
	}
}

function AgentInsightCard({ agent, disabled }: { agent: RegistryItem; disabled?: boolean }) {
	const { data: reports } = useInsightReports(agent.id);
	const { data: sessionCountData, isLoading: isLoadingCount } = useInsightSessionCount(agent.id);
	const generateInsight = useGenerateInsight();

	const latest = (reports ?? [])[0] as InsightReportListItem | undefined;
	const reportCount = (reports ?? []).length;
	const availableSessions = sessionCountData?.session_count ?? 0;

	return (
		<div className="rounded-md border border-border bg-card p-4 flex flex-col gap-3 hover:bg-muted/30 transition-colors">
			<div className="flex items-start justify-between gap-2">
				<div className="min-w-0">
					<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold truncate">
						{agent.name}
					</h3>
					{agent.description && (
						<p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
							{agent.description}
						</p>
					)}
				</div>
				{latest && <StatusBadge status={latest.status} />}
			</div>

			<div className="flex items-center gap-3 text-xs text-muted-foreground">
				<span className="font-[family-name:var(--font-mono)] tabular-nums">
					{isLoadingCount ? "…" : availableSessions} sessions available
				</span>
				{latest && (
					<>
						<span>{new Date(latest.created_at).toLocaleDateString()}</span>
						{reportCount > 1 && <span>{reportCount} reports</span>}
					</>
				)}
			</div>

			<div className="flex items-center gap-2 mt-auto pt-1 flex-nowrap min-w-0">
				{latest?.status === "completed" && (
					<Link to="/insights/$reportId" params={{ reportId: latest.id }} className="flex-1">
						<Button variant="outline" size="sm" className="w-full h-7 text-xs">
							View Report
						</Button>
					</Link>
				)}
				{(latest?.status === "pending" || latest?.status === "running") && (
					<div className="flex-1 flex items-center gap-2 px-2 py-1 rounded bg-muted/50 border border-border">
						<Loader2 className="h-3 w-3 animate-spin text-info" />
						<span className="text-xs text-muted-foreground">
							{latest.status === "pending"
								? "Queued..."
								: "Generating report..."}
						</span>
					</div>
				)}
				<Button
					variant="ghost"
					size="sm"
					className="h-7 text-xs gap-1 shrink-0"
					disabled={
						disabled ||
						(!isLoadingCount && availableSessions === 0) ||
						generateInsight.isPending ||
						latest?.status === "pending" ||
						latest?.status === "running"
					}
					onClick={() => generateInsight.mutate({ agentId: agent.id })}
				>
					<Play className="h-3 w-3" />
					Generate
				</Button>
			</div>
		</div>
	);
}

export default function InsightsPage() {
	const { data: agents, isLoading, isError } = useRegistryList("agents");
	const { data: insightsStatus } = useInsightsStatus();
	const notConfigured = insightsStatus && !insightsStatus.available;

	return (
		<>
			<PageHeader title="Agent Insights" />

			<div className="p-4 sm:p-6 space-y-4">
				{notConfigured && (
					<div className="flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-600 dark:text-amber-400">
						<AlertTriangle className="h-4 w-4 shrink-0" />
						<span>{insightsStatus.reason}</span>
					</div>
				)}
				{isLoading && (
					<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
						{Array.from({ length: 6 }).map((_, i) => (
							<CardSkeleton key={i} />
						))}
					</div>
				)}

				{isError && <ErrorState message="Failed to load agents" />}

				{!isLoading && !isError && (!agents || agents.length === 0) && (
					<EmptyState
						title="No agents registered"
						description="Register agents in the registry to generate performance insights."
					/>
				)}

				{!isLoading && !isError && agents && agents.length > 0 && (
					<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
						{agents.map((agent) => (
							<AgentInsightCard key={agent.id} agent={agent} disabled={!!notConfigured} />
						))}
					</div>
				)}
			</div>
		</>
	);
}
