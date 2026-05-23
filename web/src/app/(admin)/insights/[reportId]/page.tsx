// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { use } from "react";
import Link from "next/link";
import {
	ArrowLeft,
	Lightbulb,
	Loader2,
	CheckCircle2,
	XCircle,
	Clock,
	Zap,
	Users,
	Timer,
	AlertTriangle,
	Wrench,
	TrendingUp,
	TrendingDown,
	DollarSign,
	Database,
	ThumbsUp,
	Sparkles,
	ArrowUpRight,
	ArrowDownRight,
	Target,
	Shield,
	Download,
} from "lucide-react";
import { useInsightReport } from "@/hooks/use-api";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layouts/page-header";
import { ErrorState } from "@/components/shared/error-state";
import { insights } from "@/lib/api";
import type { InsightReport } from "@/lib/types";

// ── Status Indicator ──────────────────────────────────────────────────────

function StatusIndicator({ status }: { status: InsightReport["status"] }) {
	switch (status) {
		case "completed":
			return (
				<div className="inline-flex items-center gap-1.5 text-sm font-medium text-success">
					<CheckCircle2 className="h-4 w-4" /> Completed
				</div>
			);
		case "running":
			return (
				<div className="inline-flex items-center gap-1.5 text-sm font-medium text-info">
					<Loader2 className="h-4 w-4 animate-spin" /> Generating report...
				</div>
			);
		case "pending":
			return (
				<div className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
					<Clock className="h-4 w-4" /> Queued
				</div>
			);
		case "failed":
			return (
				<div className="inline-flex items-center gap-1.5 text-sm font-medium text-destructive">
					<XCircle className="h-4 w-4" /> Failed
				</div>
			);
	}
}

// ── Metric Card ──────────────────────────────────────────────────────────

function MetricCard({
	label,
	value,
	icon: Icon,
	subtext,
}: {
	label: string;
	value: string | number;
	icon: React.ComponentType<{ className?: string }>;
	subtext?: string;
}) {
	return (
		<div className="rounded-lg border border-border bg-card p-4">
			<div className="flex items-center gap-2 text-muted-foreground mb-1">
				<Icon className="h-4 w-4" />
				<span className="text-xs font-medium uppercase tracking-wider">
					{label}
				</span>
			</div>
			<div className="font-[family-name:var(--font-mono)] text-2xl font-bold tabular-nums">
				{value}
			</div>
			{subtext && (
				<div className="text-xs text-muted-foreground mt-1">{subtext}</div>
			)}
		</div>
	);
}

// ── At a Glance (executive summary) ──────────────────────────────────────

function AtAGlance({ data }: { data: unknown }) {
	if (!data) return null;

	// Handle V1 string format
	if (typeof data === "string") {
		return (
			<div className="rounded-lg border border-primary-accent/20 bg-primary-accent/5 p-5">
				<div className="flex items-center gap-2 mb-2">
					<Lightbulb className="h-4 w-4 text-primary-accent" />
					<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
						At a Glance
					</h3>
				</div>
				<p className="text-sm leading-relaxed">{data}</p>
			</div>
		);
	}

	// V2 structured format
	const obj = data as Record<string, string>;
	const sections = [
		{ key: "whats_working", label: "What's working", color: "text-success" },
		{
			key: "whats_hindering",
			label: "What's hindering",
			color: "text-destructive",
		},
		{ key: "quick_win", label: "Quick win", color: "text-primary-accent" },
	];

	return (
		<div className="rounded-lg border border-primary-accent/20 bg-primary-accent/5 p-5">
			<div className="flex items-center justify-between mb-4">
				<div className="flex items-center gap-2">
					<Lightbulb className="h-4 w-4 text-primary-accent" />
					<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
						At a Glance
					</h3>
				</div>
				{obj.health && (
					<span
						className={`text-xs px-2 py-0.5 rounded-full font-medium ${
							obj.health === "healthy"
								? "bg-success/20 text-success"
								: obj.health === "concerning"
									? "bg-destructive/20 text-destructive"
									: "bg-warning/20 text-warning"
						}`}
					>
						{obj.health}
					</span>
				)}
			</div>
			<div className="space-y-3">
				{sections.map(
					({ key, label, color }) =>
						obj[key] && (
							<div key={key} className="flex gap-3 text-sm">
								<span className={`font-semibold shrink-0 ${color}`}>
									{label}:
								</span>
								<span className="text-foreground/80">{obj[key]}</span>
							</div>
						),
				)}
			</div>
		</div>
	);
}

