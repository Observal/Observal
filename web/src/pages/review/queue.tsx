// SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useMemo, useState } from "react";
import { Link, useSearch } from "@tanstack/react-router";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ArrowUpRight, GitPullRequest, MessageSquare, Search, ShieldCheck } from "lucide-react";
import { auth, getUserRole, prReviews, teams } from "@/lib/api";
import type { ReviewSummary } from "@/lib/types";
import { useAuthGuard } from "@/hooks/use-auth";
import { useReviewSubscription } from "@/hooks/use-review-api";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

const filters = [
  ["my_review", "Needs my review"],
  ["ready_to_publish", "Ready to publish"],
  ["changes_requested", "Changes requested"],
  ["mine", "Mine"],
  ["open", "All open"],
  ["closed", "Closed"],
] as const;
const componentTypes = new Set(["mcp", "skill", "hook", "prompt", "sandbox"]);

function StatePill({ state }: { state: string }) {
  const tone: Record<string, string> = {
    open: "bg-info/10 text-info", changes_requested: "bg-warning/10 text-warning",
    approved: "bg-success/10 text-success", published: "bg-success text-success-foreground",
    closed: "bg-destructive/10 text-destructive",
  };
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${tone[state] ?? "bg-muted"}`}>{state.replaceAll("_", " ")}</span>;
}

function ReviewRow({ item, nested = false }: { item: ReviewSummary; nested?: boolean }) {
  return <Link to="/review/$number" params={{ number: String(item.number) }}
    className={`group flex items-start gap-3 border-b border-border px-4 py-3 transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-2 focus-visible:outline-ring ${nested ? "pl-12" : ""}`}>
    <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md bg-muted text-xs font-semibold text-muted-foreground uppercase" aria-hidden="true">{item.subject_type.slice(0, 2)}</span>
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
        <span className="truncate">{item.title}</span>
        <StatePill state={item.state} />
        {item.requested_from_me && <span className="text-xs font-normal text-warning">Requested from you</span>}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="font-mono">#{item.number}</span>
        <span className="capitalize">{item.subject_type}</span>
        <span>Revision {item.head_revision}</span>
        <span>Updated {new Date(item.updated_at).toLocaleDateString()}</span>
        {item.depends_on.length > 0 && <span>Waits on {item.depends_on.map(n => `#${n}`).join(", ")}</span>}
        <span className="sm:hidden">{item.gate.approvals}/{item.gate.required} approvals · {item.threads.unresolved} open threads · {item.checks.fail ? "Checks failing" : "Checks passed"}</span>
      </div>
    </div>
    <div className="hidden shrink-0 flex-col items-end gap-1 text-xs text-muted-foreground sm:flex">
      <span>{item.gate.approvals}/{item.gate.required} approvals</span>
      <span className="flex items-center gap-2"><MessageSquare className="size-3.5" /> {item.threads.unresolved} open <ShieldCheck className="size-3.5" /> {item.checks.fail ? "Checks failing" : "Checks passed"}</span>
    </div>
    <ArrowUpRight className="mt-1 size-4 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100" aria-hidden="true" />
  </Link>;
}

