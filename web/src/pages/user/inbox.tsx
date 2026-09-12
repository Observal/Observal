// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

/**
 * The inbox, laid out as a notifications feed.
 *
 * The shape is deliberately GitHub's: a filter rail beside the feed, an
 * All/Unread split with search and sort above the list, and rows that carry
 * their subject, their reason and their age on one line. That layout is worth
 * copying because it solves the same problem — a long list of heterogeneous
 * items where the question is always "what still needs me".
 *
 * One thing is not copied. GitHub rows are pure links; ours also carry a body,
 * a copyable CLI command and an audit trail, none of which fit on a row. Those
 * live in a detail sheet reachable from the row's hover actions, so the row
 * stays a link to the actual work rather than becoming a summary of it.
 */

import { useEffect, useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import {
	ArrowLeftRight,
	ArrowUpCircle,
	Check,
	CheckCheck,
	ChevronDown,
	CircleCheck,
	CircleDot,
	CircleX,
	Copy,
	Eye,
	EyeOff,
	FileDiff,
	GitPullRequest,
	Inbox as InboxIcon,
	Info,
	ListFilter,
	Loader2,
	Megaphone,
	MessageSquare,
	RotateCcw,
	Search,
	Sparkles,
	TriangleAlert,
	UserPlus,
	Users,
	X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuRadioGroup,
	DropdownMenuRadioItem,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
	Sheet,
	SheetContent,
	SheetDescription,
	SheetHeader,
	SheetTitle,
} from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardContent, DashboardShell } from "@/components/layouts/dashboard-shell";
import {
	useBulkAction,
	useDismissItem,
	useInbox,
	useInboxCounts,
	useInboxItem,
	useMarkDone,
	useMarkRead,
	useMarkUnread,
	useReadAll,
	useReopenItem,
} from "@/hooks/use-inbox-api";
import {
	INBOX_KIND_LABELS,
	INBOX_KIND_REASONS,
	INBOX_SUBJECT_LABELS,
	type InboxFilters,
	type InboxItem,
	type InboxKind,
	type InboxSort,
	type InboxState,
} from "@/lib/types";
import { cn } from "@/lib/utils";

// ── Presentation tables ────────────────────────────────────────────────

/**
 * The glyph and colour for each kind, which is what makes the list scannable
 * without reading it — the same job GitHub's merged/open/closed icons do.
 */
const KIND_META: Record<InboxKind, { icon: LucideIcon; tone: string }> = {
	review_requested: { icon: GitPullRequest, tone: "text-primary-accent" },
	review_approved: { icon: CircleCheck, tone: "text-success" },
	review_rejected: { icon: CircleX, tone: "text-destructive" },
	review_comment: { icon: MessageSquare, tone: "text-muted-foreground" },
	change_requested: { icon: FileDiff, tone: "text-warning" },
	team_join_requested: { icon: UserPlus, tone: "text-primary-accent" },
	team_join_decided: { icon: Users, tone: "text-muted-foreground" },
	team_created_pending: { icon: Users, tone: "text-warning" },
	ownership_transfer: { icon: ArrowLeftRight, tone: "text-warning" },
	update_available: { icon: ArrowUpCircle, tone: "text-info" },
	insight_ready: { icon: Sparkles, tone: "text-primary-accent" },
	system_notice: { icon: Megaphone, tone: "text-muted-foreground" },
};

const BUCKETS: { key: InboxState; label: string; icon: LucideIcon }[] = [
	{ key: "open", label: "Inbox", icon: InboxIcon },
	{ key: "done", label: "Done", icon: Check },
	{ key: "dismissed", label: "Dismissed", icon: X },
];

const SORT_LABELS: Record<InboxSort, string> = {
	newest: "Newest to oldest",
	oldest: "Oldest to newest",
};

type GroupMode = "date" | "type" | "none";

const GROUP_LABELS: Record<GroupMode, string> = {
	date: "Date",
	type: "Type",
	none: "Nothing",
};

// ── Small helpers ──────────────────────────────────────────────────────

/**
 * Split a server-built `action_url` into what Link needs, or refuse it.
 *
 * Two jobs. First, safety: the column is a free string and the API contract
 * does not constrain it, so a hostile value reaching Link would be an open
 * redirect out of a trusted surface. Rejected in order: anything not starting
 * with a single slash, protocol-relative `//host`, backslashes (browsers treat
 * them as separators, so `/\host` escapes too), control characters and spaces,
 * any first path segment outside the allowlist below, and `..` segments. The
 * allowlist is the decisive one — the set of routes the server links to is
 * small and known, so anything else is a bug or an injection.
 *
 * Second, correctness: these paths carry query strings that decide what the
 * destination renders — `?type=` picks the component type, `?tab=` picks the
 * review queue tab. Link takes those as a `search` object, not baked into
 * `to`, so a raw string would navigate to the path with the params dropped.
 */