// ── Usage Patterns Section ──────────────────────────────────────────────

function UsagePatterns({ data }: { data: unknown }) {
	if (!data) return null;

	// Handle V1 array/string format
	if (Array.isArray(data) || typeof data === "string") {
		return (
			<GenericBulletSection
				title="Usage Patterns"
				icon={TrendingUp}
				items={data}
			/>
		);
	}

	const obj = data as Record<string, unknown>;
	const narrative = obj.narrative as string | undefined;
	const toolDist = obj.tool_distribution as
		| { tool: string; calls: number; error_rate: number }[]
		| undefined;
	const sessionProfile = obj.session_profile as
		| Record<string, unknown>
		| undefined;

	return (
		<div className="rounded-lg border border-border bg-card">
			<div className="flex items-center gap-2 px-5 py-3 border-b border-border">
				<TrendingUp className="h-4 w-4 text-primary-accent" />
				<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
					How the Agent Is Used
				</h3>
			</div>
			<div className="px-5 py-4 space-y-4">
				{narrative && (
					<p className="text-sm leading-relaxed text-foreground/80">
						{narrative}
					</p>
				)}

				{/* Session profile summary */}
				{sessionProfile && (
					<div className="flex flex-wrap gap-4 py-2">
						{sessionProfile.avg_duration_minutes != null && (
							<div className="text-center">
								<div className="text-lg font-bold tabular-nums">{`${sessionProfile.avg_duration_minutes}m`}</div>
								<div className="text-xs text-muted-foreground">
									avg duration
								</div>
							</div>
						)}
						{sessionProfile.avg_tool_calls != null && (
							<div className="text-center">
								<div className="text-lg font-bold tabular-nums">{`${sessionProfile.avg_tool_calls}`}</div>
								<div className="text-xs text-muted-foreground">
									avg tool calls
								</div>
							</div>
						)}
						{sessionProfile.session_type != null && (
							<div className="text-center">
								<div className="text-lg font-bold">
									{`${sessionProfile.session_type}`.replace(/_/g, " ")}
								</div>
								<div className="text-xs text-muted-foreground">
									typical session
								</div>
							</div>
						)}
					</div>
				)}

				{/* Tool distribution bars */}
				{toolDist && toolDist.length > 0 && (
					<div className="space-y-2">
						<div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
							Tool Usage
						</div>
						{toolDist.slice(0, 6).map((tool) => {
							const maxCalls = Math.max(...toolDist.map((t) => t.calls));
							const pct = maxCalls > 0 ? (tool.calls / maxCalls) * 100 : 0;
							return (
								<div
									key={tool.tool}
									className="flex items-center gap-3 text-sm"
								>
									<span className="w-20 truncate font-[family-name:var(--font-mono)] text-xs">
										{tool.tool}
									</span>
									<div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
										<div
											className="h-full bg-primary-accent/60 rounded-full"
											style={{ width: `${pct}%` }}
										/>
									</div>
									<span className="w-12 text-right tabular-nums text-xs">
										{tool.calls}
									</span>
									{tool.error_rate > 0 && (
										<span className="text-xs text-destructive">
											{tool.error_rate.toFixed(0)}% err
										</span>
									)}
								</div>
							);
						})}
					</div>
				)}
			</div>
		</div>
	);
}

// ── Strengths Section ────────────────────────────────────────────────────

function StrengthsSection({ data }: { data: unknown }) {
	if (!data) return null;

	if (Array.isArray(data) || typeof data === "string") {
		return (
			<GenericBulletSection
				title="What Works Well"
				icon={ThumbsUp}
				items={data}
				color="text-success"
			/>
		);
	}

	const obj = data as Record<string, unknown>;
	const intro = obj.intro as string | undefined;
	const strengths = obj.strengths as
		| { title: string; description: string }[]
		| undefined;

	if (!strengths || strengths.length === 0) return null;

	return (
		<div className="rounded-lg border border-border bg-card">
			<div className="flex items-center gap-2 px-5 py-3 border-b border-border">
				<ThumbsUp className="h-4 w-4 text-primary-accent" />
				<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
					What Works Well
				</h3>
			</div>
			<div className="px-5 py-4 space-y-3">
				{intro && <p className="text-sm text-muted-foreground">{intro}</p>}
				<div className="space-y-3">
					{strengths.map((s, i) => (
						<div
							key={i}
							className="rounded-md border border-success/20 bg-success/5 p-3"
						>
							<div className="font-medium text-sm text-success mb-1">
								{s.title}
							</div>
							<div className="text-sm text-foreground/70">{s.description}</div>
						</div>
					))}
				</div>
			</div>
		</div>
	);
}

