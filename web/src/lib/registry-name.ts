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