const INTERNAL_ROOTS = new Set(["agents", "components", "review", "insights", "teamspaces"]);

function internalTarget(url: string | null): { to: string; search: Record<string, string> } | null {
	if (!url || !url.startsWith("/")) return null;

	// Reject anything that could leave this origin before the path is read.
	// `//evil.example` is protocol-relative, and a backslash is treated as a
	// separator by browsers, so `/\evil.example` escapes too. Control characters
	// and whitespace are rejected because they can be used to hide the real
	// target from anyone eyeballing the link.
	if (url.startsWith("//") || url.includes("\\")) return null;
	// Control characters and spaces are checked by code point rather than with
	// a regex literal, so this source file never has to contain one.
	if ([...url].some((ch) => ch.charCodeAt(0) <= 0x20 || ch.charCodeAt(0) === 0x7f)) return null;

	const [path, query] = url.split("?");

	// An allowlist rather than a denylist. The column is free text, and the set
	// of routes the server links to is small and known, so anything outside it
	// is a bug or an injection — either way not somewhere to navigate.
	const root = path.split("/")[1] ?? "";
	if (!INTERNAL_ROOTS.has(root)) return null;
	// `..` cannot climb out of the SPA, but it can address a route the server
	// never meant to name, so it is refused rather than normalised.
	if (path.split("/").includes("..")) return null;

	const search: Record<string, string> = {};
	if (query) {
		for (const [key, value] of new URLSearchParams(query)) search[key] = value;
	}
	return { to: path, search };
}

function plural(n: number, unit: string): string {
	return `${n} ${unit}${n === 1 ? "" : "s"} ago`;
}

function relativeTime(iso: string): string {
	const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
	if (mins < 1) return "just now";
	if (mins < 60) return plural(mins, "minute");
	const hours = Math.round(mins / 60);
	if (hours < 24) return plural(hours, "hour");
	const days = Math.round(hours / 24);
	if (days < 7) return plural(days, "day");
	const weeks = Math.round(days / 7);
	if (weeks < 5) return plural(weeks, "week");
	return plural(Math.round(days / 30), "month");
}

/** Where a row says it came from: `namespace/slug` when the subject has one. */
function subjectPath(item: InboxItem): string {
	if (item.subject_namespace && item.subject_slug) {
		return `${item.subject_namespace}/${item.subject_slug}`;
	}
	return item.subject_slug || INBOX_SUBJECT_LABELS[item.subject_type] || item.subject_type;
}

function dateBucket(iso: string): string {
	const then = new Date(iso).getTime();
	const now = new Date();
	const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
	const day = 86_400_000;
	if (then >= midnight) return "Today";
	if (then >= midnight - day) return "Yesterday";
	if (then >= midnight - 7 * day) return "This week";
	if (then >= midnight - 30 * day) return "This month";
	return "Older";
}

/**
 * Partition the page into labelled runs.
 *
 * A Map keyed on the label rather than a walk over adjacent rows: type
 * grouping revisits a label after others have appeared, and a sequential walk
 * would emit that label as several separate headings. Insertion order keeps
 * date groups in the order the sort already put them.
 */
function groupItems(items: InboxItem[], mode: GroupMode): { label: string; items: InboxItem[] }[] {
	if (mode === "none") return [{ label: "", items }];
	const groups = new Map<string, InboxItem[]>();
	for (const item of items) {
		const label =
			mode === "date"
				? dateBucket(item.created_at)
				: INBOX_SUBJECT_LABELS[item.subject_type] || item.subject_type;
		const bucket = groups.get(label);
		if (bucket) bucket.push(item);
		else groups.set(label, [item]);
	}
	return [...groups].map(([label, rows]) => ({ label, items: rows }));
}

/**
 * A stable colour per namespace, so the same owner reads as the same owner
 * down the list. Hashed rather than random because a colour that changes
 * between renders carries no information at all.
 */
const AVATAR_TONES = [
	"bg-chart-1",
	"bg-chart-2",
	"bg-chart-3",
	"bg-chart-4",
	"bg-chart-5",
	"bg-chart-6",
	"bg-chart-7",
	"bg-chart-8",
];

function OwnerAvatar({ name }: { name: string }) {
	let hash = 0;
	for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0;
	const tone = AVATAR_TONES[Math.abs(hash) % AVATAR_TONES.length];
	return (
		<span
			aria-hidden
			className={cn(
				"flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold text-background",
				tone,
			)}
		>
			{name.slice(0, 1).toUpperCase()}
		</span>
	);
}

