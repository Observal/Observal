// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { use } from "react";
import { useTrace } from "@/hooks/use-api";
import { PageHeader } from "@/components/layouts/page-header";
import { StatusBadge } from "@/components/registry/status-badge";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryError } from "@/components/dashboard/query-error";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { ListTree } from "lucide-react";

interface Span {
	spanId: string;
	name: string;
	type: string;
	startTime?: string;
	endTime?: string;
	status: string;
	latencyMs?: number;
}

interface TraceDetail {
	traceId: string;
	traceType: string;
	name?: string;
	ide?: string;
	startTime?: string;
	endTime?: string;
	spans?: Span[];
	metrics?: {
		totalSpans?: number;
		errorCount?: number;
		totalLatencyMs?: number;
		toolCallCount?: number;
		tokenCountTotal?: number;
	};
}

function Stat({ label, value }: { label: string; value: string | number }) {
	return (
		<div>
			<p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
				{label}
			</p>
			<p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
		</div>
	);
}

export default function TraceDetailPage({
	params,
}: {
	params: Promise<{ traceId: string }>;
}) {
	const { traceId } = use(params);
	const { data, isLoading, isError, error, refetch } = useTrace(traceId);
	const trace = data as TraceDetail | undefined;
	const spans = trace?.spans ?? [];
	const m = trace?.metrics;

	return (
		<>
			<PageHeader
				title={trace?.name || "Trace"}
				breadcrumbs={[
					{ label: "Dashboard", href: "/dashboard" },
					{ label: "Traces", href: "/traces" },
					{ label: trace?.name || "Trace" },
				]}
			/>
			<div className="p-6 w-full mx-auto space-y-6">
				{isError ? (
					<QueryError message={error?.message} onRetry={refetch} />
				) : isLoading ? (
					<div className="space-y-3">
						<Skeleton className="h-20 w-full" />
						<Skeleton className="h-64 w-full" />
					</div>
				) : !trace ? (
					<div className="flex flex-col items-center justify-center rounded-md border border-dashed py-16">
						<ListTree className="h-6 w-6 text-muted-foreground" />
						<p className="mt-3 text-sm font-medium">Trace not found</p>
					</div>
				) : (
					<>
						{/* ── Meta + metrics ── */}
						<div className="flex flex-wrap items-center gap-2 text-sm">
							<Badge variant="outline">{trace.traceType}</Badge>
							{trace.ide && (
								<span className="text-xs text-muted-foreground">
									IDE: {trace.ide}
								</span>
							)}
							{trace.startTime && (
								<span className="text-xs text-muted-foreground">
									{new Date(trace.startTime).toLocaleString()} (UTC stored)
								</span>
							)}
						</div>
						<div className="grid grid-cols-2 gap-6 rounded-lg border p-5 sm:grid-cols-4">
							<Stat label="Spans" value={m?.totalSpans ?? spans.length} />
							<Stat label="Tool Calls" value={m?.toolCallCount ?? 0} />
							<Stat label="Errors" value={m?.errorCount ?? 0} />
							<Stat label="Tokens" value={m?.tokenCountTotal ?? 0} />
						</div>

						{/* ── Spans ── */}
						{spans.length === 0 ? (
							<div className="flex flex-col items-center justify-center rounded-md border border-dashed py-16">
								<ListTree className="h-6 w-6 text-muted-foreground" />
								<p className="mt-3 text-sm font-medium">No spans in this trace</p>
							</div>
						) : (
							<div className="rounded-md border">
								<Table>
									<TableHeader>
										<TableRow className="hover:bg-transparent">
											<TableHead className="h-9 px-3 text-xs">Name</TableHead>
											<TableHead className="h-9 px-3 text-xs">Type</TableHead>
											<TableHead className="h-9 px-3 text-xs">
												Start Time
											</TableHead>
											<TableHead className="h-9 px-3 text-xs">
												Latency
											</TableHead>
											<TableHead className="h-9 px-3 text-xs">Status</TableHead>
										</TableRow>
									</TableHeader>
									<TableBody>
										{spans.map((s) => (
											<TableRow key={s.spanId}>
												<TableCell className="px-3 py-2 text-sm font-medium">
													{s.name}
												</TableCell>
												<TableCell className="px-3 py-2">
													<Badge variant="outline" className="text-xs">
														{s.type}
													</Badge>
												</TableCell>
												<TableCell className="px-3 py-2 text-xs text-muted-foreground">
													{s.startTime
														? new Date(s.startTime).toLocaleString()
														: "—"}
												</TableCell>
												<TableCell className="px-3 py-2 text-xs tabular-nums text-muted-foreground">
													{s.latencyMs != null ? `${s.latencyMs} ms` : "—"}
												</TableCell>
												<TableCell className="px-3 py-2">
													<StatusBadge status={s.status} />
												</TableCell>
											</TableRow>
										))}
									</TableBody>
								</Table>
							</div>
						)}
					</>
				)}
			</div>
		</>
	);
}
