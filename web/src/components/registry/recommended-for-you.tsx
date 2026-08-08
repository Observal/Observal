// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { Link } from "@tanstack/react-router";
import { Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CardSkeleton } from "@/components/shared/skeleton-layouts";
import { RegistryMark } from "@/components/registry/registry-mark";
// "sandbox" does not pluralise by appending "s"; the route expects "sandboxes".
import { REVERSE_TYPE_MAP } from "@/components/registry/agent-component-constants";
import {
	useDismissRecommendation,
	useMyRecommendations,
} from "@/hooks/use-recommendations-api";
import { registryItemPath } from "@/lib/registry-name";
import { compactNumber } from "@/lib/utils";

const TYPE_LABELS: Record<string, string> = {
	skill: "Skill",
	hook: "Hook",
	prompt: "Prompt",
	mcp: "MCP",
	sandbox: "Sandbox",
};

/**
 * Personalised component rail on the registry home page.
 *
 * Renders nothing at all when there is nothing worth showing — an empty rail
 * is worse than no rail. When the user has no session history the copy says
 * "popular" rather than implying personalisation that did not happen.
 */
export function RecommendedForYou({ limit = 6 }: { limit?: number }) {
	const { data, isLoading, isError } = useMyRecommendations(limit);
	const dismiss = useDismissRecommendation();

	if (isError) return null;

	if (isLoading) {
		return (
			<section className="space-y-3">
				<h2 className="font-[family-name:var(--font-display)] text-sm font-semibold">
					Recommended for you
				</h2>
				<CardSkeleton />
			</section>
		);
	}

	const items = data?.items ?? [];
	const personalized = data?.personalized ?? false;
	const sessions = data?.profile_sessions ?? 0;

	// An empty rail used to render nothing at all, which is indistinguishable
	// from the feature being broken or absent. Say why instead.
	if (items.length === 0) {
		return (
			<section className="space-y-3">
				<div className="flex items-center gap-2">
					<Sparkles className="h-4 w-4 text-muted-foreground" />
					<h2 className="font-[family-name:var(--font-display)] text-sm font-semibold">
						Recommended for you
					</h2>
				</div>
				<div className="rounded-lg border border-border bg-card px-4 py-3">
					<p className="text-sm text-muted-foreground">
						Nothing to recommend right now. Either the registry has no components
						visible to you, or you have already installed or dismissed them all.
					</p>
				</div>
			</section>
		);
	}

	// Sub-heading is the honest part: it must never imply personalisation
	// that did not happen, and it should say what would improve it.
	const subtitle = personalized
		? data?.topics && data.topics.length > 0
			? `Based on ${sessions} session${sessions === 1 ? "" : "s"} — mostly ${data.topics.slice(0, 3).join(", ")}`
			: `Based on ${sessions} session${sessions === 1 ? "" : "s"} of your activity`
		: "No session history yet, so these are simply the most-used components. Run a few sessions and this becomes personal.";

	return (
		<section className="space-y-3">
			<div className="flex items-start justify-between gap-3 flex-wrap">
				<div className="flex items-center gap-2">
					<Sparkles className={`h-4 w-4 ${personalized ? "text-primary-accent" : "text-muted-foreground"}`} />
					<h2 className="font-[family-name:var(--font-display)] text-sm font-semibold">
						{personalized ? "Recommended for you" : "Popular in your registry"}
					</h2>
				</div>
				<p className="text-xs text-muted-foreground max-w-prose">{subtitle}</p>
			</div>

			<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
				{items.map((item) => (
					<div
						key={`${item.type}:${item.id}`}
						className="group relative rounded-lg border border-border bg-card p-3 hover:border-primary/40 transition-colors"
					>
						<Button
							variant="ghost"
							size="sm"
							aria-label={`Dismiss ${item.name}`}
							className="absolute top-1.5 right-1.5 h-6 w-6 p-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
							disabled={dismiss.isPending}
							onClick={() => dismiss.mutate({ type: item.type, id: item.id })}
						>
							<X className="h-3.5 w-3.5" />
						</Button>

						<div className="flex items-center gap-2">
							<RegistryMark size={13} />
							<span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
								{TYPE_LABELS[item.type] ?? item.type}
							</span>
							{item.download_count > 0 && (
								<span className="text-xs text-muted-foreground">
									{compactNumber(item.download_count)} installs
								</span>
							)}
						</div>

						<Link
							to={registryItemPath(item, REVERSE_TYPE_MAP[item.type] ?? "mcps", item.id)}
							className="mt-2 block font-medium text-sm hover:text-primary-accent break-all pr-6"
						>
							{item.name}
						</Link>

						<p className="mt-1 text-xs text-muted-foreground line-clamp-2">
							{item.description}
						</p>
						<p className="mt-2 text-xs text-primary-accent/80">{item.reason}</p>
					</div>
				))}
			</div>
		</section>
	);
}