// ── Sidebar ────────────────────────────────────────────────────────────

function RailRow({
	icon: Icon,
	label,
	count,
	active,
	onClick,
}: {
	icon?: LucideIcon;
	label: string;
	count?: number;
	active: boolean;
	onClick: () => void;
}) {
	return (
		<button
			type="button"
			onClick={onClick}
			className={cn(
				"flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
				active ? "bg-muted font-semibold" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
			)}
		>
			{Icon && <Icon className="h-4 w-4 shrink-0" />}
			<span className="min-w-0 flex-1 truncate">{label}</span>
			{count ? <span className="shrink-0 text-xs tabular-nums">{count}</span> : null}
		</button>
	);
}

function InboxRail({
	bucket,
	kind,
	subjectType,
	actionOnly,
	counts,
	onBucket,
	onKind,
	onSubjectType,
	onActionOnly,
	onMarkAllRead,
	markAllDisabled,
}: {
	bucket: InboxState;
	kind: InboxKind | undefined;
	subjectType: string | undefined;
	actionOnly: boolean;
	counts:
		| {
				open: number;
				done: number;
				dismissed: number;
				action_required: number;
				by_kind: Partial<Record<InboxKind, number>>;
				by_subject_type: Record<string, number>;
		  }
		| undefined;
	onBucket: (b: InboxState) => void;
	onKind: (k: InboxKind | undefined) => void;
	onSubjectType: (t: string | undefined) => void;
	onActionOnly: (v: boolean) => void;
	onMarkAllRead: () => void;
	markAllDisabled: boolean;
}) {
	const byKind = counts?.by_kind ?? {};
	const bySubject = counts?.by_subject_type ?? {};

	// Only kinds actually present in this bucket get a row; the full list lives
	// behind "More filters" so a rail with two kinds in it does not render ten
	// dead zeroes.
	const presentKinds = (Object.keys(byKind) as InboxKind[])
		.filter((k) => (byKind[k] ?? 0) > 0)
		.sort((a, b) => (byKind[b] ?? 0) - (byKind[a] ?? 0));
	const hiddenKinds = (Object.keys(INBOX_KIND_LABELS) as InboxKind[]).filter(
		(k) => !presentKinds.includes(k),
	);
	const subjectTypes = Object.keys(bySubject)
		.filter((t) => bySubject[t] > 0)
		.sort((a, b) => bySubject[b] - bySubject[a]);

	const bucketCount = (b: InboxState) =>
		b === "open" ? counts?.open : b === "done" ? counts?.done : counts?.dismissed;

	return (
		<aside data-testid="inbox-rail" className="hidden w-56 shrink-0 overflow-y-auto border-l p-2 md:block">
			<nav className="space-y-0.5">
				{BUCKETS.map((entry) => (
					<RailRow
						key={entry.key}
						icon={entry.icon}
						label={entry.label}
						count={bucketCount(entry.key)}
						active={bucket === entry.key}
						onClick={() => onBucket(entry.key)}
					/>
				))}
			</nav>

			<div className="my-3 border-t" />

			<div className="px-2 pb-1 text-xs font-semibold text-muted-foreground">Filters</div>
			<nav className="space-y-0.5">
				<RailRow
					icon={CircleDot}
					label="Needs action"
					count={counts?.action_required}
					active={actionOnly}
					onClick={() => onActionOnly(!actionOnly)}
				/>
				{presentKinds.map((k) => (
					<RailRow
						key={k}
						icon={KIND_META[k].icon}
						label={INBOX_KIND_LABELS[k]}
						count={byKind[k]}
						active={kind === k}
						onClick={() => onKind(kind === k ? undefined : k)}
					/>
				))}
				{hiddenKinds.length > 0 && (
					<DropdownMenu>
						<DropdownMenuTrigger asChild>
							<button
								type="button"
								className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
							>
								<ListFilter className="h-4 w-4 shrink-0" />
								<span className="flex-1 truncate">More filters</span>
							</button>
						</DropdownMenuTrigger>
						<DropdownMenuContent align="start" className="w-56">
							<DropdownMenuLabel>Filter by kind</DropdownMenuLabel>
							<DropdownMenuSeparator />
							{hiddenKinds.map((k) => (
								<DropdownMenuItem key={k} onSelect={() => onKind(k)}>
									{INBOX_KIND_LABELS[k]}
								</DropdownMenuItem>
							))}
						</DropdownMenuContent>
					</DropdownMenu>
				)}
			</nav>

			{subjectTypes.length > 0 && (
				<>
					<div className="my-3 border-t" />
					<div className="px-2 pb-1 text-xs font-semibold text-muted-foreground">Types</div>
					<nav className="space-y-0.5">
						{subjectTypes.map((t) => (
							<RailRow
								key={t}
								label={INBOX_SUBJECT_LABELS[t] || t}
								count={bySubject[t]}
								active={subjectType === t}
								onClick={() => onSubjectType(subjectType === t ? undefined : t)}
							/>
						))}
					</nav>
				</>
			)}

			<div className="my-3 border-t" />
			<DropdownMenu>
				<DropdownMenuTrigger asChild>
					<button
						type="button"
						className="flex w-full items-center gap-1 rounded-md px-2 py-1.5 text-left text-sm text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
					>
						<span className="flex-1 truncate">Manage notifications</span>
						<ChevronDown className="h-3.5 w-3.5 shrink-0" />
					</button>
				</DropdownMenuTrigger>
				<DropdownMenuContent align="start" className="w-56">
					<DropdownMenuItem disabled={markAllDisabled} onSelect={() => onMarkAllRead()}>
						<CheckCheck className="mr-2 h-4 w-4" />
						Mark these as read
					</DropdownMenuItem>
					<DropdownMenuSeparator />
					<DropdownMenuItem
						onSelect={() => {
							onKind(undefined);
							onSubjectType(undefined);
							onActionOnly(false);
						}}
					>
						Clear filters
					</DropdownMenuItem>
				</DropdownMenuContent>
			</DropdownMenu>
		</aside>
	);
}

