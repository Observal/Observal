// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { teams } from "@/lib/api";
import type { TeamRole } from "@/lib/types";

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

export function useTeamMembers(teamId?: string) {
	return useQuery({
		queryKey: ["teams", teamId, "members"],
		queryFn: () => teams.members(teamId || ""),
		enabled: !!teamId,
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
		mutationFn: ({ id, body }: { id: string; body: { name?: string; description?: string } }) =>
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
		mutationFn: (body: { email?: string; username?: string; user_id?: string; role?: TeamRole }) =>
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
