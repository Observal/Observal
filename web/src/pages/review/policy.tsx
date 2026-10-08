// SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import { prReviews } from "@/lib/api";
import type { ReviewPolicy } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

const kinds = ["agent", "mcp", "skill", "hook", "prompt", "sandbox"];
const defaults: ReviewPolicy = { required_approvals: {}, self_approval: "not_counted", dismiss_stale_approvals: true, require_resolved_threads: false, auto_publish: false };

export default function ReviewPolicyPage({ teamId }: { teamId?: string }) {
  const { data, isPending, isError, refetch } = useQuery({ queryKey: ["review-policy", teamId], queryFn: () => teamId ? prReviews.teamPolicy(teamId) : prReviews.orgPolicy() });
  const [value, setValue] = useState<ReviewPolicy>(defaults);
  useEffect(() => { if (data) setValue({ ...defaults, ...data }); }, [data]);
  const save = useMutation({ mutationFn: () => teamId ? prReviews.setTeamPolicy(teamId, value) : prReviews.setOrgPolicy(value), onSuccess: async () => { toast.success("Review policy saved and open reviews re-evaluated"); await refetch(); }, onError: (error: Error) => toast.error(error.message) });
  const flag = (name: "dismiss_stale_approvals" | "require_resolved_threads" | "auto_publish", label: string, description: string) => <label className="flex items-center justify-between gap-4 border-b border-border py-4"><span><span className="block text-sm font-medium">{label}</span><span className="block text-xs text-muted-foreground">{description}</span></span><Switch checked={value[name]} onCheckedChange={checked => setValue(previous => ({ ...previous, [name]: checked }))} /></label>;
  return <div className="mx-auto max-w-4xl space-y-5 px-4 py-6 sm:px-6"><Link to={teamId ? "/teamspaces" : "/settings"} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> {teamId ? "Teamspaces" : "Settings"}</Link><header><h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight"><ShieldCheck className="size-6" /> {teamId ? "Teamspace review policy" : "Review policy"}</h1><p className="mt-2 text-sm text-muted-foreground">Control the publication gate for new and open reviews. Changes re-evaluate open reviews immediately.</p></header>{isPending ? <p className="text-sm text-muted-foreground">Loading policy…</p> : isError ? <p className="text-sm text-destructive">Could not load review policy.</p> : <form onSubmit={event => { event.preventDefault(); save.mutate(); }} className="rounded-xl border border-border bg-card p-5"><h2 className="text-sm font-semibold">Required approvals by type</h2><p className="mt-1 text-xs text-muted-foreground">The organization default applies unless a teamspace sets a stricter policy.</p><div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">{kinds.map(kind => <label key={kind} className="text-sm capitalize">{kind}<Input type="number" min={1} max={5} className="mt-1" value={value.required_approvals[kind] ?? 1} onChange={event => setValue(previous => ({ ...previous, required_approvals: { ...previous.required_approvals, [kind]: Number(event.target.value) } }))} /></label>)}</div><div className="mt-6 border-t border-border">{flag("dismiss_stale_approvals", "Dismiss stale approvals", "Approvals on earlier revisions stop counting.")}{flag("require_resolved_threads", "Require resolved conversations", "Unresolved threads block publication.")}{flag("auto_publish", "Publish automatically", "Publish as soon as every requirement is met.")}</div><label className="mt-4 block text-sm font-medium">Self-approval<select value={value.self_approval} onChange={event => setValue(previous => ({ ...previous, self_approval: event.target.value as ReviewPolicy["self_approval"] }))} className="mt-1 block w-full rounded-md border border-border bg-background p-2"><option value="not_counted">Recorded, not counted</option><option value="counted">Counted for eligible private teamspaces</option></select></label><div className="mt-6 flex justify-end"><Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save review policy"}</Button></div></form>}</div>;
}