// ── Row ────────────────────────────────────────────────────────────────

function HoverAction({
	label,
	icon: Icon,
	onClick,
}: {
	label: string;
	icon: LucideIcon;
	onClick: () => void;
}) {
	return (
		<Tooltip>
			<TooltipTrigger asChild>
				<button
					type="button"
					aria-label={label}
					onClick={onClick}
					className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
				>
					<Icon className="h-4 w-4" />
				</button>
			</TooltipTrigger>
			<TooltipContent>{label}</TooltipContent>
		</Tooltip>
	);
}

function ItemRow({
	item,
	checked,
	onCheck,
	onOpenDetail,
}: {
	item: InboxItem;
	checked: boolean;
	onCheck: (value: boolean) => void;
	onOpenDetail: () => void;
}) {
	const markRead = useMarkRead();
	const markUnread = useMarkUnread();
	const markDone = useMarkDone();
	const dismiss = useDismissItem();
	const reopen = useReopenItem();

	const meta = KIND_META[item.kind] ?? KIND_META.system_notice;
	const Icon = meta.icon;
	const target = internalTarget(item.action_url);
	const owner = item.subject_namespace;

	// Following the link is the act of reading it. The API is idempotent here,
	// but the guard keeps a click on an already-read row from writing a second
	// history entry that says nothing happened.
	const openRow = () => {
		if (!item.read) markRead.mutate(item.id);
	};

	return (
		<li
			className={cn(
				"group relative flex items-center gap-2 py-2 pr-3 pl-2 transition-colors hover:bg-muted/40",
				!item.read && "bg-muted/20",
			)}
		>
			{/* Covers the row so a click anywhere follows the item, with the real
			    controls lifted above it. A Link rather than a click handler keeps
			    middle-click and open-in-new-tab working. */}
			{target ? (
				<Link
					to={target.to}
					search={target.search}
					onClick={openRow}
					className="absolute inset-0"
					aria-label={item.title}
				/>
			) : (
				<button
					type="button"
					onClick={() => {
						openRow();
						onOpenDetail();
					}}
					className="absolute inset-0"
					aria-label={item.title}
				/>
			)}

			<span
				className={cn("relative z-10 h-2 w-2 shrink-0 rounded-full", !item.read && "bg-info")}
				aria-hidden
			/>
			<Checkbox
				checked={checked}
				onCheckedChange={(value) => onCheck(value === true)}
				aria-label={`Select ${item.title}`}
				className="relative z-10"
			/>
			<Icon className={cn("relative z-10 h-4 w-4 shrink-0", meta.tone)} />

			<div className="min-w-0 flex-1 leading-tight">
				<div className="truncate text-xs text-muted-foreground">
					{subjectPath(item)}
					{item.subject_type !== "system" && (
						<span className="ml-1 opacity-70">· {item.subject_type}</span>
					)}
				</div>
				<div className={cn("truncate text-sm", !item.read && "font-semibold")}>{item.title}</div>
			</div>

			{/* Metadata and hover actions occupy the same corner, the way GitHub
			    swaps one for the other, so the row does not reflow on hover. */}
			<div className="flex shrink-0 items-center gap-3 group-hover:invisible">
				{item.action_required && item.state === "open" && (
					<span className="rounded-full border border-warning/40 px-1.5 py-0.5 text-[10px] font-medium text-warning">
						needs action
					</span>
				)}
				<span className="hidden text-xs text-muted-foreground lg:inline">
					{INBOX_KIND_REASONS[item.kind] ?? item.kind}
				</span>
				{owner ? <OwnerAvatar name={owner} /> : null}
				<span className="w-24 shrink-0 text-right text-xs text-muted-foreground">
					{relativeTime(item.created_at)}
				</span>
			</div>
			{/* `top` is pinned rather than left to the static position. An abspos
			    child of a flex container resolves its static position from the
			    container's content box, which is not reliably the row's centre —
			    the sidebar badge landed on the wrong row for exactly this reason. */}
			<div className="invisible absolute top-1/2 right-3 z-10 flex -translate-y-1/2 items-center gap-0.5 group-hover:visible">
				{item.state === "open" ? (
					<>
						<HoverAction label="Done" icon={Check} onClick={() => markDone.mutate(item.id)} />
						<HoverAction label="Dismiss" icon={X} onClick={() => dismiss.mutate(item.id)} />
					</>
				) : (
					<HoverAction label="Reopen" icon={RotateCcw} onClick={() => reopen.mutate(item.id)} />
				)}
				<HoverAction
					label={item.read ? "Mark as unread" : "Mark as read"}
					icon={item.read ? EyeOff : Eye}
					onClick={() => (item.read ? markUnread.mutate(item.id) : markRead.mutate(item.id))}
				/>
				<HoverAction label="Details" icon={Info} onClick={onOpenDetail} />
			</div>
		</li>
	);
}

