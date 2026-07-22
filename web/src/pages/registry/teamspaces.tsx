// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import { LogOut, Loader2, Plus, Trash2, Users } from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { PickerSelect } from "@/components/ui/picker-select";
import { EmptyState } from "@/components/shared/empty-state";
import { UserSearchInput } from "@/components/shared/user-search-input";
import { getUserRole } from "@/lib/api";
import { hasMinRole } from "@/hooks/use-role-guard";
import {
	useAllTeams,
	useCreateTeam,
	useDeleteTeam,
	useLeaveTeam,
	useRemoveTeamMember,
	useTeamMembers,
	useTeams,
	useUpsertTeamMember,
} from "@/hooks/use-teams-api";
import type { Team, TeamMember, TeamRole } from "@/lib/types";

const ROLE_OPTIONS = [
	{ value: "member", label: "Member" },
	{ value: "reviewer", label: "Reviewer" },
	{ value: "owner", label: "Owner" },
];

function slugifyHandle(value: string) {
	return value.toLowerCase().trim().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32);
}

function TeamDetail({ team }: { team: Team }) {
	const { data: members = [], isLoading } = useTeamMembers(team.id);
	const upsert = useUpsertTeamMember(team.id);
	const removeMember = useRemoveTeamMember(team.id);
	const leaveTeam = useLeaveTeam();
	const deleteTeam = useDeleteTeam();
	const [role, setRole] = useState<TeamRole>("member");
	const [searchValue, setSearchValue] = useState("");
	const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
	const isOwner = team.role === "owner";

	function addUser() {
		if (!selectedUserId) return;
		upsert.mutate(
			{ user_id: selectedUserId, role },
			{ onSuccess: () => { setSearchValue(""); setSelectedUserId(null); } },
		);
	}

	return (
		<div className="flex-1 overflow-y-auto">
			<div className="p-6 space-y-6">
				<div className="flex items-start justify-between gap-4">
					<div>
						<h2 className="text-xl font-semibold font-display">{team.name}</h2>
						<p className="text-sm text-muted-foreground font-mono">{team.handle}</p>
						{team.description && <p className="text-sm text-muted-foreground mt-2">{team.description}</p>}
					</div>
					<div className="flex gap-2">
						<Button variant="outline" size="sm" onClick={() => leaveTeam.mutate(team.id)} disabled={leaveTeam.isPending}>
							<LogOut className="h-3.5 w-3.5 mr-1.5" /> Leave
						</Button>
						{isOwner && (
							<Button variant="destructive" size="sm" onClick={() => deleteTeam.mutate(team.id)} disabled={deleteTeam.isPending}>
								<Trash2 className="h-3.5 w-3.5 mr-1.5" /> Delete
							</Button>
						)}
					</div>
				</div>

				{isOwner && (
					<div className="space-y-3">
						<h3 className="text-sm font-semibold">Add member</h3>
						<div className="flex gap-2 items-center">
							<UserSearchInput
								placeholder="Search people"
								value={searchValue}
								onValueChange={(value) => { setSearchValue(value); setSelectedUserId(null); }}
								onSelect={(user) => {
									setSearchValue(user.username ? `@${user.username}` : user.email);
									setSelectedUserId(user.id);
								}}
								className="flex-1"
								disabled={upsert.isPending}
							/>
							<PickerSelect value={role} onValueChange={(v) => setRole(v as TeamRole)} className="w-32" options={ROLE_OPTIONS} />
							<Button size="sm" onClick={addUser} disabled={upsert.isPending || !selectedUserId}>
								{upsert.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
								Add
							</Button>
						</div>
					</div>
				)}

				<div className="space-y-1">
					<h3 className="text-sm font-semibold mb-2">Members</h3>
					{isLoading ? (
						<p className="text-sm text-muted-foreground">Loading...</p>
					) : members.length === 0 ? (
						<p className="text-sm text-muted-foreground">No members yet.</p>
					) : (
						<div className="rounded-md border border-border divide-y divide-border">
							{members.map((m: TeamMember) => (
								<div key={m.id} className="flex items-center justify-between px-4 py-2.5 text-sm">
									<div>
										<span className="font-medium">{m.username ? `@${m.username}` : m.email}</span>
										{m.name && <span className="text-muted-foreground ml-2">{m.name}</span>}
									</div>
									<div className="flex items-center gap-2">
										<span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">{m.role}</span>
										{isOwner && (
											<Button
												variant="ghost"
												size="sm"
												className="h-7 px-2 text-destructive"
												onClick={() => removeMember.mutate(m.id)}
												disabled={removeMember.isPending}
											>
												<Trash2 className="h-3.5 w-3.5" />
											</Button>
										)}
									</div>
								</div>
							))}
						</div>
					)}
				</div>
			</div>
		</div>
	);
}

function CreatePanel({ onCreated }: { onCreated: () => void }) {
	const createTeam = useCreateTeam();
	const [name, setName] = useState("");
	const [handle, setHandle] = useState("");
	const [description, setDescription] = useState("");

	function submit() {
		createTeam.mutate(
			{ name: name.trim(), handle: slugifyHandle(handle || name), description: description.trim() || undefined },
			{
				onSuccess: () => {
					setName("");
					setHandle("");
					setDescription("");
					onCreated();
				},
			},
		);
	}

	return (
		<div className="flex-1 overflow-y-auto">
			<div className="p-6 space-y-6">
				<h2 className="text-xl font-semibold font-display">Create teamspace</h2>
				<div className="grid gap-4 md:grid-cols-2">
					<div className="space-y-2">
						<Label>Name</Label>
						<Input
							value={name}
							onChange={(e) => {
								setName(e.target.value);
								if (!handle) setHandle(slugifyHandle(e.target.value));
							}}
							placeholder="Platform Tools"
						/>
					</div>
					<div className="space-y-2">
						<Label>Handle</Label>
						<Input value={handle} onChange={(e) => setHandle(slugifyHandle(e.target.value))} placeholder="platform-tools" />
						<p className="text-xs text-muted-foreground">
							Used in install commands: <code>observal pull handle/agent-name</code>
						</p>
					</div>
				</div>
				<div className="space-y-2">
					<Label>Description</Label>
					<Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} placeholder="What this team publishes" />
				</div>
				<Button disabled={!name.trim() || createTeam.isPending} onClick={submit}>
					Create teamspace
				</Button>
			</div>
		</div>
	);
}