export default function ReviewQueue() {
  useAuthGuard();
  useReviewSubscription();
  const { tab: tabFromUrl } = useSearch({ from: "/_authed/review" });
  const canReviewTeamspaces = ["reviewer", "admin", "super_admin"].includes(getUserRole() ?? "");
  const [tab, setTab] = useState(tabFromUrl === "teamspaces" && !canReviewTeamspaces ? "agents" : tabFromUrl ?? "agents");
  const [filter, setFilter] = useState<string>(getUserRole() === "user" ? "open" : "my_review");
  const [search, setSearch] = useState("");
  const [selection, setSelection] = useState(0);
  useEffect(() => { if (tabFromUrl) setTab(tabFromUrl === "teamspaces" && !canReviewTeamspaces ? "agents" : tabFromUrl); }, [tabFromUrl, canReviewTeamspaces]);
  const { data: me } = useQuery({ queryKey: ["auth", "whoami"], queryFn: auth.whoami });
  const params: Record<string, string> = {
    state: filter === "closed" ? "completed" : filter === "changes_requested" ? "changes_requested" : "open",
    type: tab === "agents" ? "agent" : "component", limit: "25",
  };
  if (filter === "my_review" || filter === "ready_to_publish") params.needs = filter;
  if (filter === "mine") params.author = "me";
  if (search.trim()) params.q = search.trim();
  const { data, isPending, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ["pr-reviews", params],
    queryFn: ({ pageParam }) => prReviews.list({ ...params, ...(pageParam ? { cursor: String(pageParam) } : {}) }),
    initialPageParam: null as number | null,
    getNextPageParam: last => last.next_cursor,
    enabled: tab !== "teamspaces",
  });
  const { data: dependencies } = useQuery({ queryKey: ["pr-reviews", "open-dependencies"], queryFn: () => prReviews.list({ state: "open", type: "component", limit: "100" }), enabled: tab === "agents" });
  const { data: requests, isPending: teamPending, isError: teamError } = useQuery({ queryKey: ["review", "teamspaces"], queryFn: teams.visibilityRequests, enabled: tab === "teamspaces" });
  const rows = useMemo(() => {
    const primary = data?.pages.flatMap(page => page.items) ?? [];
    const pinned = new Set(primary.filter(item => item.subject_type === "agent").flatMap(item => item.depends_on));
    const all = [...primary, ...(dependencies?.items ?? []).filter(item => pinned.has(item.number) && !primary.some(row => row.id === item.id))];
    const filtered = all.filter(item => (tab === "components" ? componentTypes.has(item.subject_type) : item.subject_type === "agent" || pinned.has(item.number)) && (filter !== "closed" || ["published", "closed"].includes(item.state)));
    return [...filtered].sort((a, b) => Number(b.requested_from_me) - Number(a.requested_from_me));
  }, [data, dependencies, tab, filter]);
  const byNumber = new Map(rows.map(row => [row.number, row]));
  const children = new Set(rows.flatMap(row => row.depends_on));
  const ordered = rows.flatMap(row => children.has(row.number) && row.subject_type !== "agent" ? [] : [row, ...row.depends_on.map(n => byNumber.get(n)).filter((entry): entry is ReviewSummary => !!entry)]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.altKey || event.metaKey || event.ctrlKey) return;
      if (event.key === "j" || event.key === "k") { event.preventDefault(); setSelection(index => Math.max(0, Math.min(ordered.length - 1, index + (event.key === "j" ? 1 : -1)))); }
      if (event.key === "Enter" && ordered[selection]) window.location.assign(`/review/${ordered[selection].number}`);
      if (event.key === "o" && ordered[selection]) window.open(`/review/${ordered[selection].number}`, "_blank", "noopener");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ordered, selection]);
  const tabs = canReviewTeamspaces ? ["agents", "components", "teamspaces"] as const : ["agents", "components"] as const;
  return <div className="mx-auto max-w-7xl space-y-5 px-4 py-6 sm:px-6">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-2xl font-semibold tracking-tight">Review</h1><p className="mt-1 text-sm text-muted-foreground">Review and publish registry changes.</p></div><GitPullRequest className="size-6 text-muted-foreground" aria-hidden="true" /></header>
    <nav aria-label="Review type" className="flex gap-1 border-b border-border">{tabs.map(name => <button key={name} type="button" onClick={() => { setTab(name); setSelection(0); }} className={`border-b-2 px-3 py-2 text-sm capitalize transition-colors ${tab === name ? "border-foreground font-semibold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{name}</button>)}</nav>
    {tab !== "teamspaces" && <div className="flex flex-wrap items-center gap-2">{filters.map(([key, label]) => <button type="button" key={key} onClick={() => { setFilter(key); setSelection(0); }} aria-pressed={filter === key} className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${filter === key ? "border-foreground bg-foreground text-background" : "border-border bg-card text-muted-foreground hover:text-foreground"}`}>{label}</button>)}<label className="relative ml-auto min-w-44"><Search aria-hidden="true" className="pointer-events-none absolute left-2 top-2 size-4 text-muted-foreground" /><Input aria-label="Search reviews" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search reviews" className="h-8 pl-8" /></label></div>}
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      {tab === "teamspaces" ? teamPending ? <div className="space-y-2 p-4"><Skeleton className="h-12" /><Skeleton className="h-12" /></div> : teamError ? <p className="p-8 text-sm text-destructive">Could not load requests.</p> : requests?.length ? requests.map(team => <Link key={team.team_id} to="/review/teamspace/$teamId" params={{ teamId: team.team_id }} className="flex items-center justify-between border-b border-border px-4 py-3 text-sm hover:bg-muted/50"><span>{team.name} · requests public visibility</span><ArrowUpRight className="size-4" /></Link>) : <p className="p-10 text-center text-sm text-muted-foreground">No teamspace requests need a decision.</p>
      : isPending ? <div className="space-y-2 p-4"><Skeleton className="h-16" /><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
      : isError ? <div className="p-8 text-center text-sm">Could not load reviews. <button className="underline" type="button" onClick={() => refetch()}>Try again</button></div>
      : ordered.length ? <>{ordered.map((item, index) => <div key={item.id} className={index === selection ? "bg-muted/30" : ""}><ReviewRow item={item} nested={children.has(item.number) && item.subject_type !== "agent"} /></div>)}</>
      : <div className="p-12 text-center"><GitPullRequest className="mx-auto size-6 text-muted-foreground" /><p className="mt-3 text-sm font-medium">{hasNextPage ? "No matches on this page" : "Nothing to review here"}</p><p className="mt-1 text-xs text-muted-foreground">{hasNextPage ? "Load more reviews to keep searching." : "Try another filter or come back after the next submission."}</p></div>}
    </div>
    {tab !== "teamspaces" && <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground"><p>{ordered.length} reviews · j/k to select · Enter to open · o for new tab{me && getUserRole() === "super_admin" ? " · Policy in Settings" : ""}</p>{hasNextPage && <button type="button" onClick={() => fetchNextPage()} disabled={isFetchingNextPage} className="rounded-md border border-border px-3 py-2 text-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50">{isFetchingNextPage ? "Loading reviews…" : "Load more reviews"}</button>}</div>}
  </div>;
}