// ── Friction Section ─────────────────────────────────────────────────────

function FrictionSection({ data }: { data: unknown }) {
	if (!data) return null;

	if (Array.isArray(data) || typeof data === "string") {
		return (
			<GenericBulletSection
				title="Where Things Go Wrong"
				icon={AlertTriangle}
				items={data}
				color="text-destructive"
			/>
		);
	}

	const obj = data as Record<string, unknown>;
	const intro = obj.intro as string | undefined;
	const categories = obj.categories as
		| {
				title: string;
				severity: string;
				description: string;
				evidence: string;
				impact: string;
		  }[]
		| undefined;

	if (!categories || categories.length === 0) return null;

	return (
		<div className="rounded-lg border border-border bg-card">
			<div className="flex items-center gap-2 px-5 py-3 border-b border-border">
				<AlertTriangle className="h-4 w-4 text-primary-accent" />
				<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
					Where Things Go Wrong
				</h3>
			</div>
			<div className="px-5 py-4 space-y-3">
				{intro && <p className="text-sm text-muted-foreground">{intro}</p>}
				<div className="space-y-3">
					{categories.map((cat, i) => (
						<div
							key={i}
							className="rounded-md border border-destructive/20 bg-destructive/5 p-3"
						>
							<div className="flex items-center justify-between mb-1">
								<div className="font-medium text-sm text-destructive">
									{cat.title}
								</div>
								<span
									className={`text-xs px-2 py-0.5 rounded-full ${
										cat.severity === "high"
											? "bg-destructive/20 text-destructive"
											: cat.severity === "medium"
												? "bg-warning/20 text-warning"
												: "bg-muted text-muted-foreground"
									}`}
								>
									{cat.severity}
								</span>
							</div>
							<div className="text-sm text-foreground/70 mb-1">
								{cat.description}
							</div>
							{cat.evidence && (
								<div className="text-xs text-muted-foreground font-[family-name:var(--font-mono)] mt-2 p-2 bg-muted/30 rounded">
									{cat.evidence}
								</div>
							)}
						</div>
					))}
				</div>
			</div>
		</div>
	);
}

// ── Suggestions Section ──────────────────────────────────────────────────

function SuggestionsSection({ data }: { data: unknown }) {
	if (!data) return null;

	if (Array.isArray(data) || typeof data === "string") {
		return (
			<GenericBulletSection
				title="Suggestions"
				icon={Lightbulb}
				items={data}
				numbered
			/>
		);
	}

	const obj = data as Record<string, unknown>;
	const intro = obj.intro as string | undefined;
	const items = obj.items as
		| { title: string; action: string; why: string; priority: string }[]
		| undefined;

	if (!items || items.length === 0) return null;

	return (
		<div className="rounded-lg border border-border bg-card">
			<div className="flex items-center gap-2 px-5 py-3 border-b border-border">
				<Lightbulb className="h-4 w-4 text-primary-accent" />
				<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
					Suggestions
				</h3>
			</div>
			<div className="px-5 py-4 space-y-3">
				{intro && <p className="text-sm text-muted-foreground mb-3">{intro}</p>}
				{items.map((item, i) => (
					<div
						key={i}
						className="rounded-md border border-border bg-muted/10 p-3"
					>
						<div className="flex items-center justify-between mb-1">
							<div className="font-medium text-sm">{item.title}</div>
							<span
								className={`text-xs px-2 py-0.5 rounded-full ${
									item.priority === "high"
										? "bg-destructive/20 text-destructive"
										: item.priority === "medium"
											? "bg-warning/20 text-warning"
											: "bg-muted text-muted-foreground"
								}`}
							>
								{item.priority}
							</span>
						</div>
						<div className="text-sm text-foreground/80 mt-1">{item.action}</div>
						{item.why && (
							<div className="text-xs text-muted-foreground mt-2 italic">
								{item.why}
							</div>
						)}
					</div>
				))}
			</div>
		</div>
	);
}

// ── Token/Cost Section ──────────────────────────────────────────────────