export default function TeamspacesPage() {
	const { data: teams = [], isLoading } = useTeams();
	const { data: allTeams = [] } = useAllTeams();
	const canCreate = hasMinRole(getUserRole(), "reviewer");
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [showCreate, setShowCreate] = useState(false);

	const selectedTeam = teams.find((t) => t.id === selectedId);
	const browse = teams.length === 0 ? allTeams : teams;

	return (
		<>
			<PageHeader title="Teamspaces" breadcrumbs={[{ label: "Registry", href: "/" }, { label: "Teamspaces" }]} />
			<div className="flex flex-1 overflow-hidden border-t border-border">
				<div className="w-72 border-r border-border flex flex-col overflow-hidden">
					{canCreate && (
						<div className="p-3 border-b border-border">
							<Button
								size="sm"
								variant="outline"
								className="w-full"
								onClick={() => {
									setShowCreate(true);
									setSelectedId(null);
								}}
							>
								<Plus className="h-3.5 w-3.5 mr-1.5" /> New teamspace
							</Button>
						</div>
					)}
					<div className="flex-1 overflow-y-auto">
						{isLoading ? (
							<p className="p-4 text-sm text-muted-foreground">Loading...</p>
						) : browse.length === 0 ? (
							<p className="p-4 text-sm text-muted-foreground">No teamspaces yet.</p>
						) : (
							browse.map((team) => (
								<button
									key={team.id}
									type="button"
									className={`w-full text-left px-4 py-3 border-b border-border transition-colors ${selectedId === team.id ? "bg-accent" : "hover:bg-muted/50"}`}
									onClick={() => {
										setSelectedId(team.id);
										setShowCreate(false);
									}}
								>
									<p className="text-sm font-medium truncate">{team.name}</p>
									<p className="text-xs text-muted-foreground font-mono truncate">{team.handle}</p>
								</button>
							))
						)}
					</div>
				</div>

				<div className="flex-1 flex flex-col overflow-hidden">
					{showCreate ? (
						<CreatePanel onCreated={() => setShowCreate(false)} />
					) : selectedTeam ? (
						<TeamDetail team={selectedTeam} />
					) : (
						<div className="flex-1 flex items-center justify-center">
							<EmptyState icon={Users} title="Select a teamspace" description="Pick a team from the sidebar or create a new one." />
						</div>
					)}
				</div>
			</div>
		</>
	);
}
