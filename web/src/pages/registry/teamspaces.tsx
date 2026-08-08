// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Building2, ChevronRight, Loader2, Lock, Plus, RefreshCw, Search, Users } from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAllTeams, useClaimPersonalTeamspace, useCreateTeam, useTeams } from "@/hooks/use-api";
import { slugifyRegistryText } from "@/lib/registry-name";
import type { Team } from "@/lib/types";

const CONTROL_CLASS_NAME =
	"bg-background/80 border-input/90 placeholder:text-muted-foreground/80 hover:border-primary-accent/50 focus-visible:border-primary-accent focus-visible:ring-primary-accent/30";

function slugifyHandle(value: string) {
	const base = slugifyRegistryText(value, { maxLength: 32 });
	return base && base.length < 3 ? `${base}-team` : base;
}

function TeamspaceCard({ team }: { team: Team }) {
	return (
		<Link
			to="/teamspaces/$handle"
			params={{ handle: team.handle }}
			className="group flex flex-col rounded-lg border border-border/80 bg-card p-4 transition-all duration-200 ease-out hover:-translate-y-0.5 hover:border-primary-accent/40 hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-accent/50"
		>
			<div className="flex items-start gap-3">
				<div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-primary-accent/25 bg-primary-accent/10 text-primary-accent">
					<Building2 className="h-4.5 w-4.5" />
				</div>
				<div className="min-w-0 flex-1">
					<p className="truncate text-sm font-semibold leading-tight">{team.name}</p>
					<p className="mt-0.5 flex items-center gap-1 truncate font-mono text-[11px] text-muted-foreground">
						{team.handle}
						{team.visibility === "private" && (
							<Lock className="h-3 w-3 shrink-0" role="img" aria-label="Private teamspace" />
						)}
					</p>
				</div>
				<ChevronRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5" />
			</div>

			{team.description && (
				<p className="mt-3 line-clamp-2 text-xs leading-5 text-muted-foreground">{team.description}</p>
			)}

			<div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
				<Badge variant="outline" className="px-1.5 py-0 text-[10px] font-medium capitalize">
					{team.role ?? "discoverable"}
				</Badge>
				{team.member_count != null && (
					<span className="inline-flex items-center gap-1">
						<Users className="h-3 w-3" />
						{team.member_count}
					</span>
				)}
			</div>
		</Link>
	);
}

