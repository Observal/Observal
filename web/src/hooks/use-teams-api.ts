// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { teams } from "@/lib/api";
import type { TeamMemberUpsertBody, TeamUpdateBody } from "@/lib/types";

const JOIN_REQUESTS_KEY = (teamId: string | undefined) => ["teams", teamId, "join-requests"];

const TEAMS_STALE_MS = 5 * 60 * 1000;
const TEAM_REFRESH_MS = 10 * 1000;

export function useTeams(enabled = true) {
	return useQuery({
		queryKey: ["teams"],
		queryFn: teams.list,
		enabled,
		staleTime: TEAMS_STALE_MS,
		refetchOnWindowFocus: "always",
	});
}

export function useAllTeams() {
	return useQuery({
		queryKey: ["teams", "all"],
		queryFn: teams.listAll,
		staleTime: TEAMS_STALE_MS,
		refetchOnWindowFocus: "always",
	});
}

export function useTeam(id?: string) {
	return useQuery({
		queryKey: ["teams", id],
		queryFn: () => teams.get(id || ""),
		enabled: !!id,
		staleTime: TEAMS_STALE_MS,
		refetchInterval: TEAM_REFRESH_MS,
		refetchOnWindowFocus: "always",
	});
}

/**
 * Resolve a teamspace from the handle in the URL via GET /teams/by-handle.
 *
 * Server-side resolution replaces the old client-side filter over `/teams/all`
 * so a shared /teamspaces/{handle} link resolves in one request and a wrong
 * handle is a definite 404 rather than "not in my discoverable list".
 * `notFound` is reported explicitly so the detail page can say the handle is
 * wrong instead of rendering a blank shell.
 */
export function useTeamByHandle(handle: string | undefined) {
	const query = useQuery({
		queryKey: ["teams", "by-handle", handle],
		queryFn: () => teams.byHandle(handle!),
		enabled: !!handle,
		staleTime: TEAMS_STALE_MS,
		refetchInterval: TEAM_REFRESH_MS,
		refetchOnWindowFocus: "always",
		retry: (failureCount, error) =>
			(error as Error & { status?: number }).status === 404 ? false : failureCount < 2,
	});
	const notFound = (query.error as (Error & { status?: number }) | null)?.status === 404;
	return {
		team: query.data,
		isLoading: query.isLoading,
		isError: query.isError && !notFound,
		error: query.error,
		refetch: query.refetch,
		notFound,
	};
}

export function useTeamMembers(teamId?: string, enabled = true) {
	return useQuery({
		queryKey: ["teams", teamId, "members"],
		queryFn: () => teams.members(teamId || ""),
		enabled: !!teamId && enabled,
		refetchOnWindowFocus: "always",
	});
}

export function useCreateTeam() {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: teams.create,
		onSuccess: (team) => {
			qc.invalidateQueries({ queryKey: ["teams"] });
			toast.success(
				team.visibility_request_status === "pending"
					? "Public teamspace submitted for review"
					: "Teamspace created",
			);
		},
		onError: (err: Error) => toast.error(err.message || "Failed to create teamspace"),
	});
}

export function useClaimPersonalTeamspace() {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: teams.claimPersonal,
		onSuccess: (team) => {
			qc.invalidateQueries({ queryKey: ["teams"] });
			toast.success(`${team.name} is yours — private and ready to publish into`);
		},
		onError: (err: Error) => toast.error(err.message || "Failed to claim your teamspace"),
	});
}

export function useUpdateTeam() {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: ({ id, body }: { id: string; body: TeamUpdateBody }) =>
			teams.update(id, body),
		onSuccess: (_data, vars) => {
			qc.invalidateQueries({ queryKey: ["teams"] });
			qc.invalidateQueries({ queryKey: ["teams", vars.id] });
			toast.success("Teamspace updated");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to update teamspace"),
	});
}

export function useUpdateTeamVisibility(teamId?: string) {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: (visibility: "public" | "private") =>
			teams.updateVisibility(teamId || "", visibility),
		onSuccess: (data) => {
			qc.invalidateQueries({ queryKey: ["teams"] });
			toast.success(
				data.visibility_request_status === "pending"
					? "Public visibility submitted for review"
					: data.visibility === "private"
						? "Teamspace is now private, hidden from non-members"
						: "Teamspace is now public",
			);
		},
		onError: (err: Error) => toast.error(err.message || "Failed to change visibility"),
	});
}

export function useTeamVisibilityRequests() {
	return useQuery({
		queryKey: ["review", "team-visibility"],
		queryFn: teams.visibilityRequests,
		refetchInterval: TEAM_REFRESH_MS,
		refetchOnWindowFocus: "always",
	});
}

export function useDecideTeamVisibility() {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: ({ id, approve, reason }: { id: string; approve: boolean; reason?: string }) =>
			approve ? teams.approveVisibility(id) : teams.rejectVisibility(id, reason),
		onSuccess: (_data, vars) => {
			qc.invalidateQueries({ queryKey: ["review", "team-visibility"] });
			qc.invalidateQueries({ queryKey: ["teams"] });
			toast.success(vars.approve ? "Teamspace is now public" : "Public visibility rejected");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to review teamspace visibility"),
	});
}

