// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { useEffect, useState } from "react";

/**
 * Displays a non-intrusive banner when the frontend build version
 * doesn't match the server version (stale browser tab after server upgrade).
 *
 * Fetches /api/v1/config/version on mount and compares server_version
 * against NEXT_PUBLIC_APP_VERSION.
 */
export function VersionMismatchBanner() {
	const [mismatch, setMismatch] = useState<{
		server: string;
		frontend: string;
	} | null>(null);
	const [dismissed, setDismissed] = useState(false);

	useEffect(() => {
		if (sessionStorage.getItem("observal:version-mismatch-dismissed")) {
			return;
		}

		const buildVersion = process.env.NEXT_PUBLIC_APP_VERSION;
		if (!buildVersion) return;

		// Fetch server version directly
		fetch("/api/v1/config/version")
			.then((res) => (res.ok ? res.json() : null))
			.then((data) => {
				if (!data?.server_version) return;
				const serverVersion = data.server_version;
				if (serverVersion !== buildVersion && serverVersion !== "dev") {
					setMismatch({ server: serverVersion, frontend: buildVersion });
				}
			})
			.catch(() => {}); // Silently ignore failures
	}, []);

	if (!mismatch || dismissed) return null;

	const handleDismiss = () => {
		setDismissed(true);
		sessionStorage.setItem("observal:version-mismatch-dismissed", "1");
	};

	const handleRefresh = () => {
		window.location.reload();
	};

	return (
		<div className="fixed bottom-4 right-4 z-50 flex items-center gap-3 rounded-lg border bg-card p-3 shadow-lg animate-in slide-in-from-bottom-2">
			<div className="text-sm">
				<p className="font-medium">New version available</p>
				<p className="text-muted-foreground text-xs">
					v{mismatch.frontend} → v{mismatch.server}
				</p>
			</div>
			<button
				type="button"
				onClick={handleRefresh}
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
