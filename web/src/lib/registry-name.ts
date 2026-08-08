// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

/**
 * Display helpers for qualified registry identities (``namespace/slug``).
 *
 * The API returns the canonical slash form in ``qualified_name``. That form is
 * what commands take (``observal agent pull alice/reviewer``), but it reads
 * poorly in the UI, so listings render the bare name with the owning namespace
 * underneath as ``@alice``. Keep using ``qualified_name`` verbatim for anything
 * copy-pasted into a shell.
 */

/**
 * Canonical namespace charset: 3-32 chars, starting and ending alphanumeric,
 * hyphens and dots inside. Mirrors `observal_shared/namespace_rules.py` — keep
 * the two in sync.
 */
const NAMESPACE_RE = /^[a-z0-9][a-z0-9.-]{1,30}[a-z0-9]$/;

export const NAMESPACE_RULE_TEXT =
	"Namespaces must be 3-32 characters using lowercase letters, numbers, " +
	"hyphens, and dots, and must start and end with a letter or number";

// Server slug charset, from services/registry_namespace.py SLUG_RE.
const SLUG_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;

/**
 * The canonical `/namespace/slug` path segments, but only when both resolve
 * server-side. Migration 016 backfilled some namespaces verbatim from legacy
 * usernames (uppercase, underscores, spaces, or under 3 chars), and the
 * `/registry/resolve` endpoint lowercases and validates before matching — so a
 * card linking `/agents/John_Smith/tool` would 404. Returning null for those
 * keeps the caller on the always-working UUID route.
 */
export function canonicalRouteParts(
	namespace: string | null | undefined,
	slug: string | null | undefined,
): { namespace: string; slug: string } | null {
	const ns = namespace?.trim();
	const sl = slug?.trim();
	if (ns && sl && NAMESPACE_RE.test(ns) && SLUG_RE.test(sl)) {
		return { namespace: ns, slug: sl };
	}
	return null;
}

export interface SlugifyRegistryTextOptions {
	allowUnderscore?: boolean;
	maxLength?: number;
	preserveTrailingSeparator?: boolean;
}

const AGENT_NAME_RE = /^[a-z0-9][a-z0-9_-]*$/;

/** Normalize human input to a lowercase registry slug without adding padding. */
export function slugifyRegistryText(raw: string, options: SlugifyRegistryTextOptions = {}): string {
	const separatorPattern = options.allowUnderscore ? /[^a-z0-9_-]+/g : /[^a-z0-9-]+/g;
	let slug = raw
		.trimStart()
		.toLowerCase()
		.replace(separatorPattern, "-")
		.replace(/-+/g, "-")
		.replace(/^-+/, "");

	if (options.maxLength !== undefined) {
		slug = slug.slice(0, options.maxLength);
	}
	return options.preserveTrailingSeparator ? slug : slug.replace(/-+$/, "");
}

export function normalizeAgentName(raw: string): string {
	return slugifyRegistryText(raw, { allowUnderscore: true });
}

export function isValidAgentName(raw: string): boolean {
	return AGENT_NAME_RE.test(normalizeAgentName(raw));
}

/** Whether a username can be used verbatim as a registry namespace. */
export function isValidNamespace(handle: string | null | undefined): boolean {
	if (!handle) return false;
	const value = handle.trim().toLowerCase();
	if (value.includes("..")) return false;
	return NAMESPACE_RE.test(value);
}

/** Any shape carrying some subset of the canonical identity fields. */
export interface QualifiedIdentity {
	name?: string;
	namespace?: string;
	slug?: string;
	qualified_name?: string;
}

export interface RegistryIdentity {
	/** Bare item name, never containing a slash. */
	name: string;
	/** Owning namespace without the leading ``@``, or undefined when unknown. */
	handle?: string;
	/** Canonical ``namespace/slug`` when known, else the bare name. */
	qualified: string;
}

/**
 * Split a registry item into its display name and owning handle.
 *
 * Prefers the explicit ``namespace``/``slug`` columns and falls back to parsing
 * ``qualified_name`` so older payloads (and the leaderboard summaries, which
 * only carry the qualified form) still render a handle.
 */
export function registryIdentity(item: QualifiedIdentity | null | undefined, fallbackName = ""): RegistryIdentity {
	const qualifiedName = item?.qualified_name?.trim();
	let handle = item?.namespace?.trim() || undefined;
	let name = item?.slug?.trim() || undefined;

	if ((!handle || !name) && qualifiedName?.includes("/")) {
		const separator = qualifiedName.indexOf("/");
		handle = handle ?? qualifiedName.slice(0, separator);
		name = name ?? qualifiedName.slice(separator + 1);
	}

	// The slug is what used to follow the slash, so it keeps listings looking the
	// same minus the namespace. Fall back to the human-authored name.
	const displayName = name || item?.name?.trim() || fallbackName;

	return {
		name: displayName,
		handle: handle || undefined,
		qualified: qualifiedName || (handle && name ? `${handle}/${name}` : displayName),
	};
}

/** The canonical ``namespace/slug`` string to embed in CLI commands. */
export function qualifiedName(item: QualifiedIdentity | null | undefined, fallbackName = ""): string {
	return registryIdentity(item, fallbackName).qualified;
}

/** Single-line form for breadcrumbs and document titles, e.g. ``reviewer @alice``. */
export function registryNameWithHandle(item: QualifiedIdentity | null | undefined, fallbackName = ""): string {
	const { name, handle } = registryIdentity(item, fallbackName);
	return handle ? `${name} @${handle}` : name;
}

export type RegistryRouteType =
	| "agent"
	| "agents"
	| "mcp"
	| "mcps"
	| "skill"
	| "skills"
	| "hook"
	| "hooks"
	| "prompt"
	| "prompts"
	| "sandbox"
	| "sandboxes";

const COMPONENT_ROUTE_TYPE: Record<Exclude<RegistryRouteType, "agent" | "agents">, string> = {
	mcp: "mcps",
	mcps: "mcps",
	skill: "skills",
	skills: "skills",
	hook: "hooks",
	hooks: "hooks",
	prompt: "prompts",
	prompts: "prompts",
	sandbox: "sandboxes",
	sandboxes: "sandboxes",
};

/** Canonical web path when possible, otherwise the always-resolvable UUID path. */
export function registryItemPath(item: QualifiedIdentity | null | undefined, type: RegistryRouteType, id: string): string {
	const identity = registryIdentity(item);
	const parts = canonicalRouteParts(identity.handle, identity.name);
	if (type === "agent" || type === "agents") {
		return parts ? `/agents/${parts.namespace}/${parts.slug}` : `/agents/${id}`;
	}
	const plural = COMPONENT_ROUTE_TYPE[type];
	return parts
		? `/components/${plural}/${parts.namespace}/${parts.slug}`
		: `/components/${id}?type=${plural}`;
}