function TokenSection({
	data,
	metrics,
}: {
	data: unknown;
	metrics: InsightReport["metrics"];
}) {
	if (!data && !metrics?.cost) return null;

	// If we have structured V2 data
	if (data && typeof data === "object" && !Array.isArray(data)) {
		const obj = data as Record<string, unknown>;
		const summary = obj.summary as string | undefined;
		const costMetrics = obj.metrics as
			| {
					total_cost_usd: number;
					cost_per_session: number;
					cache_efficiency_pct: number;
			  }
			| undefined;
		const opportunities = obj.opportunities as
			| { title: string; description: string; estimated_savings: string }[]
			| undefined;

		return (
			<div className="rounded-lg border border-border bg-card">
				<div className="flex items-center gap-2 px-5 py-3 border-b border-border">
					<DollarSign className="h-4 w-4 text-primary-accent" />
					<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
						Cost & Token Efficiency
					</h3>
				</div>
				<div className="px-5 py-4 space-y-4">
					{summary && <p className="text-sm text-foreground/80">{summary}</p>}

					{costMetrics && (
						<div className="grid grid-cols-3 gap-3">
							<div className="text-center p-2 rounded bg-muted/30">
								<div className="text-lg font-bold">
									${costMetrics.total_cost_usd?.toFixed(4)}
								</div>
								<div className="text-xs text-muted-foreground">total cost</div>
							</div>
							<div className="text-center p-2 rounded bg-muted/30">
								<div className="text-lg font-bold">
									${costMetrics.cost_per_session?.toFixed(4)}
								</div>
								<div className="text-xs text-muted-foreground">per session</div>
							</div>
							<div className="text-center p-2 rounded bg-muted/30">
								<div className="text-lg font-bold">
									{costMetrics.cache_efficiency_pct?.toFixed(0)}%
								</div>
								<div className="text-xs text-muted-foreground">
									cache efficiency
								</div>
							</div>
						</div>
					)}

					{opportunities && opportunities.length > 0 && (
						<div className="space-y-2">
							<div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
								Optimization Opportunities
							</div>
							{opportunities.map((opp, i) => (
								<div
									key={i}
									className="flex gap-3 text-sm p-2 rounded bg-muted/20"
								>
									<span className="text-primary-accent font-semibold shrink-0">
										{i + 1}.
									</span>
									<div>
										<span className="font-medium">{opp.title}</span>
										<span className="text-foreground/60">
											{" "}
											— {opp.description}
										</span>
										{opp.estimated_savings && (
											<span className="text-success ml-1">
												({opp.estimated_savings})
											</span>
										)}
									</div>
								</div>
							))}
						</div>
					)}
				</div>
			</div>
		);
	}

	// Fallback: render from metrics.cost
	if (metrics?.cost && metrics.cost.total_cost_usd > 0) {
		const cost = metrics.cost;
		return (
			<div className="rounded-lg border border-border bg-card">
				<div className="flex items-center gap-2 px-5 py-3 border-b border-border">
					<DollarSign className="h-4 w-4 text-primary-accent" />
					<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
						Cost Summary
					</h3>
				</div>
				<div className="px-5 py-4">
					<div className="grid grid-cols-2 md:grid-cols-4 gap-3">
						<MetricCard
							label="Total Cost"
							value={`$${cost.total_cost_usd.toFixed(4)}`}
							icon={DollarSign}
						/>
						<MetricCard
							label="Per Session"
							value={`$${cost.avg_cost_per_session.toFixed(4)}`}
							icon={DollarSign}
						/>
						<MetricCard
							label="Cache Efficiency"
							value={`${(cost.cache_efficiency_ratio * 100).toFixed(0)}%`}
							icon={Database}
						/>
						<MetricCard
							label="P90 Session"
							value={`$${cost.p90_session_cost.toFixed(4)}`}
							icon={DollarSign}
						/>
					</div>
				</div>
			</div>
		);
	}

	// V1 bullets fallback
	if (Array.isArray(data) || typeof data === "string") {
		return (
			<GenericBulletSection
				title="Token Optimization"
				icon={DollarSign}
				items={data}
			/>
		);
	}

	return null;
}

// ── User Experience Section ─────────────────────────────────────────────

