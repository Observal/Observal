// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useState, useEffect } from "react";
import { useSearch } from "@tanstack/react-router";
import { loadDoc, listDocPaths } from "@/lib/docs-loader";
import { WikiRenderer } from "@/components/wiki/wiki-renderer";
import { PageHeader } from "@/components/layouts/page-header";
import { Loader2, ChevronRight, ArrowLeft } from "lucide-react";

function organizeBySection(paths: string[]): Record<string, string[]> {
	const sections: Record<string, string[]> = {};
	for (const p of paths) {
		const parts = p.split("/");
		const section = parts.length > 1 ? parts.slice(0, -1).join("/") : "general";
		if (!sections[section]) sections[section] = [];
		sections[section].push(p);
	}
	return sections;
}

function pathToTitle(path: string): string {
	const filename = path.split("/").pop()?.replace(".md", "") || path;
	return filename
		.split("-")
		.map((w) => w.charAt(0).toUpperCase() + w.slice(1))
		.join(" ");
}

function sectionLabel(key: string): string {
	const labels: Record<string, string> = {
		"general": "General",
		"self-hosting": "Self-Hosting",
		"getting-started": "Getting Started",
		"reference": "Reference",
		"use-cases": "Use Cases",
	};
	return labels[key] || pathToTitle(key);
}

function docHref(path: string): string {
	return `/wiki?doc=${encodeURIComponent(path)}`;
}

export default function WikiPage() {
	const search = useSearch({ strict: false }) as { doc?: string };
	const activePath = search.doc || null;
	const [content, setContent] = useState<string | null>(null);
	const [loading, setLoading] = useState(false);
	const allPaths = listDocPaths();
	const sections = organizeBySection(allPaths);

	useEffect(() => {
		if (!activePath) {
			setContent(null);
			return;
		}
		setLoading(true);
		loadDoc(activePath)
			.then((md) => setContent(md ?? null))
			.catch(() => setContent(null))
			.finally(() => setLoading(false));
	}, [activePath]);

	const sortedSections = Object.entries(sections).sort(([a], [b]) => {
		const order = ["getting-started", "general", "self-hosting", "reference", "use-cases"];
		return (order.indexOf(a) === -1 ? 99 : order.indexOf(a)) - (order.indexOf(b) === -1 ? 99 : order.indexOf(b));
	});

	return (
		<div className="min-h-full bg-background">
			<PageHeader
				title={activePath ? pathToTitle(activePath) : "Wiki"}
				breadcrumbs={[
					{ label: "Registry", href: "/" },
					{ label: "Wiki" },
				]}
			/>
			<main className="px-6 py-6 lg:px-10">
				{!activePath ? (
					<div className="mx-auto max-w-5xl">
						<p className="mb-8 max-w-2xl text-sm leading-6 text-muted-foreground">
							Practical Observal wiki pages for setup, operations, registry use, and self-hosting.
						</p>
						<div className="divide-y divide-border rounded-lg border border-border bg-card/20">
							{sortedSections.map(([section, paths]) => (
								<section key={section} className="grid gap-4 px-5 py-5 md:grid-cols-[180px_minmax(0,1fr)]">
									<div>
										<h2 className="text-sm font-semibold text-foreground">{sectionLabel(section)}</h2>
										<p className="mt-1 text-xs text-muted-foreground">{paths.length} page{paths.length === 1 ? "" : "s"}</p>
									</div>
									<ul className="grid gap-x-6 gap-y-1 sm:grid-cols-2 xl:grid-cols-3">
										{paths.sort().map((p) => (
											<li key={p}>
												<a href={docHref(p)} className="group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-foreground/75 transition-colors hover:bg-muted/50 hover:text-foreground">
													<ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
													<span className="min-w-0 flex-1 truncate">{pathToTitle(p)}</span>
												</a>
											</li>
										))}
									</ul>
								</section>
							))}
						</div>
					</div>
				) : loading ? (
					<div className="flex items-center justify-center py-12">
						<Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
					</div>
				) : content ? (
					<article className="mx-auto max-w-4xl">
						<a href="/wiki" className="mb-6 inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground">
							<ArrowLeft className="h-4 w-4" />
							Back to wiki
						</a>
						<WikiRenderer content={content} basePath={activePath} />
					</article>
				) : (
					<div className="py-12 text-center">
						<p className="text-muted-foreground">Document not found.</p>
						<a href="/wiki" className="mt-3 inline-flex text-sm text-primary hover:underline">Back to wiki</a>
					</div>
				)}
			</main>
		</div>
	);
}
