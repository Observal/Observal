// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useEffect, useState } from "react";

/**
 * Simple semver comparison. Returns:
 *   1 if a > b
 *  -1 if a < b
 *   0 if equal
 */
function semverCompare(a: string, b: string): number {
	const pa = a.split(".").map(Number);
	const pb = b.split(".").map(Number);
	for (let i = 0; i < 3; i++) {
		const av = pa[i] || 0;
		const bv = pb[i] || 0;
		if (av > bv) return 1;
		if (av < bv) return -1;
	}
	return 0;
}

type MismatchState = {
	server: string;
	frontend: string;
	direction: "ahead" | "behind";
};

/**
 * Version gate component. Enforces frontend/server version alignment.
 *
 * - Frontend AHEAD of server: Full-page blocking overlay (cannot dismiss).
 *   This happens when a cached browser tab has a newer build than the server.
 *   User must hard-refresh to load the correct frontend version.
 *
 * - Frontend BEHIND server: Soft refresh banner (dismissable).
 *   Server was upgraded; refreshing will pull the new frontend.
 */
export function VersionMismatchBanner() {
	const [mismatch, setMismatch] = useState<MismatchState | null>(null);
	const [dismissed, setDismissed] = useState(false);
	const [refreshAttempts, setRefreshAttempts] = useState(0);

	// Hydrate refresh attempts from sessionStorage on mount
	useEffect(() => {
		const stored = sessionStorage.getItem(
			"observal:version-refresh-attempts",
		);
		if (stored) setRefreshAttempts(parseInt(stored, 10));
	}, []);

	useEffect(() => {
		const buildVersion = import.meta.env.VITE_APP_VERSION;
		if (!buildVersion) return;

		fetch("/api/v1/config/version")
			.then((res) => (res.ok ? res.json() : null))
			.then((data) => {
				if (!data?.server_version) return;
				const serverVersion = data.server_version;
				if (serverVersion === "dev") return;

				const cmp = semverCompare(buildVersion, serverVersion);
				if (cmp === 0) return; // versions match

				setMismatch({
					server: serverVersion,
					frontend: buildVersion,
					direction: cmp > 0 ? "ahead" : "behind",
				});
			})
			.catch(() => {}); // Silently ignore failures
	}, []);

	if (!mismatch) return null;

	// Frontend AHEAD of server: full-page blocking overlay (no dismiss)
	if (mismatch.direction === "ahead") {
		return (
			<div className="fixed inset-0 z-[9999] flex items-center justify-center bg-background/95 backdrop-blur-sm">
				<div className="mx-4 max-w-md rounded-xl border bg-card p-8 text-center shadow-2xl">
					<div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
						<svg
							className="h-6 w-6 text-destructive"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
							strokeWidth={2}
						>
							<path
								strokeLinecap="round"
								strokeLinejoin="round"
								d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
							/>
						</svg>
					</div>
					<h2 className="mb-2 text-lg font-semibold">
						Version Mismatch
					</h2>
					<p className="mb-4 text-sm text-muted-foreground">
						Your app (v{mismatch.frontend}) is ahead of the server
						(v{mismatch.server}). This can cause compatibility
						issues.
					</p>
					<p className="mb-6 text-xs text-muted-foreground">
						Hard refresh to load the correct version:
					</p>
					<div className="space-y-2">
						<button
							type="button"
							onClick={() => {
								const next = refreshAttempts + 1;
								sessionStorage.setItem(
									"observal:version-refresh-attempts",
									String(next),
								);
								setRefreshAttempts(next);
								window.location.reload();
							}}
							className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
						>
							Refresh Now
						</button>
						<p className="text-xs text-muted-foreground">
							<kbd className="rounded border px-1.5 py-0.5 font-mono text-xs">
								Ctrl+Shift+R
							</kbd>{" "}
							/{" "}
							<kbd className="rounded border px-1.5 py-0.5 font-mono text-xs">
								Cmd+Shift+R
							</kbd>
						</p>
						{refreshAttempts >= 2 && (
							<button
								type="button"
								onClick={() => {
									sessionStorage.removeItem(
										"observal:version-refresh-attempts",
									);
									setMismatch(null);
								}}
								className="w-full rounded-md border px-4 py-2 text-xs text-muted-foreground hover:text-foreground"
							>
								Dismiss (split deployment?)
							</button>
						)}
					</div>
				</div>
			</div>
		);
	}

	// Frontend BEHIND server: soft dismissable banner
	if (dismissed) return null;
	if (
		typeof window !== "undefined" &&
		sessionStorage.getItem("observal:version-mismatch-dismissed")
	) {
		return null;
	}

	const handleDismiss = () => {
		setDismissed(true);
		sessionStorage.setItem("observal:version-mismatch-dismissed", "1");
	};

	return (
		<div className="fixed bottom-4 right-4 z-50 flex items-center gap-3 rounded-lg border bg-card p-3 shadow-lg animate-in slide-in-from-bottom-2">
			<div className="text-sm">
				<p className="font-medium">New version available</p>
				<p className="text-muted-foreground text-xs">
					Server updated to v{mismatch.server} - refresh to get the
					latest.
				</p>
			</div>
			<button
				type="button"
				onClick={() => window.location.reload()}
				className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
			>
				Refresh
			</button>
			<button
				type="button"
				onClick={handleDismiss}
				className="text-muted-foreground hover:text-foreground text-xs"
				aria-label="Dismiss"
			>
				✕
			</button>
		</div>
	);
}
