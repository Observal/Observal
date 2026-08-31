// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * Token / credit usage summary for the current user's sessions.
 *
 * Harnesses meter differently: most report raw input/output token counts, while
 * Kiro only reports credits. The server sets `has_token_data` / `has_credit_data`
 * so this component can pick the right presentation instead of rendering a
 * section full of misleading zeros.
 */

import { useMemo } from "react";
import {
	Area,
	AreaChart,
	CartesianGrid,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import { BarChart3, Coins } from "lucide-react";
import { useTokenStats } from "@/hooks/use-api";
import { StatCard } from "@/components/dashboard/stat-card";
import type { TokenStats, TokenUsageRow } from "@/lib/types";

const CHART_HEIGHT = 220;

/** Recharts needs concrete colors, so resolve the semantic tokens used elsewhere. */
const COLOR_INPUT = "oklch(var(--success))";
const COLOR_OUTPUT = "oklch(var(--info))";
const COLOR_CREDITS = "oklch(var(--warning))";

const AXIS_TICK = { fill: "oklch(var(--muted-foreground))", fontSize: 11 };

const TOOLTIP_STYLE = {
	background: "oklch(var(--background))",
	border: "1px solid oklch(var(--border))",
	borderRadius: 8,
	fontSize: 12,
} as const;

export function fmtCompact(n: number): string {
	if (!Number.isFinite(n)) return "0";
	if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
	return `${n}`;
}

/**
 * Credits are small fractional amounts, so keep more precision than tokens.
 * Mirrors the formatting used in the traces table.
 */
export function fmtCredits(n: number): string {
	if (!Number.isFinite(n) || n === 0) return "0";
	return n < 0.01 ? n.toFixed(4) : n.toFixed(2);
}

/** Short label for a date bucket returned by ClickHouse (`YYYY-MM-DD`). */
function fmtDay(date: string): string {
	return date.length >= 10 ? date.slice(5) : date;
}

type UsageMode = "none" | "tokens" | "credits" | "mixed";

/**
 * Decide what to render. Exported so the presentation rule stays testable
 * without mounting the chart library.
 */
export function usageMode(stats: Pick<TokenStats, "has_token_data" | "has_credit_data">): UsageMode {
	if (stats.has_token_data && stats.has_credit_data) return "mixed";
	if (stats.has_credit_data) return "credits";
	if (stats.has_token_data) return "tokens";
	return "none";
}

function SectionShell({
	title,
	description,
	icon: Icon,
	children,
}: {
	title: string;
	description: string;
	icon: typeof BarChart3;
	children: React.ReactNode;
}) {
	return (
		<div className="rounded-lg border border-border p-4">
			<div className="flex items-center gap-2">
				<Icon className="h-4 w-4 text-muted-foreground" />
				<h3 className="text-sm font-medium">{title}</h3>
			</div>
			<p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
			<div className="mt-4">{children}</div>
		</div>
	);
}

/** Horizontal bar list, matching the "Agent Usage by Category" pattern. */
function ByAgentList({
	rows,
	metric,
}: {
	rows: TokenUsageRow[];
	metric: "tokens" | "credits";
}) {
	const value = (row: TokenUsageRow) => (metric === "credits" ? row.credits : row.total);
	const max = Math.max(...rows.map(value), metric === "credits" ? 0.0001 : 1);

	return (
		<div className="space-y-3">
			{rows.map((row) => (
				<div key={row.id || row.name} className="flex items-center gap-3">
					<span className="w-40 truncate text-sm" title={row.name}>
						{row.name}
					</span>
					<div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
						<div
							className="h-full rounded-full bg-primary"
							style={{ width: `${Math.min((value(row) / max) * 100, 100)}%` }}
						/>
					</div>
					<span className="w-20 shrink-0 text-right font-mono text-xs tabular-nums">
						{metric === "credits" ? `${fmtCredits(row.credits)} cr` : fmtCompact(row.total)}
					</span>
					<span className="w-16 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
						{row.traces} {row.traces === 1 ? "session" : "sessions"}
					</span>
				</div>
			))}
		</div>
	);
}

function CreditsOverTime({ data }: { data: TokenStats["over_time"] }) {
	const points = useMemo(
		() => data.map((p) => ({ ...p, label: fmtDay(p.date) })),
		[data],
	);

	if (points.length === 0) {
		return <p className="text-xs text-muted-foreground">No usage in this period.</p>;
	}

	return (
		<ResponsiveContainer width="100%" height={CHART_HEIGHT}>
			<AreaChart data={points} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
				<defs>
					<linearGradient id="creditsGrad" x1="0" y1="0" x2="0" y2="1">
						<stop offset="0%" stopColor={COLOR_CREDITS} stopOpacity={0.28} />
						<stop offset="100%" stopColor={COLOR_CREDITS} stopOpacity={0.02} />
					</linearGradient>
				</defs>
				<CartesianGrid strokeDasharray="3 3" stroke="oklch(var(--border))" strokeOpacity={0.5} vertical={false} />
				<XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} />
				<YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} width={48} />
				<Tooltip
					contentStyle={TOOLTIP_STYLE}
					formatter={(v) => [`${fmtCredits(Number(v))} cr`, "Credits"]}
				/>
				<Area
					type="monotone"
					dataKey="credits"
					stroke={COLOR_CREDITS}
					strokeWidth={2}
					fill="url(#creditsGrad)"
					dot={false}
				/>
			</AreaChart>
		</ResponsiveContainer>
	);
}