// ── Detail sheet ───────────────────────────────────────────────────────

function DetailBody({ itemId }: { itemId: string }) {
	const { data: item, isLoading, isError, refetch } = useInboxItem(itemId);
	const markDone = useMarkDone();
	const dismiss = useDismissItem();
	const reopen = useReopenItem();

	if (isLoading) {
		return (
			<div className="flex flex-1 items-center justify-center">
				<Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
			</div>
		);
	}
	// The query does not retry, so a failure leaves isLoading false and item
	// undefined. Falling back to the spinner here would leave it turning forever
	// with nothing on the way.
	if (isError || !item) {
		return (
			<div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
				<p className="text-sm font-medium">Could not load this item</p>
				<p className="text-xs text-muted-foreground">
					It may have been removed, or the request failed.
				</p>
				<Button size="sm" variant="outline" onClick={() => refetch()}>
					Try again
				</Button>
			</div>
		);
	}

	const target = internalTarget(item.action_url);
	const copyCommand = async () => {
		if (!item.action_command) return;
		try {
			await navigator.clipboard.writeText(item.action_command);
			toast.success("Command copied");
		} catch {
			toast.error("Could not copy the command");
		}
	};

	return (
		<div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
			<div className="text-xs text-muted-foreground">
				{new Date(item.created_at).toLocaleString()}
				{item.state !== "open" && ` · ${item.state}`}
			</div>

			{item.body && <p className="whitespace-pre-wrap text-sm text-muted-foreground">{item.body}</p>}

			<div className="flex flex-wrap gap-2">
				{target && (
					<Button asChild size="sm">
						<Link to={target.to} search={target.search}>
							Open
						</Link>
					</Button>
				)}
				{item.state === "open" ? (
					<>
						<Button
							size="sm"
							variant="outline"
							onClick={() => markDone.mutate(item.id)}
							disabled={markDone.isPending}
						>
							<Check className="mr-1 h-3.5 w-3.5" />
							Done
						</Button>
						<Button
							size="sm"
							variant="ghost"
							onClick={() => dismiss.mutate(item.id)}
							disabled={dismiss.isPending}
						>
							<X className="mr-1 h-3.5 w-3.5" />
							Dismiss
						</Button>
					</>
				) : (
					<Button
						size="sm"
						variant="outline"
						onClick={() => reopen.mutate(item.id)}
						disabled={reopen.isPending}
					>
						<RotateCcw className="mr-1 h-3.5 w-3.5" />
						Reopen
					</Button>
				)}
			</div>

			{item.action_command && (
				<div>
					<div className="mb-1 text-xs font-medium text-muted-foreground">Run this yourself</div>
					{/* Shown, never executed: the web app does not run commands. */}
					<div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 p-2">
						<code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap text-xs">
							{item.action_command}
						</code>
						<Button size="icon" variant="ghost" className="h-6 w-6" onClick={copyCommand}>
							<Copy className="h-3 w-3" />
						</Button>
					</div>
				</div>
			)}

			<div className="mt-auto pt-2">
				<div className="mb-2 text-xs font-medium text-muted-foreground">History</div>
				<ol className="space-y-1">
					{item.history.map((event) => (
						<li key={event.id} className="flex flex-wrap items-baseline gap-2 text-xs">
							<span className="font-mono text-muted-foreground">
								{new Date(event.created_at).toLocaleString()}
							</span>
							<span>{event.event}</span>
							{event.detail && <span className="text-muted-foreground">— {event.detail}</span>}
						</li>
					))}
				</ol>
			</div>
		</div>
	);
}