function CreatePanel({
	onCreated,
	onCancel,
	firstTeamspace = false,
}: {
	onCreated: () => void;
	onCancel?: () => void;
	firstTeamspace?: boolean;
}) {
	const createTeam = useCreateTeam();
	const claimPersonal = useClaimPersonalTeamspace();
	const [name, setName] = useState("");
	const [handle, setHandle] = useState("");
	const [handleEdited, setHandleEdited] = useState(false);
	const [description, setDescription] = useState("");
	const [visibility, setVisibility] = useState<"public" | "private">("public");
	const generatedHandle = slugifyHandle(name);
	const submittedHandle = handleEdited ? slugifyHandle(handle) : generatedHandle;
	const previewHandle = submittedHandle || "team";

	function submit() {
		createTeam.mutate(
			{
				name: name.trim(),
				handle: submittedHandle || undefined,
				description: description.trim() || undefined,
				visibility,
			},
			{
				onSuccess: () => {
					setName("");
					setHandle("");
					setHandleEdited(false);
					setDescription("");
					setVisibility("public");
					onCreated();
				},
			},
		);
	}

	return (
		<section className="grid min-h-[620px] w-full overflow-hidden rounded-lg border border-border/80 bg-card 2xl:grid-cols-[minmax(260px,0.82fr)_minmax(0,1.5fr)]">
			<aside className="grid gap-8 border-b border-border/70 bg-primary-accent/[0.04] p-5 sm:p-6 md:grid-cols-[minmax(0,1fr)_minmax(260px,0.9fr)] 2xl:flex 2xl:flex-col 2xl:justify-between 2xl:border-b-0 2xl:border-r">
				<div>
					<div className="flex items-center gap-2 text-xs font-medium text-primary-accent">
						<Building2 className="h-4 w-4" /> Registry identity
					</div>
					<h2 className="mt-6 max-w-xs text-2xl font-semibold tracking-tight">
						{firstTeamspace ? "Give your team a home." : "Define the namespace your team will publish from."}
					</h2>
					<p className="mt-3 max-w-sm text-sm leading-6 text-muted-foreground">
						The name is for people. The handle is the stable slug that travels with every install command.
					</p>
				</div>

				<div className="self-center" aria-live="polite" aria-atomic="true">
					<p className="text-xs font-medium text-muted-foreground">Live install identity</p>
					<div className="mt-3 min-h-16 border-b border-primary-accent/20 pb-4 font-mono text-xl tracking-tight 2xl:text-2xl">
						<span className="text-primary-accent/70">observal pull </span>
						<span
							key={previewHandle}
							className="inline-block text-foreground motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-200 motion-reduce:animate-none"
						>
							{previewHandle}
						</span>
						<span className="text-muted-foreground">/agent-name</span>
					</div>
					<p className="mt-3 text-xs leading-5 text-muted-foreground">
						This preview updates as you type and uses the same slug rules as the teamspace handle.
					</p>
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
						<h3 className="mt-2 text-2xl font-semibold tracking-tight">
							{firstTeamspace ? "Create your first teamspace" : "Create a teamspace"}
						</h3>
						<p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
							Create a shared namespace for publishing agents and components with your team.
						</p>
					</div>
					{onCancel && (
						<Button type="button" variant="ghost" size="sm" onClick={onCancel}>
							Cancel
						</Button>
					)}
				</header>

				<form
					className="flex min-h-0 flex-1 flex-col"
					onSubmit={(event) => {
						event.preventDefault();
						submit();
					}}
				>
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
									<button
										type="button"
										className="inline-flex items-center gap-1 text-xs text-primary-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-accent/50"
										onClick={() => {
											setHandle("");
											setHandleEdited(false);
										}}
									>
										<RefreshCw className="h-3 w-3" /> Use generated
									</button>
								)}
							</div>
							<Input
								id="team-handle"
								value={handleEdited ? handle : generatedHandle}
								onChange={(event) => {
									setHandle(slugifyRegistryText(event.target.value, { maxLength: 32, preserveTrailingSeparator: true }));
									setHandleEdited(true);
								}}
								placeholder="platform-tools"
								aria-describedby="team-handle-help"
								className={`${CONTROL_CLASS_NAME} h-11 font-mono text-base`}
							/>
							<p id="team-handle-help" className="text-xs leading-5 text-muted-foreground">
								Generated live from the name. Short names use a readable `-team` suffix to meet namespace rules.
							</p>
						</div>
						<div className="space-y-2 md:col-span-2">
							<Label id="team-visibility-label">Visibility</Label>
							<div
								role="radiogroup"
								aria-labelledby="team-visibility-label"
								className="grid gap-2 sm:grid-cols-2"
							>
								{(
									[
										{
											value: "public" as const,
											title: "Public",
											blurb: "Discoverable by every signed-in user; anyone can request to join.",
										},
										{
											value: "private" as const,
											title: "Private",
											blurb: "Hidden from non-members. Admins and global reviewers still see it.",
										},
									]
								).map((option) => (
									<button
										key={option.value}
										type="button"
										role="radio"
										aria-checked={visibility === option.value}
										onClick={() => setVisibility(option.value)}
										className={`rounded-md border p-3 text-left transition-colors ${
											visibility === option.value
												? "border-primary-accent bg-primary-accent/5"
												: "border-border/80 hover:border-foreground/20"
										}`}
									>
										<p className="text-sm font-medium">{option.title}</p>
										<p className="mt-1 text-xs leading-5 text-muted-foreground">{option.blurb}</p>
									</button>
								))}
							</div>
						</div>
						<div className="space-y-2 md:col-span-2">
							<Label htmlFor="team-description">
								Description <span className="font-normal text-muted-foreground">(optional)</span>
							</Label>
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
						<div className="flex flex-col gap-2 sm:flex-row sm:items-center">
							{/* Claiming is idempotent, so the button is safe to show whenever
							    the panel is open, not only on the first-run empty state. */}
							<Button
								type="button"
								variant="outline"
								disabled={claimPersonal.isPending}
								onClick={() => claimPersonal.mutate(undefined, { onSuccess: () => onCreated() })}
								title="One click creates a private teamspace of your own, named after you and hidden from other users"
							>
								{claimPersonal.isPending ? (
									<Loader2 className="h-4 w-4 animate-spin" />
								) : (
									<Lock className="h-4 w-4" />
								)}
								Claim your private teamspace
							</Button>
							<Button
								type="submit"
								className="bg-primary-accent px-5 text-primary-foreground hover:bg-primary-accent/90"
								disabled={!name.trim() || createTeam.isPending}
							>
								{createTeam.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
								Create teamspace
							</Button>
						</div>
					</footer>
				</form>
			</div>
		</section>
	);
}

