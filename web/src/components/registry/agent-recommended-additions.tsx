// SPDX-FileCopyrightText: 2026 The Observal Authors
// SPDX-License-Identifier: Apache-2.0

import { Link } from "@tanstack/react-router";
import { Sparkles } from "lucide-react";
import { RegistryMark } from "@/components/registry/registry-mark";
// "sandbox" does not pluralise by appending "s"; the route expects "sandboxes".
import { REVERSE_TYPE_MAP } from "@/components/registry/agent-component-constants";
import { useAgentRecommendedAdditions } from "@/hooks/use-insights-api";
import type { RecommendedAddition } from "@/lib/types/admin";

const TYPE_LABELS: Record<string, string> = {
	skill: "Skill",
	hook: "Hook",
	prompt: "Prompt",
	mcp: "MCP",
	sandbox: "Sandbox",
};

/**
 * Evidence-backed add-on recommendations shown on the agent detail page.
 *
 * Drawn from the latest insight report's deterministic component shortlist
 * (`registry_offer`): public registry components this agent does not yet use
 * but might benefit from based on observed usage. Unlike the full insight
 * report, this surface exposes only public component references — no session
 * telemetry — so it is safe to show to anyone who can see the agent.
 *
 * Renders nothing when there is no data: an empty rail is worse than no rail.
 * This covers "no report yet", "report had an empty offer", and "the feature
 * was disabled at generation time" — all of which are expected, not errors.
 */
export function AgentRecommendedAdditions({ agentId }: { agentId: string }) {
	const { data, isLoading, isError } = useAgentRecommendedAdditions(agentId);

	// Loading and error states render nothing: the rail is a progressive
	// enhancement, never a blocker for the agent detail page.
	if (isLoading || isError) return null;

	const items = data?.items ?? [];
	if (items.length === 0) return null;

	return (
		<section className="space-y-3">
			<div className="flex items-start justify-between gap-3 flex-wrap">
				<div className="flex items-center gap-2">
					<Sparkles className="h-4 w-4 text-primary-accent" />
					<h3 className="font-[family-name:var(--font-display)] text-sm font-semibold">
						Recommended add-ons
					</h3>
				</div>
				<p className="text-xs text-muted-foreground max-w-prose">
					Based on observed usage of this agent — public components it
					doesn&apos;t use yet.
				</p>
			</div>

			<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
				{items.map((item: RecommendedAddition) => (
					<div
						key={`${item.type}:${item.id}`}
						className="group rounded-lg border border-border bg-card p-3 hover:border-primary/40 transition-colors"
					>
						<div className="flex items-center gap-2">
							<RegistryMark size={13} />
							<span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
								{TYPE_LABELS[item.type] ?? item.type}
							</span>
							{item.category && (
								<span className="text-xs text-muted-foreground">
									{item.category}
								</span>
							)}
						</div>

						<Link
							to="/components/$componentId"
							params={{ componentId: item.id }}
							search={{ type: REVERSE_TYPE_MAP[item.type] ?? `${item.type}s` }}
							className="mt-2 block font-medium text-sm hover:text-primary-accent break-all"
						>
							{item.name}
						</Link>

						{item.description && (
							<p className="mt-1 text-xs text-muted-foreground line-clamp-2">
								{item.description}
							</p>
						)}
					</div>
				))}
			</div>
		</section>
	);
}