function TokensOverTime({ data }: { data: TokenStats["over_time"] }) {
	const points = useMemo(
		() => data.map((p) => ({ ...p, label: fmtDay(p.date) })),
		[data],
	);

	if (points.length === 0) {
		return <p className="text-xs text-muted-foreground">No usage in this period.</p>;
	}

	return (
		<>
			<ResponsiveContainer width="100%" height={CHART_HEIGHT}>
				<AreaChart data={points} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
					<defs>
						<linearGradient id="inputGrad" x1="0" y1="0" x2="0" y2="1">
							<stop offset="0%" stopColor={COLOR_INPUT} stopOpacity={0.28} />
							<stop offset="100%" stopColor={COLOR_INPUT} stopOpacity={0.02} />
						</linearGradient>
						<linearGradient id="outputGrad" x1="0" y1="0" x2="0" y2="1">
							<stop offset="0%" stopColor={COLOR_OUTPUT} stopOpacity={0.28} />
							<stop offset="100%" stopColor={COLOR_OUTPUT} stopOpacity={0.02} />
						</linearGradient>
					</defs>
					<CartesianGrid strokeDasharray="3 3" stroke="oklch(var(--border))" strokeOpacity={0.5} vertical={false} />
					<XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} />
					<YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} width={48} tickFormatter={fmtCompact} />
					<Tooltip
						contentStyle={TOOLTIP_STYLE}
						formatter={(v, name) => [
							fmtCompact(Number(v)),
							name === "input" ? "Input" : "Output",
						]}
					/>
					<Area type="monotone" dataKey="input" stroke={COLOR_INPUT} strokeWidth={2} fill="url(#inputGrad)" dot={false} />
					<Area type="monotone" dataKey="output" stroke={COLOR_OUTPUT} strokeWidth={2} fill="url(#outputGrad)" dot={false} />
				</AreaChart>
			</ResponsiveContainer>
			<div className="mt-3 flex gap-4 text-xs text-muted-foreground">
				<span className="flex items-center gap-2">
					<span className="h-0.5 w-3 rounded" style={{ background: COLOR_INPUT }} />
					Input
				</span>
				<span className="flex items-center gap-2">
					<span className="h-0.5 w-3 rounded" style={{ background: COLOR_OUTPUT }} />
					Output
				</span>
			</div>
		</>
	);
}

function CreditCards({ stats }: { stats: TokenStats }) {
	return (
		<div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
			<StatCard title="Total credits" value={`${fmtCredits(stats.total_credits)} cr`} />
			<StatCard
				title="Avg credits / session"
				value={`${fmtCredits(stats.avg_credits_per_trace)} cr`}
				description="across sessions reporting credits"
			/>
			<StatCard title="Sessions" value={stats.total_traces} />
		</div>
	);
}