function UserExperienceSection({ data }: { data: unknown }) {
	if (!data) return null;

	if (Array.isArray(data) || typeof data === "string") {
		return (
			<GenericBulletSection title="User Experience" icon={Users} items={data} />
		);
	}

	const obj = data as Record<string, unknown>;
	const narrative = obj.narrative as string | undefined;
	const signals = obj.signals as
		| { signal: string; interpretation: string }[]
		| undefined;
	const satisfaction = obj.satisfaction_indicators as
		| Record<string, string>
		| undefined;

	return (
		<div className="rounded-lg border border-border bg-card">
			<div className="flex items-center gap-2 px-5 py-3 border-b border-border">
				<Users className="h-4 w-4 text-primary-accent" />
				<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
					User Experience
				</h3>
			</div>
			<div className="px-5 py-4 space-y-4">
				{narrative && (
					<p className="text-sm leading-relaxed text-foreground/80">
						{narrative}
					</p>
				)}

				{satisfaction && (
					<div className="flex flex-wrap gap-4 py-2 px-3 rounded bg-muted/20">
						{satisfaction.completion_rate &&
							satisfaction.completion_rate !== "N/A" && (
								<div className="text-center">
									<div className="text-sm font-bold">
										{satisfaction.completion_rate}
									</div>
									<div className="text-xs text-muted-foreground">
										completion
									</div>
								</div>
							)}
						{satisfaction.interruption_rate &&
							satisfaction.interruption_rate !== "N/A" && (
								<div className="text-center">
									<div className="text-sm font-bold">
										{satisfaction.interruption_rate}
									</div>
									<div className="text-xs text-muted-foreground">
										interruptions
									</div>
								</div>
							)}
					</div>
				)}

				{signals && signals.length > 0 && (
					<div className="space-y-2">
						{signals.map((s, i) => (
							<div key={i} className="text-sm flex gap-2">
								<span className="text-muted-foreground shrink-0">•</span>
								<div>
									<span className="font-medium">{s.signal}</span>
									{s.interpretation && (
										<span className="text-muted-foreground">
											{" "}
											— {s.interpretation}
										</span>
									)}
								</div>
							</div>
						))}
					</div>
				)}
			</div>
		</div>
	);
}

// ── Regression Section ──────────────────────────────────────────────────

function RegressionSection({
	data,
	regressions,
}: {
	data: unknown;
	regressions?: unknown[];
}) {
	// Handle structured regression data from narrative
	if (data && typeof data === "object" && !Array.isArray(data)) {
		const obj = data as Record<string, unknown>;
		if (obj.has_previous_data === false) return null;
		const changes = obj.changes as
			| {
					metric: string;
					direction: string;
					previous_value: string;
					current_value: string;
					magnitude_pct: number;
					significance: string;
			  }[]
			| undefined;
		if (!changes || changes.length === 0) return null;

		return (
			<div className="rounded-lg border border-border bg-card">
				<div className="flex items-center gap-2 px-5 py-3 border-b border-border">
					<TrendingDown className="h-4 w-4 text-primary-accent" />
					<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
						Changes vs Previous Period
					</h3>
				</div>
				<div className="px-5 py-4 space-y-2">
					{obj.summary ? (
						<p className="text-sm text-muted-foreground mb-3">
							{String(obj.summary)}
						</p>
					) : null}
					{changes.map((c, i) => (
						<div key={i} className="flex items-center gap-3 text-sm">
							{c.direction === "improved" ? (
								<ArrowUpRight className="h-4 w-4 text-success shrink-0" />
							) : c.direction === "degraded" ? (
								<ArrowDownRight className="h-4 w-4 text-destructive shrink-0" />
							) : (
								<span className="w-4 h-4 shrink-0" />
							)}
							<span className="flex-1">
								<span className="font-medium">
									{c.metric.replace(/_/g, " ")}
								</span>{" "}
								<span
									className={
										c.direction === "improved"
											? "text-success"
											: c.direction === "degraded"
												? "text-destructive"
												: "text-muted-foreground"
									}
								>
									{c.direction} {Math.abs(c.magnitude_pct).toFixed(1)}%
								</span>
								<span className="text-muted-foreground ml-2">
									({c.previous_value} → {c.current_value})
								</span>
							</span>
							{c.significance && (
								<span
									className={`text-xs px-2 py-0.5 rounded-full ${
										c.significance === "meaningful"
											? "bg-primary-accent/20 text-primary-accent"
											: "bg-muted text-muted-foreground"
									}`}
								>
									{c.significance}
								</span>
							)}
						</div>
					))}
				</div>
			</div>
		);
	}

	// Handle V1 regressions array from metrics
	if (regressions && regressions.length > 0) {
		return (
			<div className="rounded-lg border border-border bg-card">
				<div className="flex items-center gap-2 px-5 py-3 border-b border-border">
					<TrendingDown className="h-4 w-4 text-primary-accent" />
					<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
						Changes vs Previous Period
					</h3>
				</div>
				<div className="px-5 py-4 space-y-2">
					{(
						regressions as {
							metric: string;
							direction: string;
							magnitude: number;
							current_value: number;
							previous_value: number;
							severity: string;
						}[]
					).map((r, i) => (
						<div key={i} className="flex items-center gap-3 text-sm">
							{r.direction === "improved" ? (
								<ArrowUpRight className="h-4 w-4 text-success shrink-0" />
							) : (
								<ArrowDownRight className="h-4 w-4 text-destructive shrink-0" />
							)}
							<span className="flex-1">
								<span className="font-medium">
									{r.metric.replace(/_/g, " ")}
								</span>{" "}
								<span
									className={
										r.direction === "improved"
											? "text-success"
											: "text-destructive"
									}
								>
									{r.direction} {Math.abs(r.magnitude).toFixed(1)}%
								</span>
								<span className="text-muted-foreground ml-2">
									({r.previous_value} → {r.current_value})
								</span>
							</span>
						</div>
					))}
				</div>
			</div>
		);
	}

	// V1 bullets
	if (Array.isArray(data) || typeof data === "string") {
		const items = Array.isArray(data) ? data : [data];
		if (
			items.length === 1 &&
			typeof items[0] === "string" &&
			items[0].includes("No previous")
		)
			return null;
		return (
			<GenericBulletSection
				title="Regression Detection"
				icon={TrendingDown}
				items={data}
			/>
		);
	}

	return null;
}

