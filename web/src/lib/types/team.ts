// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

// ── Teamspaces ──────────────────────────────────────────────────────

export type TeamRole = "owner" | "reviewer" | "member";

export type TeamVisibility = "public" | "private";

export interface Team {
	id: string;
	name: string;
	handle: string;
	description?: string | null;
	visibility?: TeamVisibility;
	is_personal?: boolean;
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

export interface TeamUpdateBody {
	name?: string;
	description?: string;
}

export interface TeamMemberUpsertBody {
	email?: string;
	username?: string;
	user_id?: string;
	role?: TeamRole;
}

export type TeamJoinRequestStatus = "pending" | "approved" | "rejected" | "cancelled";

export interface TeamJoinRequest {
	id: string;
	team_id: string;
	user_id: string;
	email?: string | null;
	username?: string | null;
	name?: string | null;
	status: TeamJoinRequestStatus;
	message?: string | null;
	decided_by?: string | null;
	decided_by_username?: string | null;
	decided_at?: string | null;
	decision_reason?: string | null;
	created_at?: string | null;
}
