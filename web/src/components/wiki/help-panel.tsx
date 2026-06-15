// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useRef, useState, useCallback } from "react";
import { WikiRenderer } from "./wiki-renderer";
import { loadDoc } from "@/lib/docs-loader";
import { Loader2, X, BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

interface HelpPanelProps {
	/** Doc file path relative to docs/ */
	file: string | null;
	/** Optional anchor to scroll to */
	anchor?: string;
	/** Human-readable title */
	title?: string;
	onClose: () => void;
}

export function HelpPanel({ file, anchor, title, onClose }: HelpPanelProps) {
	const [content, setContent] = useState<string | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const scrollRef = useRef<HTMLDivElement>(null);

	// Load doc content when file changes
	useEffect(() => {
		if (!file) {
			setContent(null);
			return;
		}
		setLoading(true);
		setError(null);
		loadDoc(file)
			.then((md) => {
				if (md) {
					// Strip SPDX header comments
					const cleaned = md.replace(/^<!--[\s\S]*?-->\s*\n*/m, "");
					setContent(cleaned);
				} else {
					setError("Documentation not found.");
					setContent(null);
				}
			})
			.catch(() => {
				setError("Failed to load documentation.");
				setContent(null);
			})
			.finally(() => setLoading(false));
	}, [file]);

	// Scroll to anchor when content loads
	useEffect(() => {
		if (!anchor || !content || loading) return;
		const timer = setTimeout(() => {
			const el = scrollRef.current?.querySelector(`#${anchor}`) as HTMLElement | null;
			if (el) {
				el.scrollIntoView({ behavior: "smooth", block: "start" });
				el.classList.add("bg-primary/10", "-mx-2", "px-2", "rounded");
				setTimeout(() => el.classList.remove("bg-primary/10", "-mx-2", "px-2", "rounded"), 2000);
			}
		}, 150);
		return () => clearTimeout(timer);
	}, [anchor, content, loading]);

	// Escape key closes the panel
	const handleKeyDown = useCallback(
		(e: KeyboardEvent) => {
			if (e.key === "Escape") onClose();
		},
		[onClose],
	);

	useEffect(() => {
		if (!file) return;
		document.addEventListener("keydown", handleKeyDown);
		return () => document.removeEventListener("keydown", handleKeyDown);
	}, [file, handleKeyDown]);

	if (!file) return null;

	return (
		<div className="fixed right-0 top-0 w-[min(720px,calc(100vw-260px))] min-w-[560px] border-l border-border bg-card flex flex-col h-screen z-40 shadow-xl">
			{/* Sticky header */}
			<div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-card z-10 shrink-0">
				<div className="flex items-center gap-2 min-w-0">
					<BookOpen className="h-3.5 w-3.5 text-primary shrink-0" />
					<h3 className="text-sm font-semibold truncate">
						{title || file}
					</h3>
				</div>
				<Button
					variant="ghost"
					size="sm"
					className="h-6 w-6 p-0 shrink-0"
					onClick={onClose}
					title="Close panel (Esc)"
				>
					<X className="h-4 w-4" />
				</Button>
			</div>

			{/* Scrollable content */}
			<div ref={scrollRef} className="flex-1 overflow-y-auto p-4">
				{loading ? (
					<div className="flex items-center justify-center py-12">
						<Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
					</div>
				) : error ? (
					<p className="text-sm text-muted-foreground">{error}</p>
				) : content ? (
					<WikiRenderer content={content} basePath={file} />
				) : null}
			</div>
		</div>
	);
}
