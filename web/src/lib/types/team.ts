// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

// ── Teamspaces ──────────────────────────────────────────────────────

export type TeamRole = "owner" | "reviewer" | "member";

export interface Team {
	id: string;
	name: string;
	handle: string;
	description?: string | null;
	role?: TeamRole | null;
	member_count?: number | null;
	created_at?: string;
}

export interface TeamMember {
	id: string;
	email: string;
	username?: string | null;
	name?: string | null;
	role: TeamRole;
}