// ── Fun Ending ──────────────────────────────────────────────────────────

function FunEnding({ data }: { data: unknown }) {
	if (!data) return null;

	if (typeof data === "string") {
		return (
			<div className="rounded-lg border border-border bg-muted/10 p-5">
				<div className="flex items-center gap-2 mb-2">
					<Sparkles className="h-4 w-4 text-primary-accent" />
					<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
						Notable Moment
					</h3>
				</div>
				<p className="text-sm leading-relaxed text-muted-foreground italic">
					{data}
				</p>
			</div>
		);
	}

	const obj = data as { headline?: string; detail?: string };
	if (!obj.headline && !obj.detail) return null;

	return (
		<div className="rounded-lg border border-border bg-muted/10 p-5 text-center">
			<Sparkles className="h-5 w-5 text-primary-accent mx-auto mb-2" />
			{obj.headline && (
				<div className="font-[family-name:var(--font-display)] text-sm font-semibold mb-1">
					{obj.headline}
				</div>
			)}
			{obj.detail && (
				<p className="text-sm text-muted-foreground italic">{obj.detail}</p>
			)}
		</div>
	);
}

// ── Tools Table ─────────────────────────────────────────────────────────

function ToolsTable({
	tools,
}: {
	tools: { name: string; invocations: string; errors: string }[] | undefined;
}) {
	if (!tools || tools.length === 0) return null;

	return (
		<div className="rounded-lg border border-border bg-card overflow-hidden">
			<div className="flex items-center gap-2 px-5 py-3 border-b border-border">
				<Wrench className="h-4 w-4 text-primary-accent" />
				<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
					Top Tools
				</h3>
			</div>
			<div className="overflow-x-auto">
				<table className="w-full text-sm">
					<thead>
						<tr className="border-b border-border text-xs text-muted-foreground uppercase tracking-wider">
							<th className="text-left px-5 py-2 font-medium">Tool</th>
							<th className="text-right px-5 py-2 font-medium">Calls</th>
							<th className="text-right px-5 py-2 font-medium">Errors</th>
							<th className="text-right px-5 py-2 font-medium">Error Rate</th>
						</tr>
					</thead>
					<tbody>
						{tools.slice(0, 10).map((tool) => {
							const invocations = Number(tool.invocations) || 0;
							const errors = Number(tool.errors) || 0;
							const errorRate =
								invocations > 0
									? ((errors / invocations) * 100).toFixed(1)
									: "0.0";
							return (
								<tr
									key={tool.name}
									className="border-b border-border last:border-0 hover:bg-muted/30"
								>
									<td className="px-5 py-2.5 font-[family-name:var(--font-mono)] text-xs">
										{tool.name}
									</td>
									<td className="px-5 py-2.5 text-right tabular-nums">
										{invocations.toLocaleString()}
									</td>
									<td className="px-5 py-2.5 text-right tabular-nums">
										{errors}
									</td>
									<td className="px-5 py-2.5 text-right tabular-nums">
										<span
											className={
												Number(errorRate) > 10
													? "text-destructive font-medium"
													: ""
											}
										>
											{errorRate}%
										</span>
									</td>
								</tr>
							);
						})}
					</tbody>
				</table>
			</div>
		</div>
	);
}

