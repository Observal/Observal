// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useState, useCallback, useMemo } from "react";
import { Link } from "@tanstack/react-router";
import {
	CheckCircle2,
	X,
	ExternalLink,
	GitBranch,
	AlertCircle,
} from "lucide-react";
import {
	Sheet,
	SheetContent,
	SheetHeader,
	SheetTitle,
	SheetDescription,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import {
	ValidationBadge,
	ValidationDetails,
	ComponentReadinessBadge,
} from "./validation-badges";
import {
	useReviewDetail,
	useRelatedSkills,
	useApproveWithSkills,
} from "@/hooks/use-api";
import yaml from "js-yaml";
import type { ReviewItem } from "@/lib/types";

function toYaml(value: unknown): string {
	try {
		return yaml.dump(value, { lineWidth: 120, indent: 2, noRefs: true }).trimEnd();
	} catch {
		return JSON.stringify(value, null, 2);
	}
}

function reviewItemHref(item: ReviewItem): string {
	if (item.type === "agent") return `/agents/${item.id}`;
	const plural = item.type ? `${item.type}s` : "mcps";
	return `/components/${item.id}?type=${plural}`;
}

function DetailField({ label, value }: { label: string; value: unknown }) {
	if (value === null || value === undefined || value === "") return null;

	return (
		<div>
			<dt className="text-xs font-medium text-muted-foreground">{label}</dt>
			<dd className="text-sm mt-0.5">
				{typeof value === "object" ? (
					<pre className="max-h-40 overflow-auto rounded bg-muted p-2 text-xs whitespace-pre-wrap">
						{toYaml(value)}
					</pre>
				) : typeof value === "boolean" ? (
					value ? (
						"Yes"
					) : (
						"No"
					)
				) : (
					String(value)
				)}
			</dd>
		</div>
	);
}

function McpConfigSection({ detail }: { detail: ReviewItem }) {
	return (
		<dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
			<DetailField label="Transport" value={detail.transport} />
			<DetailField label="Framework" value={detail.framework} />
			<DetailField label="Docker Image" value={detail.docker_image} />
			<DetailField label="Command" value={detail.command} />
			<DetailField label="Args" value={detail.args} />
			<DetailField label="URL" value={detail.url} />
			<DetailField label="Auto Approve" value={detail.auto_approve} />
			<DetailField
				label="Setup Instructions"
				value={detail.setup_instructions}
			/>
			<DetailField label="Changelog" value={detail.changelog} />
			<DetailField
				label="Environment Variables"
				value={detail.environment_variables}
			/>
			<DetailField label="Headers" value={detail.headers} />
			<DetailField label="Tools Schema" value={detail.tools_schema} />
		</dl>
	);
}

function SkillConfigSection({ detail }: { detail: ReviewItem }) {
	return (
		<dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
			<DetailField label="Task Type" value={detail.task_type} />
			<DetailField label="Slash Command" value={detail.slash_command} />
			<DetailField label="Skill Path" value={detail.skill_path} />
			<DetailField label="Git URL" value={detail.git_url} />
			<DetailField label="Git Ref" value={detail.git_ref} />
			<DetailField label="Validated" value={detail.validated} />
			<DetailField label="Target Agents" value={detail.target_agents} />
		</dl>
	);
}

function HookConfigSection({ detail }: { detail: ReviewItem }) {
	return (
		<dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
			<DetailField label="Event" value={detail.event} />
			<DetailField label="Execution Mode" value={detail.execution_mode} />
			<DetailField label="Priority" value={detail.priority} />
			<DetailField label="Handler Type" value={detail.handler_type} />
			<DetailField label="Scope" value={detail.scope} />
			<DetailField label="Tool Filter" value={detail.tool_filter} />
			<DetailField label="Handler Config" value={detail.handler_config} />
			{detail.script_filename && <DetailField label="Script" value={detail.script_filename} />}
			{detail.source_url && <DetailField label="Source" value={`${detail.source_url}@${detail.source_ref || 'main'}`} />}
			{detail.requirements && detail.requirements.length > 0 && <DetailField label="Requirements" value={detail.requirements.join(', ')} />}
		</dl>
	);
}

function PromptConfigSection({ detail }: { detail: ReviewItem }) {
	return (
		<dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
			<DetailField label="Category" value={detail.category} />
			<DetailField label="Tags" value={detail.tags} />
			<DetailField label="Variables" value={detail.variables} />
			<DetailField label="Model Hints" value={detail.model_hints} />
			{detail.template && (
				<div className="col-span-full">
					<dt className="text-xs font-medium text-muted-foreground">
						Template
					</dt>
					<dd className="mt-0.5">
						<pre className="max-h-60 overflow-auto rounded bg-muted p-2 text-[11px] font-mono leading-relaxed break-words">
							{detail.template}
						</pre>
					</dd>
				</div>
			)}
		</dl>
	);
}

function SandboxConfigSection({ detail }: { detail: ReviewItem }) {
	return (
		<dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
			<DetailField label="Runtime Type" value={detail.runtime_type} />
			<DetailField label="Image" value={detail.image} />
			<DetailField label="Network Policy" value={detail.network_policy} />
			<DetailField label="Entrypoint" value={detail.entrypoint} />
			<DetailField label="Resource Limits" value={detail.resource_limits} />
			{detail.sandbox_path && <DetailField label="Sandbox Path" value={detail.sandbox_path} />}
			{detail.source_url && <DetailField label="Source" value={detail.source_url} />}
		</dl>
	);
}

function AgentConfigSection({ detail }: { detail: ReviewItem }) {
	return (
		<dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
			<DetailField label="Model" value={detail.model_name} />
			<DetailField label="External MCPs" value={detail.external_mcps} />
			<DetailField
				label="Required IDE Features"
				value={detail.required_ide_features}
			/>
			<DetailField label="Model Config" value={detail.model_config_json} />
			{detail.components && detail.components.length > 0 && (
				<div className="col-span-full">
					<dt className="text-xs font-medium text-muted-foreground mb-1">
						Components ({detail.components.length})
					</dt>
					<dd className="space-y-2">
						{detail.components.map((c, i) => {
							const comp = c as Record<string, unknown>;
							const name = (comp.name as string) || `${c.component_type} component`;
							const description = comp.description as string | undefined;
							const CONTENT_KEYS = ["template", "skill_md_content", "handler_config", "input_schema", "output_schema", "source_url", "git_url", "config_json"];
							const contentEntries = Object.entries(comp).filter(([k]) => CONTENT_KEYS.includes(k) && comp[k]);
							return (
								<div key={i} className="rounded border border-border overflow-hidden">
									<div className="flex items-center gap-2 px-3 py-2 bg-muted/50">
										<Badge variant="outline" className="text-[10px] shrink-0">
											{c.component_type as string}
										</Badge>
										<span className="text-xs font-medium">{name}</span>
									</div>
									{description && (
										<p className="px-3 py-1.5 text-[11px] text-muted-foreground border-b border-border/50">{description}</p>
									)}
									{contentEntries.length > 0 && (
										<details open className="group">
											<summary className="cursor-pointer select-none px-3 py-1.5 text-[10px] font-medium text-muted-foreground hover:text-foreground list-none flex items-center gap-1">
												<span className="group-open:rotate-90 transition-transform inline-block">▶</span>
												Content
											</summary>
											<pre className="px-3 py-2 text-[11px] font-mono leading-relaxed overflow-auto max-h-80 bg-background border-t border-border/50 break-words">
												{toYaml(Object.fromEntries(contentEntries))}
											</pre>
										</details>
									)}
								</div>
							);
						})}
					</dd>
				</div>
			)}
			{detail.prompt && (
				<div className="col-span-full">
					<dt className="text-xs font-medium text-muted-foreground">Prompt</dt>
					<dd className="mt-0.5">
						<pre className="max-h-60 overflow-auto rounded bg-muted p-2 text-[11px] font-mono leading-relaxed break-words">
							{detail.prompt}
						</pre>
					</dd>
				</div>
			)}
		</dl>
	);
}

function ConfigSection({ detail }: { detail: ReviewItem }) {
	switch (detail.type) {
		case "mcp":
			return <McpConfigSection detail={detail} />;
		case "skill":
			return <SkillConfigSection detail={detail} />;
		case "hook":
			return <HookConfigSection detail={detail} />;
		case "prompt":
			return <PromptConfigSection detail={detail} />;
		case "sandbox":
			return <SandboxConfigSection detail={detail} />;
		case "agent":
			return <AgentConfigSection detail={detail} />;
		default:
			return null;
	}
}

function RelatedSkillsSection({
	mcpId,
	onApproveWithSkills,
}: {
	mcpId: string;
	onApproveWithSkills: (mcpId: string, skillIds: string[]) => void;
}) {
	const { data: skills, isLoading } = useRelatedSkills(mcpId);
	const approveWithSkills = useApproveWithSkills();
	const [deselected, setDeselected] = useState<Set<string>>(new Set());

	const allIds = useMemo(
		() => new Set(skills?.map((s) => s.id) ?? []),
		[skills],
	);
	const selected = useMemo(
		() => new Set([...allIds].filter((id) => !deselected.has(id))),
		[allIds, deselected],
	);

	if (isLoading) {
		return (
			<div className="space-y-2">
				<Skeleton className="h-4 w-40" />
				<Skeleton className="h-8 w-full" />
			</div>
		);
	}

	if (!skills?.length) return null;

	const toggleSkill = (id: string) => {
		setDeselected((prev) => {
			const next = new Set(prev);
			if (next.has(id)) next.delete(id);
			else next.add(id);
			return next;
		});
	};

	return (
		<div className="space-y-3">
			<h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
				Related Pending Skills ({skills.length})
			</h4>
			<div className="space-y-2">
				{skills.map((skill) => (
					<label
						key={skill.id}
						className="flex items-center gap-3 px-3 py-2 rounded border border-border hover:bg-muted/30 transition-colors cursor-pointer"
					>
						<Checkbox
							checked={selected.has(skill.id)}
							onCheckedChange={() => toggleSkill(skill.id)}
						/>
						<div className="min-w-0 flex-1">
							<p className="text-sm font-medium truncate">{skill.name}</p>
							<div className="flex items-center gap-2 text-xs text-muted-foreground">
								{skill.version && <span>v{skill.version}</span>}
								{skill.task_type && <span>{skill.task_type}</span>}
							</div>
						</div>
					</label>
				))}
			</div>
			{selected.size > 0 && (
				<Button
					size="sm"
					className="w-full h-8 text-xs bg-success/10 hover:bg-success/20 text-success border border-success/25 shadow-none"
					disabled={approveWithSkills.isPending}
					onClick={() => onApproveWithSkills(mcpId, Array.from(selected))}
				>
					<CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />
					Approve MCP + {selected.size} skill{selected.size !== 1 ? "s" : ""}
				</Button>
			)}
		</div>
	);
}

interface ReviewDetailSheetProps {
	item: ReviewItem | null;
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onApprove: (id: string, type?: string, category?: string) => void;
	onReject: (id: string, reason: string, type?: string) => void;
}

export function ReviewDetailSheet({
	item,
	open,
	onOpenChange,
	onApprove,
	onReject,
}: ReviewDetailSheetProps) {
	return (
		<Sheet open={open} onOpenChange={onOpenChange}>
			<SheetContent side="right" className="sm:max-w-2xl overflow-y-auto">
				{item ? (
					<SheetBody
						key={item.id}
						item={item}
						open={open}
						onOpenChange={onOpenChange}
						onApprove={onApprove}
						onReject={onReject}
					/>
				) : (
					<div className="space-y-4 pt-6">
						<Skeleton className="h-6 w-48" />
						<Skeleton className="h-4 w-full" />
						<Skeleton className="h-4 w-3/4" />
					</div>
				)}
			</SheetContent>
		</Sheet>
	);
}

function SheetBody({
	item,
	open,
	onOpenChange,
	onApprove,
	onReject,
}: {
	item: ReviewItem;
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onApprove: (id: string, type?: string, category?: string) => void;
	onReject: (id: string, reason: string, type?: string) => void;
}) {
	const { data: detail, isLoading } = useReviewDetail(
		open ? item.id : undefined,
	);
	const approveWithSkills = useApproveWithSkills();
	const [showRejectInput, setShowRejectInput] = useState(false);
	const [rejectReason, setRejectReason] = useState("");

	const merged = useMemo<ReviewItem>(() => {
		if (detail) return { ...item, ...detail };
		return item;
	}, [item, detail]);

	const handleReject = useCallback(() => {
		if (!showRejectInput) {
			setShowRejectInput(true);
			return;
		}
		if (!rejectReason.trim()) return;
		if (merged) {
			onReject(merged.id, rejectReason, merged.type);
			setShowRejectInput(false);
			setRejectReason("");
			onOpenChange(false);
		}
	}, [showRejectInput, rejectReason, merged, onReject, onOpenChange]);

	const handleApprove = useCallback(() => {
		if (merged) {
			onApprove(merged.id, merged.type);
			onOpenChange(false);
		}
	}, [merged, onApprove, onOpenChange]);

	const handleApproveWithSkills = useCallback(
		(mcpId: string, skillIds: string[]) => {
			approveWithSkills.mutate(
				{ id: mcpId, skillIds },
				{ onSuccess: () => onOpenChange(false) },
			);
		},
		[approveWithSkills, onOpenChange],
	);

	const disableApprove =
		merged.type === "agent" && merged.components_ready === false;

	return (
		<div className="flex flex-col gap-6">
			{/* Header */}
			<SheetHeader>
				<div className="flex items-center gap-2 flex-wrap">
					{merged.type && (
						<Badge variant="outline" className="text-[10px]">
							{merged.type}
						</Badge>
					)}
					{merged.version && (
						<span className="text-xs text-muted-foreground">
							v{merged.version}
						</span>
					)}
					<ValidationBadge item={merged} />
				</div>
				<SheetTitle className="text-lg font-[family-name:var(--font-display)]">
					{merged.name ?? "Unnamed"}
				</SheetTitle>
				{merged.description && (
					<SheetDescription>{merged.description}</SheetDescription>
				)}
			</SheetHeader>

			{/* Overview */}
			<div className="space-y-3">
				<h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
					Overview
				</h4>
				<dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
					<DetailField label="Owner" value={merged.owner} />
					<DetailField label="Submitted By" value={merged.submitted_by} />
					<DetailField
						label="Submitted"
						value={
							merged.submitted_at || merged.created_at
								? new Date(
										(merged.submitted_at ?? merged.created_at)!,
									).toLocaleDateString()
								: undefined
						}
					/>
					<DetailField
						label="Updated"
						value={
							merged.updated_at
								? new Date(merged.updated_at).toLocaleDateString()
								: undefined
						}
					/>
					<DetailField
						label="Supported IDEs"
						value={
							merged.supported_ides?.length
								? merged.supported_ides.join(", ")
								: undefined
						}
					/>
					{merged.git_url && (
						<div>
							<dt className="text-xs font-medium text-muted-foreground">
								Git URL
							</dt>
							<dd className="text-sm mt-0.5">
								<a
									href={merged.git_url}
									target="_blank"
									rel="noopener noreferrer"
									className="inline-flex items-center gap-1 text-primary hover:underline break-all"
								>
									<GitBranch className="h-3 w-3 shrink-0" />
									{merged.git_url}
								</a>
							</dd>
						</div>
					)}
					<DetailField label="Git Ref" value={merged.git_ref} />
				</dl>
			</div>

			{/* Type-specific config */}
			{isLoading ? (
				<div className="space-y-2">
					<Skeleton className="h-4 w-32" />
					<Skeleton className="h-20 w-full" />
				</div>
			) : (
				<div className="space-y-3">
					<h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
						Configuration
					</h4>
					<ConfigSection detail={merged} />
				</div>
			)}

			{/* Validation (MCP only) */}
			{merged.type === "mcp" && merged.validation_results?.length ? (
				<div className="space-y-3">
					<h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
						Validation Results
					</h4>
					<div className="space-y-2">
						{merged.validation_results.map((vr, i) => (
							<div
								key={i}
								className={`flex items-start gap-2 p-2 rounded border text-xs ${
									vr.passed
										? "border-success/25 bg-success/5"
										: "border-destructive/25 bg-destructive/5"
								}`}
							>
								<span
									className={vr.passed ? "text-success" : "text-destructive"}
								>
									{vr.passed ? "✓" : "✗"}
								</span>
								<div className="min-w-0 flex-1">
									<p className="font-medium">{vr.stage}</p>
									{vr.details && (
										<p className="text-muted-foreground whitespace-pre-wrap mt-0.5">
											{vr.details}
										</p>
									)}
									{vr.run_at && (
										<p className="text-muted-foreground mt-0.5">
											{new Date(vr.run_at).toLocaleString()}
										</p>
									)}
								</div>
							</div>
						))}
					</div>
					<ValidationDetails results={merged.validation_results} />
				</div>
			) : null}

			{/* Component Readiness (Agent only) */}
			{merged.type === "agent" && <ComponentReadinessBadge item={merged} />}

			{/* Rejection Reason */}
			{merged.rejection_reason && (
				<div className="p-3 rounded bg-destructive/5 border border-destructive/15">
					<p className="text-xs font-medium text-destructive flex items-center gap-1">
						<AlertCircle className="h-3 w-3" /> Previous Rejection
					</p>
					<p className="text-sm text-muted-foreground mt-1">
						{merged.rejection_reason}
					</p>
				</div>
			)}

			{/* Related Skills (MCP only) */}
			{merged.type === "mcp" && (
				<RelatedSkillsSection
					mcpId={merged.id}
					onApproveWithSkills={handleApproveWithSkills}
				/>
			)}

			{/* Actions */}
			<div className="space-y-3 border-t border-border pt-4">
				<div className="flex items-center justify-between">
					<Link
						to={reviewItemHref(merged)}
						className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
					>
						<ExternalLink className="h-3 w-3" /> View public page
					</Link>
				</div>

				{showRejectInput && (
					<div className="flex items-center gap-2">
						<Input
							placeholder="Reason for rejection..."
							value={rejectReason}
							onChange={(e) => setRejectReason(e.target.value)}
							className="h-8 text-xs flex-1"
							onKeyDown={(e) => {
								if (e.key === "Enter") handleReject();
								if (e.key === "Escape") {
									setShowRejectInput(false);
									setRejectReason("");
								}
							}}
							autoFocus
						/>
						<Button
							variant="ghost"
							size="sm"
							className="h-8 w-8 p-0"
							aria-label="Cancel rejection"
							onClick={() => {
								setShowRejectInput(false);
								setRejectReason("");
							}}
						>
							<X className="h-3.5 w-3.5" />
						</Button>
					</div>
				)}

				<div className="flex items-center gap-2">
					{disableApprove ? (
						<TooltipProvider>
							<Tooltip>
								<TooltipTrigger asChild>
									<span className="flex-1">
										<Button
											size="sm"
											className="h-8 text-xs w-full bg-success/10 text-success border border-success/25 shadow-none opacity-50 cursor-not-allowed"
											disabled
										>
											Approve
										</Button>
									</span>
								</TooltipTrigger>
								<TooltipContent>
									<p>Cannot approve until all required components are ready</p>
								</TooltipContent>
							</Tooltip>
						</TooltipProvider>
					) : (
						<Button
							size="sm"
							className="h-8 text-xs flex-1 bg-success/10 hover:bg-success/20 text-success border border-success/25 shadow-none"
							onClick={handleApprove}
						>
							Approve
						</Button>
					)}
					<Button
						size="sm"
						className="h-8 text-xs flex-1 bg-destructive/10 hover:bg-destructive/20 text-destructive border border-destructive/25 shadow-none"
						onClick={handleReject}
					>
						{showRejectInput ? "Confirm" : "Reject"}
					</Button>
				</div>
			</div>
		</div>
	);
}