function TokenCards({ stats }: { stats: TokenStats }) {
	return (
		<div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
			<StatCard title="Total tokens" value={fmtCompact(stats.total_tokens)} />
			<StatCard title="Input" value={fmtCompact(stats.total_input)} />
			<StatCard title="Output" value={fmtCompact(stats.total_output)} />
			<StatCard title="Avg / session" value={fmtCompact(Math.round(stats.avg_per_trace))} />
		</div>
	);
}

export function UsageSection({ range }: { range?: string }) {
	const { data: stats, isLoading, isError } = useTokenStats(range);

	if (isLoading) {
		return (
			<div className="space-y-4">
				<div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
					{[0, 1, 2, 3].map((i) => (
						<div key={i} className="h-20 animate-pulse rounded-lg border border-border bg-muted/30" />
					))}
				</div>
				<div className="h-56 animate-pulse rounded-lg border border-border bg-muted/30" />
			</div>
		);
	}

	if (isError || !stats) {
		return (
			<div className="rounded-lg border border-border p-8 text-center text-sm text-muted-foreground">
				Failed to load usage data.
			</div>
		);
	}

	const mode = usageMode(stats);

	if (mode === "none") {
		return (
			<SectionShell
				title="Usage"
				description="Token and credit usage across your sessions"
				icon={BarChart3}
			>
				<p className="text-sm text-muted-foreground">
					No usage data yet. Metrics appear once sessions are pushed to the server.
				</p>
			</SectionShell>
		);
	}

	// Kiro-only: credits are the only meter available, so never show a token section.
	if (mode === "credits") {
		return (
			<div className="space-y-4">
				<CreditCards stats={stats} />
				<div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
					<SectionShell
						title="Credits over time"
						description="Daily credit spend"
						icon={Coins}
					>
						<CreditsOverTime data={stats.over_time} />
					</SectionShell>
					<SectionShell
						title="Credits by agent"
						description="Credit spend attributed to each agent"
						icon={Coins}
					>
						{stats.by_agent.length > 0 ? (
							<ByAgentList rows={stats.by_agent} metric="credits" />
						) : (
							<p className="text-xs text-muted-foreground">
								No sessions in this period were linked to an agent.
							</p>
						)}
					</SectionShell>
				</div>
			</div>
		);
	}

	const showCredits = mode === "mixed";

	return (
		<div className="space-y-4">
			<TokenCards stats={stats} />
			{showCredits && (
				<>
					<p className="text-xs text-muted-foreground">
						Some sessions meter in credits rather than tokens. Both are shown separately;
						they are different units and are not comparable.
					</p>
					<CreditCards stats={stats} />
				</>
			)}
			<div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
				<SectionShell
					title="Tokens over time"
					description="Daily input and output tokens"
					icon={BarChart3}
				>
					<TokensOverTime data={stats.over_time} />
				</SectionShell>
				<SectionShell
					title={showCredits ? "Usage by agent" : "Tokens by agent"}
					description={
						showCredits
							? "Tokens per agent, with credit spend where reported"
							: "Token usage attributed to each agent"
					}
					icon={BarChart3}
				>
					{stats.by_agent.length > 0 ? (
						<ByAgentList rows={stats.by_agent} metric="tokens" />
					) : (
						<p className="text-xs text-muted-foreground">
							No sessions in this period were linked to an agent.
						</p>
					)}
				</SectionShell>
			</div>
			{showCredits && (
				<SectionShell
					title="Credits over time"
					description="Daily credit spend for harnesses that meter in credits"
					icon={Coins}
				>
					<CreditsOverTime data={stats.over_time} />
				</SectionShell>
			)}
			{stats.by_mcp.length > 0 && (
				<SectionShell
					title="Tokens by MCP server"
					description="Session tokens attributed to each MCP server a session used. A session counts toward every server it used, so these do not sum to the total."
					icon={BarChart3}
				>
					<ByAgentList rows={stats.by_mcp} metric="tokens" />
				</SectionShell>
			)}
		</div>
	);
}
