// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

/**
 * Product analytics (PostHog) - public-instance only, off by default.
 *
 * posthog-js is initialized only when the server's public config says
 * analytics is enabled (PRODUCT_ANALYTICS_ENABLED + key, server-side gate).
 * Deliberate SOC 2 / privacy posture, not an oversight:
 *   - no autocapture, no pageview capture, no session recording
 *   - person profiles for identified users only (distinct id = user UUID)
 *   - the ONLY frontend event is `insights_viewed`
 *   - users in orgs with trace_privacy=true emit nothing
 *
 * This module also persists first-touch UTM attribution (90-day expiry,
 * first touch wins) which signup flows forward to the server so the
 * server-side `user_signed_up` event carries acquisition channel.
 */

import type { PostHog } from "posthog-js";
import { auth, type ProductAnalyticsConfig } from "./api";

// ── First-touch UTM attribution ──────────────────────────────────────

const FIRST_TOUCH_KEY = "observal_first_touch";
const FIRST_TOUCH_TTL_MS = 90 * 24 * 60 * 60 * 1000; // 90 days

export type FirstTouch = {
	utm_source: string | null;
	utm_medium: string | null;
	utm_campaign: string | null;
};

type StoredFirstTouch = FirstTouch & { captured_at: number };

function readStoredFirstTouch(): StoredFirstTouch | null {
	try {
		const raw = localStorage.getItem(FIRST_TOUCH_KEY);
		if (!raw) return null;
		const parsed = JSON.parse(raw) as StoredFirstTouch;
		if (!parsed.captured_at || Date.now() - parsed.captured_at > FIRST_TOUCH_TTL_MS) {
			localStorage.removeItem(FIRST_TOUCH_KEY);
			return null;
		}
		return parsed;
	} catch {
		return null;
	}
}

/** Capture UTM params from the current URL. First touch wins: an existing
 * unexpired record is never overwritten. Call as early as possible on load. */
export function storeFirstTouch(): void {
	try {
		if (readStoredFirstTouch()) return;
		const params = new URLSearchParams(window.location.search);
		const source = params.get("utm_source");
		const medium = params.get("utm_medium");
		const campaign = params.get("utm_campaign");
		if (!source && !medium && !campaign) return;
		const record: StoredFirstTouch = {
			utm_source: source,
			utm_medium: medium,
			utm_campaign: campaign,
			captured_at: Date.now(),
		};
		localStorage.setItem(FIRST_TOUCH_KEY, JSON.stringify(record));
	} catch {
		// localStorage unavailable - attribution simply degrades to organic
	}
}

/** Stored first-touch UTMs (nulls when absent/expired), for signup payloads. */
export function getFirstTouch(): FirstTouch {
	const stored = readStoredFirstTouch();
	return {
		utm_source: stored?.utm_source ?? null,
		utm_medium: stored?.utm_medium ?? null,
		utm_campaign: stored?.utm_campaign ?? null,
	};
}

// ── PostHog client (gated) ───────────────────────────────────────────

let client: PostHog | null = null;
let workspaceId: string | null = null;
// true once we know the user's org opted into trace privacy
let suppressed = false;
let userResolved = false;

/** Initialize posthog-js. No-op unless the server-provided config says
 * analytics is enabled. Never throws. */
export async function initAnalytics(cfg: ProductAnalyticsConfig | undefined): Promise<void> {
	if (!cfg?.enabled || !cfg.posthog_key) return;
	try {
		const { default: posthog } = await import("posthog-js");
		posthog.init(cfg.posthog_key, {
			api_host: cfg.posthog_host ?? undefined,
			autocapture: false,
			capture_pageview: false,
			disable_session_recording: true,
			person_profiles: "identified_only",
		});
		client = posthog;
	} catch {
		client = null;
	}
}

/** Record the authenticated user: identify by UUID only (no email/name) and
 * remember org context + trace-privacy suppression. */
export function setAnalyticsUser(user: {
	id: string;
	org_id?: string | null;
	trace_privacy?: boolean;
}): void {
	workspaceId = user.org_id ?? null;
	suppressed = !!user.trace_privacy;
	userResolved = true;
	if (client && !suppressed) {
		client.identify(user.id);
	}
}

export function resetAnalyticsUser(): void {
	workspaceId = null;
	suppressed = false;
	userResolved = false;
	client?.reset();
}

// ── Events ───────────────────────────────────────────────────────────

let lastInsightsKey: string | null = null;
let lastInsightsAt = 0;

/** Fire `insights_viewed` once per page visit (deduped against StrictMode
 * double-mount and re-renders). */
export async function trackInsightsViewed(reportId: string): Promise<void> {
	if (!client) return;

	const now = Date.now();
	if (lastInsightsKey === reportId && now - lastInsightsAt < 5000) return;
	lastInsightsKey = reportId;
	lastInsightsAt = now;

	if (!userResolved) {
		try {
			setAnalyticsUser(await auth.whoami());
		} catch {
			return;
		}
	}
	if (suppressed) return;

	client.capture("insights_viewed", { workspace_id: workspaceId });
}