export default function TeamspacesPage() {
	const { data: teams = [], isLoading: isTeamsLoading } = useTeams();
	const { data: allTeams = [], isLoading: isAllTeamsLoading } = useAllTeams();
	const [showCreate, setShowCreate] = useState(false);
	const [teamQuery, setTeamQuery] = useState("");

	const browse = teams.length === 0 ? allTeams : teams;
	const isLoading = isTeamsLoading || (teams.length === 0 && isAllTeamsLoading);
	const query = teamQuery.trim().toLowerCase();
	const filteredTeams = browse.filter(
		(team) => !query || team.name.toLowerCase().includes(query) || team.handle.toLowerCase().includes(query),
	);
	// Any signed-in user can create a teamspace, so the first-run panel needs
	// no role gate.
	const firstTeamspace = !isLoading && browse.length === 0;
	const listTitle = teams.length > 0 ? "Your teamspaces" : "Discover teamspaces";

	return (
		<>
			<PageHeader title="Teamspaces" breadcrumbs={[{ label: "Registry", href: "/" }, { label: "Teamspaces" }]} />
			<main className="min-h-0 flex-1 overflow-y-auto bg-surface-sunken/30">
				<div className="mx-auto w-full max-w-6xl p-4 sm:p-6 lg:p-8">
					{showCreate || firstTeamspace ? (
						<CreatePanel
							firstTeamspace={firstTeamspace}
							onCreated={() => setShowCreate(false)}
							onCancel={firstTeamspace ? undefined : () => setShowCreate(false)}
						/>
					) : (
						<>
							<header className="flex flex-col gap-4 border-b border-border/80 pb-5 sm:flex-row sm:items-end sm:justify-between">
								<div>
									<h2 className="text-xl font-semibold tracking-tight">{listTitle}</h2>
									<p className="mt-1 text-sm text-muted-foreground">
										Shared publishing namespaces. Open one to browse its agents and components, manage members, and
										clear its review queue.
									</p>
								</div>
								<div className="flex items-center gap-2">
									{browse.length > 0 && (
										<div className="relative">
											<Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
											<Input
												value={teamQuery}
												onChange={(event) => setTeamQuery(event.target.value)}
												placeholder="Search teamspaces"
												aria-label="Search teamspaces"
												className={`${CONTROL_CLASS_NAME} h-9 w-full pl-8 text-xs sm:w-56`}
											/>
										</div>
									)}
									<Button
										type="button"
										variant="outline"
										size="sm"
										className="h-9 shrink-0 border-primary-accent/30 hover:border-primary-accent/60 hover:bg-primary-accent/10"
										onClick={() => setShowCreate(true)}
									>
										<Plus className="mr-1.5 h-3.5 w-3.5 text-primary-accent" /> New teamspace
									</Button>
								</div>
							</header>

							<div className="mt-6">
								{isLoading ? (
									<div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-label="Loading teamspaces">
										<div className="h-32 animate-pulse rounded-lg bg-muted/60" />
										<div className="h-32 animate-pulse rounded-lg bg-muted/60" />
										<div className="h-32 animate-pulse rounded-lg bg-muted/60" />
									</div>
								) : browse.length === 0 ? (
									<EmptyState
										icon={Users}
										title="No teamspaces to browse"
										description="Create the first teamspace to give your team a shared publishing namespace."
									/>
								) : filteredTeams.length === 0 ? (
									<EmptyState
										icon={Search}
										title="No matching teamspaces"
										description={`Nothing matches "${teamQuery.trim()}". Clear the search to see all ${browse.length}.`}
									/>
								) : (
									<div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
										{filteredTeams.map((team) => (
											<TeamspaceCard key={team.id} team={team} />
										))}
									</div>
								)}
							</div>
						</>
					)}
				</div>
			</main>
		</>
	);
}