export function useDeleteTeam() {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: teams.delete,
		onSuccess: () => {
			qc.invalidateQueries({ queryKey: ["teams"] });
			toast.success("Teamspace deleted");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to delete teamspace"),
	});
}

export function useUpsertTeamMember(teamId?: string) {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: (body: TeamMemberUpsertBody) =>
			teams.upsertMember(teamId || "", body),
		onSuccess: () => {
			// Broad prefix: the header's by-handle member count must move too.
			qc.invalidateQueries({ queryKey: ["teams"] });
			toast.success("Team member saved");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to save member"),
	});
}

export function useRemoveTeamMember(teamId?: string) {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: (userId: string) => teams.removeMember(teamId || "", userId),
		onSuccess: () => {
			// Broad prefix: the header's by-handle member count must move too.
			qc.invalidateQueries({ queryKey: ["teams"] });
			toast.success("Member removed");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to remove member"),
	});
}

export function useTeamInvites(teamId: string | undefined, enabled = true) {
	return useQuery({
		queryKey: ["teams", teamId, "invites"],
		queryFn: () => teams.invites(teamId || ""),
		enabled: !!teamId && enabled,
	});
}

export function useCreateTeamInvite(teamId?: string) {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: (body: { name?: string; expires_in_days?: number; max_uses?: number | null }) =>
			teams.createInvite(teamId || "", body),
		onSuccess: () => qc.invalidateQueries({ queryKey: ["teams", teamId, "invites"] }),
		onError: (err: Error) => toast.error(err.message || "Failed to create invite"),
	});
}

export function useRevokeTeamInvite(teamId?: string) {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: (inviteId: string) => teams.revokeInvite(teamId || "", inviteId),
		onSuccess: () => {
			qc.invalidateQueries({ queryKey: ["teams", teamId, "invites"] });
			toast.success("Invite revoked");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to revoke invite"),
	});
}

export function useDeleteTeamInvite(teamId?: string) {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: (inviteId: string) => teams.deleteInvite(teamId || "", inviteId),
		onSuccess: () => {
			qc.invalidateQueries({ queryKey: ["teams", teamId, "invites"] });
			toast.success("Unused invite deleted");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to delete invite"),
	});
}

export function useTeamInviteRequests(teamId: string | undefined, inviteId: string | undefined) {
	return useQuery({
		queryKey: ["teams", teamId, "invites", inviteId, "requests"],
		queryFn: () => teams.inviteRequests(teamId || "", inviteId || ""),
		enabled: !!teamId && !!inviteId,
	});
}

export function useTeamInvitePreview(token: string | undefined) {
	return useQuery({
		queryKey: ["team-invite", token],
		queryFn: () => teams.previewInvite(token || ""),
		enabled: !!token,
		refetchInterval: TEAM_REFRESH_MS,
		refetchOnWindowFocus: "always",
		retry: false,
	});
}

/** Every join request for a teamspace, including pending requests and decision history. */
export function useJoinRequests(teamId: string | undefined, enabled = true) {
	return useQuery({
		queryKey: JOIN_REQUESTS_KEY(teamId),
		queryFn: () => teams.joinRequests(teamId || ""),
		enabled: !!teamId && enabled,
		refetchOnWindowFocus: "always",
	});
}

/** The caller's own requests for one teamspace, for the request/pending state. */
export function useMyJoinRequests(teamId: string | undefined, enabled = true) {
	return useQuery({
		queryKey: ["teams", teamId, "join-requests", "mine"],
		queryFn: () => teams.myJoinRequests(teamId || ""),
		enabled: !!teamId && enabled,
		refetchOnWindowFocus: "always",
	});
}

export function useRequestJoin(teamId?: string) {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: (body: { message?: string; invite_token?: string }) => teams.requestJoin(teamId || "", body),
		onSuccess: () => {
			qc.invalidateQueries({ queryKey: JOIN_REQUESTS_KEY(teamId) });
			toast.success("Join request sent — a team owner will review it");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to send join request"),
	});
}

export function useDecideJoinRequest(teamId?: string) {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: ({
			requestId,
			approve,
			reason,
		}: {
			requestId: string;
			approve: boolean;
			reason?: string;
		}) =>
			approve
				? teams.approveJoinRequest(teamId || "", requestId)
				: teams.rejectJoinRequest(teamId || "", requestId, reason ? { reason } : undefined),
		onSuccess: (_data, vars) => {
			// The broad prefix also refreshes the by-handle query behind the page
			// header, so the member count moves the moment the roster does.
			qc.invalidateQueries({ queryKey: ["teams"] });
			toast.success(vars.approve ? "Request approved — member added" : "Request rejected");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to decide the request"),
	});
}

export function useCancelJoinRequest(teamId?: string) {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: (requestId: string) => teams.cancelJoinRequest(teamId || "", requestId),
		onSuccess: () => {
			qc.invalidateQueries({ queryKey: JOIN_REQUESTS_KEY(teamId) });
			toast.success("Join request withdrawn");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to withdraw the request"),
	});
}

export function useLeaveTeam() {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: teams.leave,
		onSuccess: () => {
			qc.invalidateQueries({ queryKey: ["teams"] });
			toast.success("Left teamspace");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to leave teamspace"),
	});
}
