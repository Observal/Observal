// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { Link, useRouter } from "@tanstack/react-router";
import { useState, useMemo, useCallback, useRef } from "react";
import {
	Activity,
	Search,
	ArrowUpDown,
	ArrowUp,
	ArrowDown,
	BarChart3,
} from "lucide-react";
import {
	useSessions2,
	useSessionsSummary,
	useSessionSubscription,
} from "@/hooks/use-api";
import {
	useReactTable,
	getCoreRowModel,
	getSortedRowModel,
	flexRender,
	type ColumnDef,
	type SortingState,
} from "@tanstack/react-table";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import type { Session } from "@/lib/types";

// ── Search query parser (Discord-style: platform:kiro user:"John Doe") ───────

function parseSearchQuery(query: string): { text: string; filters: Record<string, string> } {
	const filters: Record<string, string> = {};
	const tokens = query.match(/(\w+):(?:"([^"]*)"|([^\s]*))/g);
	if (tokens) {
		for (const token of tokens) {
			const colonIdx = token.indexOf(":");
			const key = token.slice(0, colonIdx).toLowerCase();
			let value = token.slice(colonIdx + 1);
			if (value.startsWith('"') && value.endsWith('"')) {
				value = value.slice(1, -1);
			}
			const keyMap: Record<string, string> = {
				platform: "platform",
				ide: "platform",
				user: "user",
				agent: "agent",
				model: "model",
				days: "days",
				status: "status",
			};
			const apiKey = keyMap[key];
			if (apiKey) filters[apiKey] = value;
		}
	}
	// Remaining text after removing filter tokens
	const text = query.replace(/(\w+):(?:"[^"]*"|[^\s]*)/g, "").trim();
	return { text, filters };
}

// ── Helpers ──────────────────────────────────────────────────────────

function isKiroSession(row: Session): boolean {
	return row.service_name === "kiro" || row.session_id.startsWith("kiro-");
}

function isCursorSession(row: Session): boolean {
	return row.service_name === "cursor" || row.platform === "Cursor";
}

function isCopilotCliSession(row: Session): boolean {
	return (
		row.service_name === "copilot-cli" ||
		row.service_name === "copilot" ||
		row.service_name === "GitHub Copilot" ||
		row.session_id.startsWith("copilot-cli-")
	);
}

function fmtTokens(n: number | string | undefined): string {
	if (n == null) return "0";
	const num = typeof n === "string" ? parseInt(n, 10) : n;
	if (isNaN(num)) return "0";
	if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
	if (num >= 1_000) return `${(num / 1_000).toFixed(1)}k`;
	return `${num}`;
}

function fmtCredits(c: number | string | undefined | null): string | null {
	if (c === null || c === undefined || c === "") return null;
	const num = typeof c === "number" ? c : parseFloat(c as string);
	if (isNaN(num) || num <= 0) return null;
	return num < 0.01 ? num.toFixed(4) : num.toFixed(2);
}

const TS_UPPER_BOUND_MS = new Date("2099-01-01").getTime();

function fmtDuration(first?: string, last?: string): string {
	if (!first || !last) return "\u2013";
	const t1 = toDate(first).getTime();
	const t2 = toDate(last).getTime();
	if (t1 >= TS_UPPER_BOUND_MS || t2 >= TS_UPPER_BOUND_MS) return "\u2013";
	const ms = t2 - t1;
	if (ms < 0) return "\u2013";
	const mins = Math.floor(ms / 60_000);
	const hours = Math.floor(mins / 60);
	if (hours > 0) return `${hours}h ${String(mins % 60).padStart(2, "0")}m`;
	if (mins > 0) return `${mins}m`;
	return "< 1m";
}

function toDate(ts: string): Date {
	if (ts.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(ts)) return new Date(ts);
	// ClickHouse returns DateTime64 as "YYYY-MM-DD HH:MM:SS.mmm" (space, no Z).
	// Replace the space with T and append Z for valid ISO 8601 UTC parsing.
	return new Date(ts.replace(" ", "T") + "Z");
}

function relTime(ts?: string): string {
	if (!ts) return "\u2013";
	const ms = Date.now() - toDate(ts).getTime();
	if (ms < 0) return "just now";
	const mins = Math.floor(ms / 60_000);
	const hours = Math.floor(ms / 3_600_000);
	const days = Math.floor(ms / 86_400_000);
	if (days > 0) return `${days}d ago`;
	if (hours > 0) return `${hours}h ago`;
	if (mins > 0) return `${mins}m ago`;
	return "just now";
}

function absTime(ts?: string): string {
	if (!ts) return "";
	return toDate(ts).toLocaleString();
}

function shortModel(raw?: string): string {
	if (!raw) return "";
	return raw
		.replace("claude-", "")
		.replace("anthropic.", "")
		.replace(/-\d{8}$/, "");
}

function derivePlatform(row: Session): string {
	if (row.platform) return row.platform;
	if (isCursorSession(row)) return "Cursor";
	if (isKiroSession(row)) return "Kiro";
	if (isCopilotCliSession(row)) return "Copilot CLI";
	return "Claude Code";
}

function sessionLabel(row: Session): string {
	const model = shortModel(row.model);
	const count = row.prompt_count ?? 0;
	const suffix = count === 1 ? "prompt" : "prompts";
	const agent = row.agent_name ? `${row.agent_name} \u00b7 ` : "";
	if (model) return `${agent}${model} \u00b7 ${count} ${suffix}`;
	return `${agent}${count} ${suffix}`;
}

// ── Column Definitions ───────────────────────────────────────────────

const columns: ColumnDef<Session>[] = [
	{
		accessorKey: "session_id",
		header: "Session",
		cell: ({ row }) => (
			<Link
				to="/traces/$traceId" params={{ traceId: row.original.session_id }}
				className="text-[13px] font-medium text-foreground/90 hover:text-foreground transition-colors whitespace-nowrap"
				onClick={(e) => e.stopPropagation()}
			>
				{sessionLabel(row.original)}
			</Link>
		),
	},
	{
		accessorKey: "user_name",
		header: "User",
		cell: ({ row }) => (
			<span className="text-[13px] text-muted-foreground whitespace-nowrap">
				{row.original.user_name || "\u2014"}
			</span>
		),
	},
	{
		id: "platform",
		accessorFn: (row) => derivePlatform(row),
		header: "Platform",
		cell: ({ row }) => (
			<span className="text-[13px] font-medium text-foreground/80 whitespace-nowrap">
				{derivePlatform(row.original)}
			</span>
		),
	},
	{
		id: "tokens",
		header: "Tokens",
		accessorFn: (row) => row.total_input_tokens ?? 0,
		cell: ({ row }) => {
			const r = row.original;
			if (isCopilotCliSession(r)) {
				return (
					<span className="text-[13px] text-muted-foreground">{"\u2014"}</span>
				);
			}
			if (isKiroSession(r)) {
				const credits = fmtCredits(r.total_credits ?? r.credits);
				if (credits) {
					return (
						<span className="text-[13px] font-mono tabular-nums text-orange-400">
							{credits} cr
						</span>
					);
				}
				return <span className="text-[13px] text-muted-foreground">{"\u2013"}</span>;
			}
			if (!r.total_input_tokens && !r.total_output_tokens) {
				return (
					<span className="text-[13px] text-muted-foreground">{"\u2014"}</span>
				);
			}
			const inp = fmtTokens(r.total_input_tokens);
			const out = fmtTokens(r.total_output_tokens);
			return (
				<span
					className="text-[13px] font-mono tabular-nums"
					title={`In: ${r.total_input_tokens?.toLocaleString() ?? 0} · Out: ${r.total_output_tokens?.toLocaleString() ?? 0}`}
				>
					<span className="text-emerald-400">{inp}</span>
					<span className="text-muted-foreground/50"> / </span>
					<span className="text-blue-400">{out}</span>
				</span>
			);
		},
	},
	{
		accessorKey: "tool_result_count",
		header: "Tools",
		cell: ({ row }) => (
			<span className="text-[13px] font-mono tabular-nums text-muted-foreground">
				{row.original.tool_result_count ?? 0}
			</span>
		),
	},
	{
		id: "duration",
		header: "Duration",
		accessorFn: (row) => {
			if (!row.first_event_time || !row.last_event_time) return 0;
			return (
				toDate(row.last_event_time).getTime() -
				toDate(row.first_event_time).getTime()
			);
		},
		cell: ({ row }) => (
			<span className="text-[13px] text-muted-foreground tabular-nums whitespace-nowrap">
				{fmtDuration(
					row.original.first_event_time,
					row.original.last_event_time,
				)}
			</span>
		),
	},
	{
		accessorKey: "first_event_time",
		header: "Started",
		cell: ({ row }) => (
			<span
				className="text-[13px] text-muted-foreground tabular-nums whitespace-nowrap"
				title={absTime(row.original.first_event_time)}
			>
				{relTime(row.original.first_event_time)}
			</span>
		),
		sortingFn: (a, b) => {
			const ta = a.original.first_event_time
				? toDate(a.original.first_event_time).getTime()
				: 0;
			const tb = b.original.first_event_time
				? toDate(b.original.first_event_time).getTime()
				: 0;
			return ta - tb;
		},
	},
];

// ── Sort Icon ────────────────────────────────────────────────────────

function SortIcon({ sorted }: { sorted: false | "asc" | "desc" }) {
	if (sorted === "asc") return <ArrowUp className="h-3 w-3" />;
	if (sorted === "desc") return <ArrowDown className="h-3 w-3" />;
	return <ArrowUpDown className="h-3 w-3 opacity-25" />;
}

// ── Page ─────────────────────────────────────────────────────────────

export default function TracesPage() {
	const router = useRouter();
	const [page, setPage] = useState(0);
	const PAGE_SIZE = 50;

	const {
		data: sessions,
		isLoading,
		isError,
		error,
		refetch,
	} = useSessions2({
		refetchInterval: 5_000,
		limit: PAGE_SIZE,
		offset: page * PAGE_SIZE,
	});
	const { data: summary } = useSessionsSummary();
	useSessionSubscription();

	const [sorting, setSorting] = useState<SortingState>([
		{ id: "first_event_time", desc: true },
	]);
	const [searchValue, setSearchValue] = useState("");
	const [globalFilter, setGlobalFilter] = useState("");
	const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

	const handleSearch = useCallback(
		(value: string) => {
			setSearchValue(value);
			clearTimeout(debounceRef.current);
			debounceRef.current = setTimeout(() => setGlobalFilter(value), 300);
		},
		[setGlobalFilter],
	);

	const allSessions = useMemo(() => (sessions ?? []) as Session[], [sessions]);

	// Apply parameterized filters from search query
	const filteredSessions = useMemo(() => {
		const { text, filters } = parseSearchQuery(globalFilter);
		let result = allSessions;

		if (filters.platform) {
			const p = filters.platform.toLowerCase();
			result = result.filter(
				(s) =>
					(s.service_name ?? "").toLowerCase().includes(p) ||
					(s.platform ?? "").toLowerCase().includes(p),
			);
		}
		if (filters.user) {
			const u = filters.user.toLowerCase();
			result = result.filter((s) =>
				(s.user_name ?? "").toLowerCase().includes(u),
			);
		}
		if (filters.agent) {
			const a = filters.agent.toLowerCase();
			result = result.filter((s) =>
				(s.agent_name ?? "").toLowerCase().includes(a),
			);
		}
		if (filters.model) {
			const m = filters.model.toLowerCase();
			result = result.filter((s) =>
				(s.model ?? "").toLowerCase().includes(m),
			);
		}
		if (filters.days) {
			const d = parseInt(filters.days, 10);
			if (!isNaN(d) && d > 0) {
				const cutoff = Date.now() - d * 86_400_000;
				result = result.filter((s) =>
					s.first_event_time && toDate(s.first_event_time).getTime() >= cutoff,
				);
			}
		}
		if (filters.status) {
			const st = filters.status.toLowerCase();
			if (st === "active") result = result.filter((s) => s.is_active);
			else if (st === "inactive") result = result.filter((s) => !s.is_active);
		}

		// Free text search on session label / user / model
		if (text) {
			const lower = text.toLowerCase();
			result = result.filter(
				(s) =>
					(s.session_id ?? "").toLowerCase().includes(lower) ||
					(s.user_name ?? "").toLowerCase().includes(lower) ||
					(s.agent_name ?? "").toLowerCase().includes(lower) ||
					(s.model ?? "").toLowerCase().includes(lower) ||
					(s.platform ?? "").toLowerCase().includes(lower),
			);
		}

		return result;
	}, [allSessions, globalFilter]);

	const data = useMemo(
		() => filteredSessions,
		[filteredSessions],
	);

	const table = useReactTable({
		data,
		columns,
		state: { sorting },
		onSortingChange: setSorting,
		getCoreRowModel: getCoreRowModel(),
		getSortedRowModel: getSortedRowModel(),
	});

	const todaySessions = summary?.today_sessions ?? allSessions.length;

	return (
		<>
			<PageHeader
				title="Traces"
				breadcrumbs={[
					{ label: "Dashboard", href: "/dashboard" },
					{ label: "Traces" },
				]}
			/>
			<div className="p-6 w-full mx-auto space-y-5">
				{isLoading ? (
					<TableSkeleton rows={8} cols={8} />
				) : isError ? (
					<ErrorState message={error?.message} onRetry={() => refetch()} />
				) : allSessions.length === 0 ? (
					<EmptyState
						icon={Activity}
						title="No sessions yet"
						description="Sessions will appear here once telemetry data is collected from your IDE."
					/>
				) : (
					<div className="animate-in space-y-5">
						{/* ── Summary ── */}
						<div className="flex items-center gap-2.5 text-sm text-muted-foreground">
							<BarChart3 className="h-4 w-4 text-foreground/50" />
							<span>
								<span className="font-semibold text-foreground tabular-nums">
									{todaySessions}
								</span>{" "}
								session{todaySessions !== 1 ? "s" : ""} today
							</span>
						</div>

						{/* ── Toolbar ── */}
						<div className="flex items-center gap-3">
							<div className="relative flex-1">
								<Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
								<Input
									placeholder="Search: platform:kiro user:name agent:my-agent model:sonnet days:7 status:active"
									value={searchValue}
									onChange={(e) => handleSearch(e.target.value)}
									className="pl-8 h-9 text-sm font-mono"
								/>
							</div>
						</div>

						{/* Filter hints */}
						<div className="flex gap-1.5 flex-wrap">
							<span className="text-[10px] text-muted-foreground">Filters:</span>
							{["platform:", "user:", "agent:", "model:", "days:", "status:"].map((hint) => (
								<button
									key={hint}
									type="button"
									className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground hover:text-foreground hover:bg-muted/80 font-mono transition-colors"
									onClick={() => handleSearch(searchValue + (searchValue && !searchValue.endsWith(" ") ? " " : "") + hint)}
								>
									{hint}
								</button>
							))}
						</div>

						{/* ── Table ── */}
						<div className="rounded-lg border border-border overflow-hidden">
							<Table>
								<TableHeader>
									{table.getHeaderGroups().map((hg) => (
										<TableRow
											key={hg.id}
											className="hover:bg-transparent bg-muted/40 border-b border-border"
										>
											{hg.headers.map((header) => (
												<TableHead
													key={header.id}
													className="h-11 px-5 text-center cursor-pointer select-none hover:text-foreground transition-colors"
													onClick={header.column.getToggleSortingHandler()}
												>
													<span className="inline-flex items-center justify-center gap-1 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
														{flexRender(
															header.column.columnDef.header,
															header.getContext(),
														)}
														<SortIcon sorted={header.column.getIsSorted()} />
													</span>
												</TableHead>
											))}
										</TableRow>
									))}
								</TableHeader>
								<TableBody>
									{table.getRowModel().rows.length === 0 ? (
										<TableRow>
											<TableCell
												colSpan={columns.length}
												className="h-32 text-center text-sm text-muted-foreground"
											>
												No matching sessions.
											</TableCell>
										</TableRow>
									) : (
										table.getRowModel().rows.map((row, idx) => {
											const active = row.original.is_active;
											return (
												<TableRow
													key={row.id}
													className={`relative cursor-pointer transition-colors hover:bg-muted/50 border-b border-border/50 ${
														idx % 2 === 1 ? "bg-muted/15" : ""
													}`}
													onClick={() =>
														router.navigate({ to: "/traces/$traceId", params: { traceId: row.original.session_id } })
													}
												>
													{row.getVisibleCells().map((cell, cellIdx) => (
														<TableCell
															key={cell.id}
															className={`py-4 px-5 text-center ${cellIdx === 0 ? "relative" : ""}`}
														>
															{cellIdx === 0 && active && (
																<span
																	className="absolute inset-y-0 left-0 w-[3px] bg-green-500 rounded-r-sm"
																	aria-hidden="true"
																/>
															)}
															{flexRender(
																cell.column.columnDef.cell,
																cell.getContext(),
															)}
														</TableCell>
													))}
												</TableRow>
											);
										})
									)}
								</TableBody>
							</Table>
						</div>

						{/* ── Footer ── */}
						<div className="flex items-center justify-between">
							<p className="text-xs text-muted-foreground/70">
								Page {page + 1} · {table.getRowModel().rows.length} sessions
							</p>
							<div className="flex items-center gap-2">
								<button
									type="button"
									className="text-xs px-2 py-1 rounded border border-border text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
									disabled={page === 0}
									onClick={() => setPage(page - 1)}
								>
									Prev
								</button>
								<button
									type="button"
									className="text-xs px-2 py-1 rounded border border-border text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
									disabled={allSessions.length < PAGE_SIZE}
									onClick={() => setPage(page + 1)}
								>
									Next
								</button>
							</div>
						</div>
					</div>
				)}
			</div>
		</>
	);
}
