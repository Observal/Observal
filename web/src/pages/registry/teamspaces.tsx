// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import { Building2, Loader2, LogOut, Plus, RefreshCw, Search, ShieldCheck, Terminal, Trash2, UserPlus, Users } from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { UserSearchInput } from "@/components/shared/user-search-input";
import {
	AlertDialog,
	AlertDialogAction,
	AlertDialogCancel,
	AlertDialogContent,
	AlertDialogDescription,
	AlertDialogFooter,
	AlertDialogHeader,
	AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PickerSelect } from "@/components/ui/picker-select";
import { Textarea } from "@/components/ui/textarea";
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
import { getUserRole } from "@/lib/api";
import type { Team, TeamMember, TeamRole } from "@/lib/types";

const ROLE_OPTIONS = [
	{ value: "member", label: "Member" },
	{ value: "reviewer", label: "Reviewer" },
	{ value: "owner", label: "Owner" },
];

const CONTROL_CLASS_NAME =
	"bg-background/80 border-input/90 placeholder:text-muted-foreground/80 hover:border-primary-accent/50 focus-visible:border-primary-accent focus-visible:ring-primary-accent/30";

function slugifyHandle(value: string) {
	const base = value.toLowerCase().trim().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32);
	return base && base.length < 3 ? `${base}-team` : base;
}