// ── Error Categories ────────────────────────────────────────────────────

function ErrorCategories({
	toolErrors,
}: {
	toolErrors:
		| { total_categorized: number; categories: Record<string, number> }
		| undefined;
}) {
	if (!toolErrors || toolErrors.total_categorized === 0) return null;

	const categories = Object.entries(toolErrors.categories).sort(
		([, a], [, b]) => b - a,
	);
	const labelMap: Record<string, string> = {
		command_failed: "Command Failed",
		user_rejected: "User Rejected",
		edit_failed: "Edit Failed",
		file_changed: "File Changed",
		file_too_large: "File Too Large",
		file_not_found: "File Not Found",
		timeout: "Timeout",
		permission_denied: "Permission Denied",
		other: "Other",
	};

	return (
		<div className="rounded-lg border border-border bg-card overflow-hidden">
			<div className="flex items-center gap-2 px-5 py-3 border-b border-border">
				<Shield className="h-4 w-4 text-primary-accent" />
				<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
					Error Categories ({toolErrors.total_categorized} total)
				</h3>
			</div>
			<div className="px-5 py-4 space-y-2">
				{categories.map(([cat, count]) => {
					const pct = ((count / toolErrors.total_categorized) * 100).toFixed(0);
					return (
						<div key={cat} className="flex items-center gap-3 text-sm">
							<span className="w-32 truncate text-muted-foreground">
								{labelMap[cat] ?? cat}
							</span>
							<div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
								<div
									className="h-full bg-destructive/60 rounded-full"
									style={{ width: `${pct}%` }}
								/>
							</div>
							<span className="w-16 text-right tabular-nums text-xs">
								{count} ({pct}%)
							</span>
						</div>
					);
				})}
			</div>
		</div>
	);
}

// ── Generic Bullet fallback (V1 compatibility) ──────────────────────────

function GenericBulletSection({
	title,
	icon: Icon,
	items,
	color,
	numbered,
}: {
	title: string;
	icon: React.ComponentType<{ className?: string }>;
	items: unknown[] | string | undefined;
	color?: string;
	numbered?: boolean;
}) {
	if (!items) return null;
	const list = Array.isArray(items) ? items : [items];
	if (list.length === 0) return null;

	return (
		<div className="rounded-lg border border-border bg-card">
			<div className="flex items-center gap-2 px-5 py-3 border-b border-border">
				<Icon className="h-4 w-4 text-primary-accent" />
				<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
					{title}
				</h3>
			</div>
			<div className="px-5 py-4">
				<ul className="space-y-2">
					{list.map((item, i) => (
						<li key={i} className="flex gap-2 text-sm">
							{numbered ? (
								<span className="text-primary-accent font-semibold mt-0.5 shrink-0">
									{i + 1}.
								</span>
							) : (
								<span
									className={`mt-0.5 shrink-0 ${color || "text-muted-foreground"}`}
								>
									•
								</span>
							)}
							<span>{formatItem(item)}</span>
						</li>
					))}
				</ul>
			</div>
		</div>
	);
}

function formatItem(item: unknown): string {
	if (typeof item === "string") return item;
	if (item && typeof item === "object") {
		const obj = item as Record<string, unknown>;
		if (obj.action) {
			const prefix = obj.type ? `[${obj.type}] ` : "";
			const suffix = obj.priority ? ` (${obj.priority})` : "";
			return `${prefix}${obj.action}${suffix}`;
		}
		return (
			Object.values(obj)
				.filter((v) => typeof v === "string")
				.join(" — ") || JSON.stringify(obj)
		);
	}
	return String(item);
}

// ── Main Report Content ─────────────────────────────────────────────────

