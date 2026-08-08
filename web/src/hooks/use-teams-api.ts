// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { teams } from "@/lib/api";
import type { TeamMemberUpsertBody, TeamUpdateBody } from "@/lib/types";

const TEAMS_STALE_MS = 5 * 60 * 1000;

export function useTeams() {
	return useQuery({ queryKey: ["teams"], queryFn: teams.list, staleTime: TEAMS_STALE_MS });
}

export function useAllTeams() {
	return useQuery({ queryKey: ["teams", "all"], queryFn: teams.listAll, staleTime: TEAMS_STALE_MS });
}

export function useTeam(id?: string) {
	return useQuery({
		queryKey: ["teams", id],
		queryFn: () => teams.get(id || ""),
		enabled: !!id,
		staleTime: TEAMS_STALE_MS,
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
	});
}

export function useCreateTeam() {
	const qc = useQueryClient();
	return useMutation({
		mutationFn: teams.create,
		onSuccess: () => {
			qc.invalidateQueries({ queryKey: ["teams"] });
			toast.success("Teamspace created");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to create teamspace"),
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
			qc.invalidateQueries({ queryKey: ["teams", teamId, "members"] });
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
			qc.invalidateQueries({ queryKey: ["teams", teamId, "members"] });
			toast.success("Member removed");
		},
		onError: (err: Error) => toast.error(err.message || "Failed to remove member"),
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