// ── Page ───────────────────────────────────────────────────────────────

export default function InboxPage() {
	const [bucket, setBucket] = useState<InboxState>("open");
	const [unreadOnly, setUnreadOnly] = useState(false);
	const [actionOnly, setActionOnly] = useState(false);
	const [kind, setKind] = useState<InboxKind | undefined>();
	const [subjectType, setSubjectType] = useState<string | undefined>();
	const [sort, setSort] = useState<InboxSort>("newest");
	const [group, setGroup] = useState<GroupMode>("date");
	const [search, setSearch] = useState("");
	const [query, setQuery] = useState("");
	const [page, setPage] = useState(1);
	const [selected, setSelected] = useState<Set<string>>(new Set());
	const [detailId, setDetailId] = useState<string | null>(null);

	// Typing must not fire a request per keystroke, and the delay has to clear
	// the page reset too or page 3 outlives the filter that produced it.
	useEffect(() => {
		const timer = setTimeout(() => {
			setQuery(search.trim());
			setPage(1);
		}, 300);
		return () => clearTimeout(timer);
	}, [search]);

	const listFilters: InboxFilters = useMemo(
		() => ({
			state: bucket,
			...(unreadOnly ? { unread: true } : {}),
			...(actionOnly ? { action_required: true } : {}),
			...(kind ? { kind } : {}),
			...(subjectType ? { subject_type: subjectType } : {}),
			...(query ? { q: query } : {}),
			sort,
		}),
		[bucket, unreadOnly, actionOnly, kind, subjectType, query, sort],
	);

	const { data, isLoading, isFetching, isError, refetch } = useInbox({ ...listFilters, page });
	const { data: counts } = useInboxCounts(true, { facets: true, facetState: bucket });
	const readAll = useReadAll();
	const bulk = useBulkAction();

	const items = data?.items ?? [];
	// Trust the server's page size, not a copy of its default: the numbers below
	// must describe the response they annotate.
	const total = data?.total ?? 0;
	const pageSize = data?.page_size ?? 25;
	const firstRow = (page - 1) * pageSize + 1;
	const lastRow = (page - 1) * pageSize + items.length;

	// A selection is only meaningful for rows still on screen. Keeping ids from
	// a previous page would let a bulk action hit rows the user cannot see.
	const visibleSelected = useMemo(
		() => items.filter((item) => selected.has(item.id)).map((item) => item.id),
		[items, selected],
	);
	const allChecked = items.length > 0 && visibleSelected.length === items.length;
	const someChecked = visibleSelected.length > 0 && !allChecked;

	const resetPage = () => {
		setPage(1);
		setSelected(new Set());
	};

	const toggleOne = (id: string, value: boolean) => {
		setSelected((prev) => {
			const next = new Set(prev);
			if (value) next.add(id);
			else next.delete(id);
			return next;
		});
	};

	const runBulk = (action: "read" | "unread" | "done" | "dismiss" | "reopen") => {
		if (visibleSelected.length === 0) return;
		bulk.mutate({ ids: visibleSelected, action });
		setSelected(new Set());
	};

	const groups = useMemo(() => groupItems(items, group), [items, group]);
	const filtersActive = Boolean(kind || subjectType || actionOnly || query || unreadOnly);

	return (
		<DashboardShell>
			<PageHeader title="Inbox" breadcrumbs={[{ label: "Inbox" }]} />
			{/* overflow-hidden, because the list below owns the scroll. Leaving the
			    shell's own overflow-y-auto in place produces two nested scrollbars. */}
			<DashboardContent className="min-h-0 overflow-hidden p-0">
				<div className="flex h-full min-h-0">
					<div data-testid="inbox-feed" className="flex min-h-0 min-w-0 flex-1 flex-col">
						{/* Toolbar */}
						<div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
							<div className="flex overflow-hidden rounded-lg border border-border">
								{[
									{ label: "All", value: false },
									{ label: "Unread", value: true },
								].map((tab) => (
									<button
										key={tab.label}
										type="button"
										onClick={() => {
											setUnreadOnly(tab.value);
											resetPage();
										}}
										className={cn(
											"px-3 py-1 text-sm transition-colors",
											unreadOnly === tab.value
												? "bg-muted font-medium"
												: "text-muted-foreground hover:bg-muted/50",
										)}
									>
										{tab.label}
									</button>
								))}
							</div>

							<div className="relative min-w-40 flex-1">
								<Search className="pointer-events-none absolute top-1/2 left-2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
								<Input
									value={search}
									onChange={(e) => setSearch(e.target.value)}
									placeholder="Search notifications"
									className="h-8 pl-7 text-sm"
								/>
							</div>

							<DropdownMenu>
								<DropdownMenuTrigger asChild>
									<Button variant="ghost" size="sm" className="h-8 gap-1 text-xs">
										Sort by: {SORT_LABELS[sort]}
										<ChevronDown className="h-3.5 w-3.5" />
									</Button>
								</DropdownMenuTrigger>
								<DropdownMenuContent align="end">
									<DropdownMenuRadioGroup
										value={sort}
										onValueChange={(v) => {
											setSort(v as InboxSort);
											resetPage();
										}}
									>
										{(Object.keys(SORT_LABELS) as InboxSort[]).map((value) => (
											<DropdownMenuRadioItem key={value} value={value}>
												{SORT_LABELS[value]}
											</DropdownMenuRadioItem>
										))}
									</DropdownMenuRadioGroup>
								</DropdownMenuContent>
							</DropdownMenu>

							<DropdownMenu>
								<DropdownMenuTrigger asChild>
									<Button variant="ghost" size="sm" className="h-8 gap-1 text-xs">
										Group by: {GROUP_LABELS[group]}
										<ChevronDown className="h-3.5 w-3.5" />
									</Button>
								</DropdownMenuTrigger>
								<DropdownMenuContent align="end">
									<DropdownMenuRadioGroup
										value={group}
										onValueChange={(v) => setGroup(v as GroupMode)}
									>
										{(Object.keys(GROUP_LABELS) as GroupMode[]).map((value) => (
											<DropdownMenuRadioItem key={value} value={value}>
												{GROUP_LABELS[value]}
											</DropdownMenuRadioItem>
										))}
									</DropdownMenuRadioGroup>
								</DropdownMenuContent>
							</DropdownMenu>
						</div>

						{/* List */}
						<div className="min-h-0 flex-1 overflow-y-auto p-3">
							<div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
								<div className="flex items-center gap-3 border-b bg-muted/30 px-3 py-2">
									<Checkbox
										checked={allChecked ? true : someChecked ? "indeterminate" : false}
										onCheckedChange={(value) =>
											setSelected(value === true ? new Set(items.map((i) => i.id)) : new Set())
										}
										aria-label="Select all"
										disabled={items.length === 0}
									/>
									<span className="text-xs text-muted-foreground">
										{visibleSelected.length > 0
											? `${visibleSelected.length} selected`
											: "Select all"}
									</span>
									<div className="ml-auto flex items-center gap-1">
										{visibleSelected.length > 0 ? (
											<>
												{bucket === "open" ? (
													<>
														<Button
															size="sm"
															variant="ghost"
															className="h-7 px-2 text-xs"
															disabled={bulk.isPending}
															onClick={() => runBulk("done")}
														>
															<Check className="mr-1 h-3.5 w-3.5" />
															Done
														</Button>
														<Button
															size="sm"
															variant="ghost"
															className="h-7 px-2 text-xs"
															disabled={bulk.isPending}
															onClick={() => runBulk("dismiss")}
														>
															<X className="mr-1 h-3.5 w-3.5" />
															Dismiss
														</Button>
													</>
												) : (
													<Button
														size="sm"
														variant="ghost"
														className="h-7 px-2 text-xs"
														disabled={bulk.isPending}
														onClick={() => runBulk("reopen")}
													>
														<RotateCcw className="mr-1 h-3.5 w-3.5" />
														Reopen
													</Button>
												)}
												<Button
													size="sm"
													variant="ghost"
													className="h-7 px-2 text-xs"
													disabled={bulk.isPending}
													onClick={() => runBulk("read")}
												>
													<Eye className="mr-1 h-3.5 w-3.5" />
													Read
												</Button>
											</>
										) : (
											<Button
												size="sm"
												variant="ghost"
												className="h-7 px-2 text-xs"
												disabled={readAll.isPending || items.length === 0}
												onClick={() => readAll.mutate(listFilters)}
											>
												<CheckCheck className="mr-1 h-3.5 w-3.5" />
												Mark all as read
											</Button>
										)}
									</div>
								</div>

								{isLoading ? (
									<div className="flex items-center justify-center p-10">
										<Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
									</div>
								) : isError ? (
									/* The query does not retry, so a failure leaves isLoading false
									   and items empty. Without this branch the empty state claims
									   the user is all caught up, which is the opposite of true. */
									<div className="flex flex-col items-center gap-2 p-10 text-center">
										<TriangleAlert className="h-6 w-6 text-destructive" />
										<p className="text-sm font-medium">Could not load your inbox</p>
										<p className="max-w-sm text-xs text-muted-foreground">
											The request failed, so this list is not showing anything - not
											even items you may have waiting.
										</p>
										<Button size="sm" variant="outline" onClick={() => refetch()}>
											Try again
										</Button>
									</div>
								) : items.length === 0 ? (
									<div className="flex flex-col items-center gap-2 p-10 text-center">
										<InboxIcon className="h-6 w-6 text-muted-foreground" />
										<p className="text-sm font-medium">
											{filtersActive ? "No matching notifications" : "You are all caught up"}
										</p>
										<p className="max-w-sm text-xs text-muted-foreground">
											{filtersActive
												? "Try clearing a filter or searching for something else."
												: "Review assignments, decisions on your submissions, and update notices show up here."}
										</p>
									</div>
								) : (
									groups.map((section) => (
										<div key={section.label || "all"}>
											{section.label && (
												<div className="border-b bg-muted/20 px-3 py-1 text-xs font-medium text-muted-foreground">
													{section.label}
												</div>
											)}
											<ul className="divide-y">
												{section.items.map((item) => (
													<ItemRow
														key={item.id}
														item={item}
														checked={selected.has(item.id)}
														onCheck={(value) => toggleOne(item.id, value)}
														onOpenDetail={() => setDetailId(item.id)}
													/>
												))}
											</ul>
										</div>
									))
								)}

								{/* Without this, anything past the first page simply does not
								    exist as far as the web UI is concerned. */}
								{total > pageSize && (
									<div className="flex items-center justify-between border-t px-3 py-1.5">
										<span className="text-xs text-muted-foreground">
											{items.length > 0 ? `${firstRow}–${lastRow} of ${total}` : `0 of ${total}`}
										</span>
										<div className="flex gap-1">
											<Button
												size="sm"
												variant="ghost"
												className="h-7 px-2 text-xs"
												disabled={page === 1 || isFetching}
												onClick={() => {
													setPage((p) => Math.max(1, p - 1));
													setSelected(new Set());
												}}
											>
												Previous
											</Button>
											<Button
												size="sm"
												variant="ghost"
												className="h-7 px-2 text-xs"
												disabled={lastRow >= total || isFetching}
												onClick={() => {
													setPage((p) => p + 1);
													setSelected(new Set());
												}}
											>
												Next
											</Button>
										</div>
									</div>
								)}
							</div>
						</div>
					</div>

					<InboxRail
						bucket={bucket}
						kind={kind}
						subjectType={subjectType}
						actionOnly={actionOnly}
						counts={counts}
						onBucket={(b) => {
							setBucket(b);
							resetPage();
						}}
						onKind={(k) => {
							setKind(k);
							resetPage();
						}}
						onSubjectType={(t) => {
							setSubjectType(t);
							resetPage();
						}}
						onActionOnly={(v) => {
							setActionOnly(v);
							resetPage();
						}}
						onMarkAllRead={() => readAll.mutate(listFilters)}
						markAllDisabled={readAll.isPending || items.length === 0}
					/>
				</div>
			</DashboardContent>

			<Sheet open={detailId !== null} onOpenChange={(open) => !open && setDetailId(null)}>
				<SheetContent side="right" className="flex w-full flex-col gap-4 sm:max-w-lg">
					<SheetHeader>
						<SheetTitle className="pr-6 text-base">
							{items.find((i) => i.id === detailId)?.title ?? "Notification"}
						</SheetTitle>
						<SheetDescription className="text-xs">
							{detailId
								? (INBOX_KIND_LABELS[items.find((i) => i.id === detailId)?.kind as InboxKind] ??
									"Details and history")
								: "Details and history"}
						</SheetDescription>
					</SheetHeader>
					{detailId && <DetailBody itemId={detailId} />}
				</SheetContent>
			</Sheet>
		</DashboardShell>
	);
}