function ReportContent({ report }: { report: InsightReport }) {
	const metrics = report.metrics;
	const narrative = report.narrative;

	const totalSessions = Number(metrics?.overview?.total_sessions) || 0;
	const uniqueUsers = Number(metrics?.overview?.unique_users) || 0;
	const totalTokens = Number(metrics?.tokens?.total_tokens) || 0;
	const avgDuration = Number(metrics?.duration?.avg_duration_seconds) || 0;
	const toolCalls = Number(metrics?.errors?.total_tool_calls) || 0;

	const formatTokens = (n: number) => {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return n.toString();
	};

	const formatDuration = (seconds: number) => {
		if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`;
		if (seconds >= 60) return `${(seconds / 60).toFixed(0)}m`;
		return `${seconds.toFixed(0)}s`;
	};

	return (
		<div className="space-y-6">
			{/* At a Glance */}
			<AtAGlance data={narrative?.at_a_glance} />

			{/* Metrics Grid */}
			<div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
				<MetricCard label="Sessions" value={totalSessions} icon={Zap} />
				<MetricCard label="Users" value={uniqueUsers} icon={Users} />
				<MetricCard
					label="Tokens"
					value={formatTokens(totalTokens)}
					icon={Database}
				/>
				<MetricCard label="Tool Calls" value={toolCalls} icon={Wrench} />
				<MetricCard
					label="Avg Duration"
					value={formatDuration(avgDuration)}
					icon={Timer}
				/>
			</div>

			{/* Usage Patterns */}
			<UsagePatterns data={narrative?.usage_patterns} />

			{/* What Works */}
			<StrengthsSection data={narrative?.what_works} />

			{/* Friction */}
			<FrictionSection data={narrative?.friction_analysis} />

			{/* Suggestions */}
			<SuggestionsSection data={narrative?.suggestions} />

			{/* Cost & Tokens */}
			<TokenSection data={narrative?.token_optimization} metrics={metrics} />

			{/* User Experience */}
			<UserExperienceSection data={narrative?.user_experience} />

			{/* Tools Table */}
			<ToolsTable tools={metrics?.tools} />

			{/* Error Categories */}
			<ErrorCategories toolErrors={metrics?.tool_errors} />

			{/* Regression Detection */}
			<RegressionSection
				data={narrative?.regression_detection}
				regressions={narrative?.regressions}
			/>

			{/* Fun Ending */}
			<FunEnding data={narrative?.fun_ending} />

			{/* No narrative fallback */}
			{!narrative && metrics && (
				<div className="rounded-lg border border-border bg-muted/30 p-5 text-center">
					<p className="text-sm text-muted-foreground">
						Narrative analysis unavailable. Configure a model to enable
						LLM-powered insights.
					</p>
				</div>
			)}
		</div>
	);
}

// ── Page Component ──────────────────────────────────────────────────────

export default function InsightReportPage({
	params,
}: {
	params: Promise<{ reportId: string }>;
}) {
	const { reportId } = use(params);
	const { data: report, isLoading, isError } = useInsightReport(reportId);

	return (
		<>
			<PageHeader
				title="Insight Report"
				actionButtonsRight={
					<div className="flex items-center gap-2">
						{report?.status === "completed" && (
							<Button
								variant="outline"
								size="sm"
								className="gap-1.5"
								onClick={() => insights.exportHtml(reportId)}
							>
								<Download className="h-4 w-4" /> Export HTML
							</Button>
						)}
						<Link href="/insights">
							<Button variant="ghost" size="sm" className="gap-1.5">
								<ArrowLeft className="h-4 w-4" /> Back
							</Button>
						</Link>
					</div>
				}
			/>

			<div className="p-4 sm:p-6 w-full">
				{isLoading && (
					<div className="flex items-center justify-center py-20">
						<Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
					</div>
				)}

				{isError && <ErrorState message="Failed to load report" />}

				{report && (
					<div className="space-y-6">
						{/* Header with status and metadata */}
						<div className="flex items-center justify-between">
							<StatusIndicator status={report.status} />
							<div className="text-xs text-muted-foreground space-x-3">
								<span>
									{new Date(report.period_start).toLocaleDateString()} -{" "}
									{new Date(report.period_end).toLocaleDateString()}
								</span>
								{report.sessions_analyzed > 0 && (
									<span>{report.sessions_analyzed} sessions analyzed</span>
								)}
							</div>
						</div>

						{/* Loading state */}
						{(report.status === "pending" || report.status === "running") && (
							<div className="flex flex-col items-center justify-center py-16 gap-3">
								<Loader2 className="h-8 w-8 animate-spin text-primary-accent" />
								<p className="text-sm text-muted-foreground">
									{report.status === "pending"
										? "Waiting in queue..."
										: "Computing metrics and generating analysis..."}
								</p>
							</div>
						)}

						{/* Error state */}
						{report.status === "failed" && (
							<div className="rounded-lg border border-destructive/30 bg-destructive/5 p-5">
								<p className="text-sm font-medium text-destructive">
									Report generation failed
								</p>
								{report.error_message && (
									<p className="text-xs text-muted-foreground mt-1 font-[family-name:var(--font-mono)]">
										{report.error_message}
									</p>
								)}
							</div>
						)}

						{/* Completed: show content */}
						{report.status === "completed" && <ReportContent report={report} />}
					</div>
				)}
			</div>
		</>
	);
}