function TeamDetail({ team }: { team: Team }) {
	const isOwner = team.role === "owner";
	const isMember = Boolean(team.role);
	const canManageMembers = isOwner || hasMinRole(getUserRole(), "admin");
	const canViewMembers = isMember || hasMinRole(getUserRole(), "admin");
	const { data: members = [], isLoading, isError } = useTeamMembers(team.id, canViewMembers);
	const upsert = useUpsertTeamMember(team.id);
	const removeMember = useRemoveTeamMember(team.id);
	const leaveTeam = useLeaveTeam();
	const deleteTeam = useDeleteTeam();
	const [role, setRole] = useState<TeamRole>("member");
	const [searchValue, setSearchValue] = useState("");
	const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
	const [deleteOpen, setDeleteOpen] = useState(false);

	function addUser() {
		if (!selectedUserId) return;
		upsert.mutate(
			{ user_id: selectedUserId, role },
			{ onSuccess: () => { setSearchValue(""); setSelectedUserId(null); } },
		);
	}

	return (
		<main className="min-h-0 flex-1 overflow-y-auto bg-surface-sunken/30">
			<div className="mx-auto w-full max-w-6xl p-4 sm:p-6 lg:p-8">
				<header className="flex flex-col gap-5 border-b border-border/80 pb-6 sm:flex-row sm:items-start sm:justify-between">
					<div className="flex min-w-0 items-start gap-3">
						<div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-primary-accent/25 bg-primary-accent/10 text-primary-accent">
							<Building2 className="h-5 w-5" />
						</div>
						<div className="min-w-0">
							<h2 className="truncate text-xl font-semibold tracking-tight">{team.name}</h2>
							<div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
								<span className="font-mono">{team.handle}</span>
								<span aria-hidden="true">·</span>
								<Badge variant="outline" className="capitalize px-1.5 py-0 text-[11px] font-medium">
									{team.role ?? "discoverable"}
								</Badge>
								{team.member_count != null && <span>{team.member_count} members</span>}
							</div>
							{team.description && <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">{team.description}</p>}
						</div>
					</div>
					<div className="flex shrink-0 flex-wrap gap-2 sm:justify-end">
						{isMember && (
							<Button variant="outline" size="sm" onClick={() => leaveTeam.mutate(team.id)} disabled={leaveTeam.isPending}>
								<LogOut className="mr-1.5 h-3.5 w-3.5" /> Leave
							</Button>
						)}
						{isOwner && (
							<Button variant="destructive" size="sm" onClick={() => setDeleteOpen(true)} disabled={deleteTeam.isPending}>
								<Trash2 className="mr-1.5 h-3.5 w-3.5" /> Delete
							</Button>
						)}
					</div>
				</header>

				<section className="mt-6 flex min-h-[calc(100dvh-11rem)] flex-col overflow-hidden rounded-xl border border-border/80 bg-card/70">
					<div className="flex flex-col gap-1 border-b border-border/70 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
						<div>
							<h3 className="text-sm font-semibold">Members</h3>
							<p className="mt-1 text-xs text-muted-foreground">
								{canViewMembers ? "People who can publish and manage this teamspace." : "Join the teamspace to view its members."}
							</p>
						</div>
						{team.member_count != null && <span className="text-xs text-muted-foreground">{team.member_count} total</span>}
					</div>

					{canManageMembers && (
						<div className="border-b border-border/70 bg-background/30 px-5 py-4">
							<div className="mb-3 flex items-center gap-2">
								<UserPlus className="h-4 w-4 text-primary-accent" />
								<div>
									<h4 className="text-sm font-medium">Add a member</h4>
									<p className="text-xs text-muted-foreground">Search for a person, then choose their role.</p>
								</div>
							</div>
							<div className="flex flex-col gap-2 lg:flex-row lg:items-center">
								<UserSearchInput
									placeholder="Search people"
									value={searchValue}
									onValueChange={(value) => { setSearchValue(value); setSelectedUserId(null); }}
									onSelect={(user) => {
										setSearchValue(user.username ? `@${user.username}` : user.email);
										setSelectedUserId(user.id);
									}}
									className="min-w-0 flex-1"
									disabled={upsert.isPending}
								/>
								<PickerSelect value={role} onValueChange={(value) => setRole(value as TeamRole)} className="w-full lg:w-32" options={ROLE_OPTIONS} />
								<Button className="bg-primary-accent text-primary-foreground hover:bg-primary-accent/90" onClick={addUser} disabled={upsert.isPending || !selectedUserId}>
									{upsert.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
									Add member
								</Button>
							</div>
						</div>
					)}

					<div className="flex-1 p-5">
						{!canViewMembers ? (
							<div className="rounded-lg border border-dashed border-border/80 px-5 py-8 text-center">
								<ShieldCheck className="mx-auto h-6 w-6 text-muted-foreground/70" />
								<p className="mt-3 text-sm font-medium">Membership required</p>
								<p className="mx-auto mt-1 max-w-sm text-xs leading-5 text-muted-foreground">This teamspace is discoverable, but its member roster is only visible to members and administrators.</p>
							</div>
						) : isLoading ? (
							<div className="space-y-2" aria-label="Loading members">
								<div className="h-12 animate-pulse rounded-md bg-muted/60" />
								<div className="h-12 animate-pulse rounded-md bg-muted/60" />
							</div>
						) : isError ? (
							<div className="rounded-lg border border-dashed border-border/80 px-5 py-8 text-center">
								<p className="text-sm font-medium">Members could not be loaded</p>
								<p className="mt-1 text-xs text-muted-foreground">Try refreshing this teamspace.</p>
							</div>
						) : members.length === 0 ? (
							<div className="rounded-lg border border-dashed border-border/80 px-5 py-8 text-center">
								<Users className="mx-auto h-6 w-6 text-muted-foreground/70" />
								<p className="mt-3 text-sm font-medium">No members yet</p>
								<p className="mt-1 text-xs text-muted-foreground">Add someone above to start publishing together.</p>
							</div>
						) : (
							<div className="divide-y divide-border/70 rounded-lg border border-border/80">
								{members.map((member: TeamMember) => (
									<div key={member.id} className="flex items-center justify-between gap-4 px-4 py-3">
										<div className="min-w-0">
											<p className="truncate text-sm font-medium">{member.username ? `@${member.username}` : member.email}</p>
											{member.name && <p className="truncate text-xs text-muted-foreground">{member.name}</p>}
										</div>
										<div className="flex shrink-0 items-center gap-2">
											{canManageMembers ? (
												<PickerSelect
													value={member.role}
													onValueChange={(value) => {
														const nextRole = value as TeamRole;
														if (nextRole !== member.role) upsert.mutate({ user_id: member.id, role: nextRole });
													}}
													options={ROLE_OPTIONS}
													ariaLabel={`Change role for ${member.username ? `@${member.username}` : member.email}`}
													className="w-28"
													inputClassName="h-8 bg-background/80 px-2 text-xs"
													disabled={upsert.isPending}
												/>
											) : (
												<Badge variant="outline" className="capitalize px-2 py-0.5 text-[11px]">{member.role}</Badge>
											)}
											{canManageMembers && (
												<Button
													variant="ghost"
													size="icon"
													className="h-7 w-7 text-muted-foreground hover:text-destructive"
													onClick={() => removeMember.mutate(member.id)}
													disabled={removeMember.isPending}
													aria-label={`Remove ${member.username ? `@${member.username}` : member.email}`}
													title="Remove member"
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

					<footer className="flex flex-col gap-3 border-t border-border/70 bg-background/20 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
						<div className="flex items-start gap-2.5">
							<Terminal className="mt-0.5 h-4 w-4 shrink-0 text-primary-accent" />
							<div>
								<p className="text-xs font-medium text-foreground">Publishing namespace</p>
								<p className="mt-1 text-xs text-muted-foreground">Use this identity when installing an agent or component from the team.</p>
							</div>
						</div>
						<code className="rounded-md border border-border/80 bg-background px-3 py-2 font-mono text-xs text-foreground">observal pull {team.handle}/agent-name</code>
					</footer>
				</section>
			</div>

			<AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
				<AlertDialogContent>
					<AlertDialogHeader>
						<AlertDialogTitle>Delete {team.name}?</AlertDialogTitle>
						<AlertDialogDescription>This permanently removes the teamspace and its membership records. Published items are not deleted.</AlertDialogDescription>
					</AlertDialogHeader>
					<AlertDialogFooter>
						<AlertDialogCancel>Cancel</AlertDialogCancel>
						<AlertDialogAction
							className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
							onClick={() => deleteTeam.mutate(team.id)}
						>
							Delete teamspace
						</AlertDialogAction>
					</AlertDialogFooter>
				</AlertDialogContent>
			</AlertDialog>
		</main>
	);
}

function CreatePanel({ onCreated, onCancel, firstTeamspace = false }: { onCreated: () => void; onCancel?: () => void; firstTeamspace?: boolean }) {
	const createTeam = useCreateTeam();
	const [name, setName] = useState("");
	const [handle, setHandle] = useState("");
	const [handleEdited, setHandleEdited] = useState(false);
	const [description, setDescription] = useState("");
	const generatedHandle = slugifyHandle(name);
	const effectiveHandle = handleEdited ? handle : generatedHandle;
	const previewHandle = effectiveHandle || "team";

	function submit() {
		createTeam.mutate(
			{ name: name.trim(), handle: effectiveHandle || undefined, description: description.trim() || undefined },
			{
				onSuccess: () => {
					setName("");
					setHandle("");
					setHandleEdited(false);
					setDescription("");
					onCreated();
				},
			},
		);
	}

	return (
		<main className="min-h-0 flex-1 overflow-y-auto bg-surface-sunken/30">
			<div className="mx-auto flex min-h-full w-full max-w-6xl items-start p-4 sm:p-6 lg:p-8 xl:p-10">
				<section className="grid min-h-[620px] w-full overflow-hidden rounded-lg border border-border/80 bg-card 2xl:grid-cols-[minmax(260px,0.82fr)_minmax(0,1.5fr)]">
					<aside className="grid gap-8 border-b border-border/70 bg-primary-accent/[0.04] p-5 sm:p-6 md:grid-cols-[minmax(0,1fr)_minmax(260px,0.9fr)] 2xl:flex 2xl:flex-col 2xl:justify-between 2xl:border-b-0 2xl:border-r">
						<div>
							<div className="flex items-center gap-2 text-xs font-medium text-primary-accent">
								<Building2 className="h-4 w-4" /> Registry identity
							</div>
							<h2 className="mt-6 max-w-xs text-2xl font-semibold tracking-tight">{firstTeamspace ? "Give your team a home." : "Define the namespace your team will publish from."}</h2>
							<p className="mt-3 max-w-sm text-sm leading-6 text-muted-foreground">The name is for people. The handle is the stable slug that travels with every install command.</p>
						</div>

						<div className="self-center" aria-live="polite" aria-atomic="true">
							<p className="text-xs font-medium text-muted-foreground">Live install identity</p>
							<div className="mt-3 min-h-16 border-b border-primary-accent/20 pb-4 font-mono text-xl tracking-tight 2xl:text-2xl">
								<span className="text-primary-accent/70">observal pull </span>
								<span key={previewHandle} className="inline-block text-foreground motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-200 motion-reduce:animate-none">{previewHandle}</span>
								<span className="text-muted-foreground">/agent-name</span>
							</div>
							<p className="mt-3 text-xs leading-5 text-muted-foreground">This preview updates as you type and uses the same slug rules as the teamspace handle.</p>
						</div>

						<div className="hidden border-t border-border/70 pt-4 text-xs leading-5 text-muted-foreground 2xl:block">
							<p className="font-medium text-foreground">After creation</p>
							<p className="mt-1">Invite members, assign roles, and publish agents or components under this namespace.</p>
						</div>
					</aside>

					<div className="flex min-w-0 flex-col">
						<header className="flex items-start justify-between gap-4 border-b border-border/70 px-6 py-6 sm:px-8 sm:py-8">
							<div>
								<p className="text-sm font-medium text-primary-accent">New teamspace</p>
								<h3 className="mt-2 text-2xl font-semibold tracking-tight">{firstTeamspace ? "Create your first teamspace" : "Create a teamspace"}</h3>
								<p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">Create a shared namespace for publishing agents and components with your team.</p>
							</div>
							{onCancel && <Button type="button" variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>}
						</header>

						<form className="flex min-h-0 flex-1 flex-col" onSubmit={(event) => { event.preventDefault(); submit(); }}>
							<div className="grid flex-1 content-start gap-6 p-6 sm:p-8 md:grid-cols-2">
								<div className="space-y-2">
									<Label htmlFor="team-name">Name</Label>
									<Input
										id="team-name"
										autoFocus={firstTeamspace}
										required
										value={name}
										onChange={(event) => setName(event.target.value)}
										placeholder="Platform Tools"
										className={`${CONTROL_CLASS_NAME} h-11 text-base`}
									/>
								</div>
								<div className="space-y-2">
									<div className="flex items-center justify-between gap-3">
										<Label htmlFor="team-handle">Handle</Label>
										{handleEdited && (
											<button type="button" className="inline-flex items-center gap-1 text-xs text-primary-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-accent/50" onClick={() => { setHandle(""); setHandleEdited(false); }}>
												<RefreshCw className="h-3 w-3" /> Use generated
											</button>
										)}
									</div>
									<Input
										id="team-handle"
										value={handleEdited ? handle : generatedHandle}
										onChange={(event) => { setHandle(slugifyHandle(event.target.value)); setHandleEdited(true); }}
										placeholder="platform-tools"
										aria-describedby="team-handle-help"
										className={`${CONTROL_CLASS_NAME} h-11 font-mono text-base`}
									/>
									<p id="team-handle-help" className="text-xs leading-5 text-muted-foreground">Generated live from the name. Short names use a readable `-team` suffix to meet namespace rules.</p>
								</div>
								<div className="space-y-2 md:col-span-2">
									<Label htmlFor="team-description">Description <span className="font-normal text-muted-foreground">(optional)</span></Label>
									<Textarea
										id="team-description"
										value={description}
										onChange={(event) => setDescription(event.target.value)}
										rows={5}
										placeholder="What this team publishes, who it serves, and what belongs in this namespace"
										className={`${CONTROL_CLASS_NAME} min-h-28 resize-y text-base leading-6`}
									/>
								</div>
							</div>
							<footer className="flex flex-col gap-3 border-t border-border/70 px-6 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-8">
								<p className="text-xs leading-5 text-muted-foreground">You can manage members and roles after creation.</p>
								<Button type="submit" className="bg-primary-accent px-5 text-primary-foreground hover:bg-primary-accent/90" disabled={!name.trim() || createTeam.isPending}>
									{createTeam.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
									Create teamspace
								</Button>
							</footer>
						</form>
					</div>
				</section>
			</div>
		</main>
	);
}

export default function TeamspacesPage() {
	const { data: teams = [], isLoading: isTeamsLoading } = useTeams();
	const { data: allTeams = [], isLoading: isAllTeamsLoading } = useAllTeams();
	const canCreate = hasMinRole(getUserRole(), "reviewer");
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [showCreate, setShowCreate] = useState(false);
	const [teamQuery, setTeamQuery] = useState("");

	const browse = teams.length === 0 ? allTeams : teams;
	const isLoading = isTeamsLoading || (teams.length === 0 && isAllTeamsLoading);
	const filteredTeams = browse.filter((team) => {
		const query = teamQuery.trim().toLowerCase();
		return !query || team.name.toLowerCase().includes(query) || team.handle.toLowerCase().includes(query);
	});
	const selectedTeam = browse.find((team) => team.id === selectedId);
	const firstTeamspace = !isLoading && browse.length === 0 && canCreate;
	const listTitle = teams.length > 0 ? "Your teamspaces" : "Discover teamspaces";

	return (
		<>
			<PageHeader title="Teamspaces" breadcrumbs={[{ label: "Registry", href: "/" }, { label: "Teamspaces" }]} />
			<div className="flex min-h-0 flex-1 flex-col overflow-hidden border-t border-border md:flex-row">
				<aside className="flex w-full shrink-0 flex-col border-b border-border bg-sidebar-background md:w-72 md:border-b-0 md:border-r">
					<div className="space-y-4 p-4">
						<div className="flex items-start justify-between gap-3">
							<div>
								<h2 className="text-sm font-semibold">Teamspaces</h2>
								<p className="mt-1 text-xs text-muted-foreground">Shared publishing namespaces</p>
							</div>
							<span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{browse.length}</span>
						</div>
						{canCreate && (
							<Button
								type="button"
								variant="outline"
								size="sm"
								className="w-full justify-start border-primary-accent/30 hover:border-primary-accent/60 hover:bg-primary-accent/10"
								onClick={() => { setShowCreate(true); setSelectedId(null); }}
							>
								<Plus className="mr-1.5 h-3.5 w-3.5 text-primary-accent" /> New teamspace
							</Button>
						)}
						{browse.length > 0 && (
							<div className="relative">
								<Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
								<Input
									value={teamQuery}
									onChange={(event) => setTeamQuery(event.target.value)}
									placeholder="Search teamspaces"
									aria-label="Search teamspaces"
									className={`${CONTROL_CLASS_NAME} h-8 pl-8 text-xs`}
								/>
							</div>
						)}
					</div>

					<div className="min-h-0 max-h-64 flex-1 overflow-y-auto px-3 pb-3 md:max-h-none">
						{browse.length === 0 ? (
							<div className="rounded-lg border border-dashed border-sidebar-border px-4 py-8 text-center">
								<Users className="mx-auto h-6 w-6 text-muted-foreground/70" />
								<p className="mt-3 text-sm font-medium">No teamspaces yet</p>
								<p className="mt-1 text-xs leading-5 text-muted-foreground">{canCreate ? "Create your first one in the main pane." : "There are no discoverable teamspaces yet."}</p>
							</div>
						) : filteredTeams.length === 0 ? (
							<div className="px-3 py-8 text-center text-xs text-muted-foreground">No matching teamspaces.</div>
						) : (
							<>
								<p className="px-2 pb-2 pt-1 text-xs font-medium text-muted-foreground">{listTitle}</p>
								<div className="space-y-1">
									{filteredTeams.map((team) => (
										<button
											key={team.id}
											type="button"
											className={`group w-full rounded-md border px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-accent/50 ${selectedId === team.id ? "border-primary-accent/35 bg-primary-accent/10" : "border-transparent hover:border-sidebar-border hover:bg-sidebar-accent/60"}`}
											onClick={() => { setSelectedId(team.id); setShowCreate(false); }}
										>
											<div className="flex items-center justify-between gap-2">
												<p className="truncate text-sm font-medium">{team.name}</p>
												{team.role && <span className="shrink-0 text-[10px] capitalize text-muted-foreground">{team.role}</span>}
											</div>
											<p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{team.handle}</p>
										</button>
									))}
								</div>
							</>
						)}
					</div>
				</aside>

				<div className="flex min-h-0 flex-1 flex-col">
					{showCreate || firstTeamspace ? (
						<CreatePanel
							firstTeamspace={firstTeamspace}
							onCreated={() => { setShowCreate(false); setSelectedId(null); }}
							onCancel={firstTeamspace ? undefined : () => setShowCreate(false)}
						/>
					) : selectedTeam ? (
						<TeamDetail team={selectedTeam} />
					) : (
						<div className="flex min-h-0 flex-1 items-center justify-center bg-surface-sunken/30 p-6">
							<EmptyState
								icon={browse.length > 0 ? Building2 : Users}
								title={browse.length > 0 ? "Select a teamspace" : "No teamspaces to browse"}
								description={browse.length > 0 ? "Choose a teamspace from the rail to view its members and publishing context." : "When a teamspace is available, it will appear here for browsing."}
							/>
						</div>
					)}
				</div>
			</div>
		</>
	);
}
