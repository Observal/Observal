// SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useState, useRef, useCallback } from "react";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { CodeEditor } from "@/components/ui/code-editor";
import { PickerSelect } from "@/components/ui/picker-select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Check, Info, Loader2, Plus, X } from "lucide-react";
import { toast } from "sonner";
import type { RegistryType } from "@/lib/api";
import { useWhoami } from "@/hooks/use-api";
import { useHarnesses } from "@/hooks/use-harnesses";
import { parseMcpConfigJson, applyParsedConfig } from "@/lib/mcp-parser";
import type { EnvVar } from "@/lib/mcp-parser";

const MCP_CATEGORIES = [
	"browser-automation",
	"cloud-platforms",
	"code-execution",
	"communication",
	"databases",
	"developer-tools",
	"devops",
	"file-systems",
	"finance",
	"knowledge-memory",
	"monitoring",
	"multimedia",
	"productivity",
	"search",
	"security",
	"version-control",
	"ai-ml",
	"data-analytics",
	"general",
];

const MCP_FRAMEWORKS = ["python", "docker", "typescript", "go"];

const MCP_TRANSPORTS = ["stdio", "sse", "streamable-http"];

function mcpExampleConfig(isEditMode: boolean, name: string) {
	return isEditMode
		? `{
  "mcpServers": {
    "${name || "my-server"}": {
      "command": "npx",
      "args": ["-y", "@example/mcp-server@latest"],
      "env": { "API_KEY": "$API_KEY" }
    }
  }
}`
		: `{
  "mcpServers": {
    "my-server": {
      "command": "npx",
      "args": ["-y", "@example/mcp-server"],
      "env": { "API_KEY": "$API_KEY" }
    }
  }
}`;
}

const SKILL_TASK_TYPES = [
	"code-review",
	"code-generation",
	"testing",
	"documentation",
	"debugging",
	"refactoring",
	"deployment",
	"security-audit",
	"performance",
	"general",
];

const HOOK_EVENTS = [
	"PreToolUse",
	"PostToolUse",
	"Notification",
	"Stop",
	"SubagentStop",
	"SessionStart",
	"UserPromptSubmit",
];

const HOOK_HANDLER_TYPES = ["command", "http"];
const HOOK_EXECUTION_MODES = ["async", "sync", "blocking"];
const HOOK_SCOPES = ["agent", "session", "global"];

const PROMPT_CATEGORIES = [
	"system-prompt",
	"code-review",
	"code-generation",
	"testing",
	"documentation",
	"debugging",
	"general",
];

const SANDBOX_RUNTIME_TYPES = ["docker", "lxc", "firecracker", "wasm"];
const SANDBOX_NETWORK_POLICIES = ["none", "host", "bridge", "restricted"];

interface SubmitComponentDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	type: RegistryType;
	onSubmit: (body: Record<string, unknown>) => void;
	onSaveDraft: (body: Record<string, unknown>) => void;
	onUpdateDraft?: (id: string, body: Record<string, unknown>) => void;
	isSubmitting: boolean;
	isSavingDraft: boolean;
	editItem?: Record<string, unknown> | null;
}

export function SubmitComponentDialog({
	open,
	onOpenChange,
	type,
	onSubmit,
	onSaveDraft,
	onUpdateDraft,
	isSubmitting,
	isSavingDraft,
	editItem,
}: SubmitComponentDialogProps) {
	const d = editItem as Record<string, unknown> | null;
	const { data: whoami } = useWhoami();
	const { data: ideList } = useHarnesses();
	const defaultOwner =
		(d?.owner as string) ||
		whoami?.username ||
		whoami?.email ||
		"";

	// ── Common ──────────────────────────────────────────────
	const [name, setName] = useState((d?.name as string) ?? "");
	const [version, setVersion] = useState((d?.version as string) ?? "0.1.0");
	const [description, setDescription] = useState(
		(d?.description as string) ?? "",
	);
	const owner = defaultOwner;
	const [supportedIdes, setSupportedIdes] = useState<string[]>(
		Array.isArray(d?.supported_harnesses) ? (d.supported_harnesses as string[]) : [],
	);

	// ── MCP ─────────────────────────────────────────────────
	const [mcpMode, setMcpMode] = useState<"json" | "manual">("json");
	const [jsonInput, setJsonInput] = useState("");
	const [jsonError, setJsonError] = useState<string | null>(null);
	const [jsonParsed, setJsonParsed] = useState(false);
	const [category, setCategory] = useState(
		(d?.category as string) ?? "general",
	);
	const [gitUrl, setGitUrl] = useState((d?.git_url as string) ?? "");
	const [command, setCommand] = useState((d?.command as string) ?? "");
	const [args, setArgs] = useState(
		Array.isArray(d?.args) ? (d.args as string[]).join(" ") : "",
	);
	const [mcpUrl, setMcpUrl] = useState((d?.url as string) ?? "");
	const [transport, setTransport] = useState((d?.transport as string) ?? "");
	const [framework, setFramework] = useState((d?.framework as string) ?? "");
	const [dockerImage, setDockerImage] = useState(
		(d?.docker_image as string) ?? "",
	);
	const [envVars, setEnvVars] = useState<EnvVar[]>(
		Array.isArray(d?.environment_variables)
			? (d.environment_variables as EnvVar[])
			: [],
	);
	const [setupInstructions, setSetupInstructions] = useState(
		(d?.setup_instructions as string) ?? "",
	);

	// ── Skill ───────────────────────────────────────────────
	const [taskType, setTaskType] = useState(
		(d?.task_type as string) ?? "general",
	);
	const [skillGitUrl, setSkillGitUrl] = useState((d?.git_url as string) ?? "");
	const [skillPath, setSkillPath] = useState((d?.skill_path as string) ?? "/");
	const [skillPathAuto, setSkillPathAuto] = useState(true); // true = auto-discovered or default
	const [skillPathHint, setSkillPathHint] = useState<string | null>(null);
	const [skillGitRef, setSkillGitRef] = useState((d?.git_ref as string) ?? "");
	const [skillMdContent, setSkillMdContent] = useState(
		(d?.skill_md_content as string) ?? "",
	);
	const [skillScriptContent, setSkillScriptContent] = useState(
		(d?.script_content as string) ?? "",
	);
	const [skillScriptFilename, setSkillScriptFilename] = useState(
		(d?.script_filename as string) ?? "",
	);
	const [skillMode, setSkillMode] = useState<"git" | "paste">("git");

	// Auto-discover skill_path from GitHub Trees API when git_url changes
	const skillDiscoverRef = useRef<ReturnType<typeof setTimeout>>(undefined);
	const [skillDiscovering, setSkillDiscovering] = useState(false);
	const handleSkillGitUrl = useCallback(
		(url: string) => {
			setSkillGitUrl(url);
			setSkillPathHint(null);
			clearTimeout(skillDiscoverRef.current);
			if (!url.trim()) return;
			// Parse GitHub owner/repo from URL
			const m = url.match(/github\.com\/([^/]+)\/([^/.]+)/);
			if (!m) return;
			const [, owner, repo] = m;
			skillDiscoverRef.current = setTimeout(async () => {
				setSkillDiscovering(true);
				try {
					const ref = skillGitRef || "main";
					const res = await fetch(
						`https://api.github.com/repos/${owner}/${repo}/git/trees/${ref}?recursive=1`,
					);
					if (!res.ok) {
						setSkillDiscovering(false);
						return;
					}
					const data = await res.json();
					// Filter: find SKILL.md files, excluding harness config copies
					// harness dirs (.claude/, .kiro/, .agents/, etc.) are installed copies, not sources
					const INSTALLED_PREFIX =
						/^(\.agents|\.(claude|kiro|cursor|gemini|github|opencode|pi|trae|trae-cn|rovodev|qoder|copilot)|plugin)\//;
					const allSkillFiles = (data.tree || []).filter(
						(f: { path: string }) =>
							f.path.endsWith("/SKILL.md") || f.path === "SKILL.md",
					);
					// Prefer canonical (non-installed) paths; fall back to all if none found
					const canonical = allSkillFiles.filter(
						(f: { path: string }) => !INSTALLED_PREFIX.test(f.path),
					);
					const skillFiles = canonical.length > 0 ? canonical : allSkillFiles;
					if (skillFiles.length === 1) {
						const found =
							skillFiles[0].path.replace(/\/?SKILL\.md$/, "") || "/";
						setSkillPath(found);
						setSkillPathAuto(true);
						setSkillPathHint(
							`Found SKILL.md at ${found === "/" ? "repo root" : found}`,
						);
					} else if (skillFiles.length > 1) {
						setSkillPathAuto(false);
						setSkillPathHint(
							`${skillFiles.length} SKILL.md files found — pick a path`,
						);
					} else {
						setSkillPathAuto(false);
						setSkillPathHint("No SKILL.md found in repo");
					}
				} catch {
					/* network error — user can enter path manually */
				}
				setSkillDiscovering(false);
			}, 600);
		},
		[skillGitRef],
	);

	// ── Hook ────────────────────────────────────────────────
	const [event, setEvent] = useState((d?.event as string) ?? "PreToolUse");
	const [handlerType, setHandlerType] = useState(
		(d?.handler_type as string) ?? "command",
	);
	const [executionMode, setExecutionMode] = useState(
		(d?.execution_mode as string) ?? "async",
	);
	const [hookScope, setHookScope] = useState((d?.scope as string) ?? "agent");
	const [handlerConfig, setHandlerConfig] = useState(
		d?.handler_config && typeof d.handler_config === "object"
			? JSON.stringify(d.handler_config, null, 2)
			: "",
	);
	const [scriptContent, setScriptContent] = useState(
		(d?.script_content as string) ?? "",
	);
	const [scriptFilename, setScriptFilename] = useState(
		(d?.script_filename as string) ?? "",
	);

	// ── Prompt ──────────────────────────────────────────────
	const [promptCategory, setPromptCategory] = useState(
		type === "prompts" ? ((d?.category as string) ?? "general") : "general",
	);
	const [template, setTemplate] = useState((d?.template as string) ?? "");

	// ── Sandbox ─────────────────────────────────────────────
	const [runtimeType, setRuntimeType] = useState(
		(d?.runtime_type as string) ?? "docker",
	);
	const [image, setImage] = useState((d?.image as string) ?? "");
	const [networkPolicy, setNetworkPolicy] = useState(
		(d?.network_policy as string) ?? "none",
	);
	const [entrypoint, setEntrypoint] = useState((d?.entrypoint as string) ?? "");

	function bumpPatchVersion(ver: string): string {
		const parts = ver.split(".");
		if (parts.length === 3) {
			const patch = parseInt(parts[2], 10);
			if (!isNaN(patch)) return `${parts[0]}.${parts[1]}.${patch + 1}`;
		}
		return ver;
	}

	const jsonParseTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
	const isEditing = !!editItem;

	const handleJsonInput = useCallback(
		(value: string) => {
			setJsonInput(value);
			setJsonError(null);
			setJsonParsed(false);

			clearTimeout(jsonParseTimerRef.current);
			if (!value.trim()) return;

			jsonParseTimerRef.current = setTimeout(() => {
				const { parsed, error } = parseMcpConfigJson(value);
				if (error) {
					setJsonError(error);
					return;
				}
				if (!parsed) return;

				const setters = {
					setCommand,
					setArgs,
					setMcpUrl,
					setTransport,
					setFramework,
					setDockerImage,
					setEnvVars,
					setName: isEditing ? setName : !name ? setName : undefined,
					setDescription: isEditing
						? setDescription
						: !description
							? setDescription
							: undefined,
				};

				if (isEditing) {
					applyParsedConfig(parsed, setters, "overwrite");
					setVersion(bumpPatchVersion(version));
				} else {
					applyParsedConfig(parsed, setters, "fill");
				}
				setJsonParsed(true);
			}, 300);
		},
		[isEditing, name, description, version],
	);

	function reset() {
		setName("");
		setVersion("0.1.0");
		setDescription("");
		setSupportedIdes([]);
		setMcpMode("json");
		setJsonInput("");
		setJsonError(null);
		setJsonParsed(false);
		setCategory("general");
		setGitUrl("");
		setCommand("");
		setArgs("");
		setMcpUrl("");
		setTransport("");
		setFramework("");
		setDockerImage("");
		setEnvVars([]);
		setSetupInstructions("");
		setTaskType("general");
		setSkillGitUrl("");
		setSkillPath("/");
		setSkillPathAuto(true);
		setSkillPathHint(null);
		setSkillGitRef("");
		setSkillMdContent("");
		setSkillScriptContent("");
		setSkillScriptFilename("");
		setSkillMode("git");
		setEvent("PreToolUse");
		setHandlerType("command");
		setExecutionMode("async");
		setHookScope("agent");
		setHandlerConfig("");
		setPromptCategory("general");
		setTemplate("");
		setRuntimeType("docker");
		setImage("");
		setNetworkPolicy("none");
		setEntrypoint("");
	}

	const isEditMode = !!editItem;
	const isPendingEdit = isEditMode && d?.status === "pending";

	function buildBody(): Record<string, unknown> {
		const base: Record<string, unknown> = {
			name,
			version,
			description,
			owner,
		};
		if (supportedIdes.length > 0) base.supported_harnesses = supportedIdes;

		switch (type) {
			case "mcps": {
				const body: Record<string, unknown> = {
					...base,
					category,
				};
				if (gitUrl) body.git_url = gitUrl;
				if (command) body.command = command;
				if (args.trim()) body.args = args.split(/\s+/).filter(Boolean);
				if (mcpUrl) body.url = mcpUrl;
				if (transport) body.transport = transport;
				if (framework) body.framework = framework;
				if (dockerImage) body.docker_image = dockerImage;
				if (envVars.length > 0) body.environment_variables = envVars;
				if (setupInstructions) body.setup_instructions = setupInstructions;
				return body;
			}
			case "skills": {
				const skillBody: Record<string, unknown> = {
					...base,
					task_type: taskType,
					delivery_mode: skillMode === "paste" ? "registry_direct" : "git_fetch",
				};
				if (skillMode === "git") {
					skillBody.git_url = skillGitUrl || undefined;
					skillBody.skill_path = skillPath || "/";
					if (skillGitRef) skillBody.git_ref = skillGitRef;
				} else {
					if (skillMdContent) skillBody.skill_md_content = skillMdContent;
					if (skillScriptContent) skillBody.script_content = skillScriptContent;
					if (skillScriptFilename) skillBody.script_filename = skillScriptFilename;
				}
				return skillBody;
			}
			case "hooks": {
				const body: Record<string, unknown> = {
					...base,
					event,
					handler_type: handlerType,
					execution_mode: executionMode,
					scope: hookScope,
				};
				if (handlerConfig.trim()) {
					try {
						body.handler_config = JSON.parse(handlerConfig);
					} catch {
						/* leave as default {} */
					}
				}
				if (scriptContent.trim()) {
					body.script_content = scriptContent;
					body.script_filename = scriptFilename || undefined;
				}
				return body;
			}
			case "prompts":
				return { ...base, category: promptCategory, template };
			case "sandboxes":
				return {
					...base,
					runtime_type: runtimeType,
					image,
					network_policy: networkPolicy,
					entrypoint: entrypoint || undefined,
				};
			default:
				return base;
		}
	}

	function validateForSubmit(): string | null {
		if (!name) return "Name is required";
		if (!description) return "Description is required";

		if (type === "mcps" && !gitUrl && !command && !mcpUrl) {
			if (mcpMode === "json" && !jsonParsed && !isEditMode) {
				return "Paste a valid server config JSON";
			}
			if (mcpMode === "json" && !jsonParsed && isEditMode) {
				// Edit mode: existing fields from editItem are still valid
				const d = editItem as Record<string, unknown> | null;
				if (!d?.command && !d?.url && !d?.git_url) {
					return "Paste a new server config JSON to update";
				}
			}
			if (mcpMode === "manual") {
				return "At least one of Git URL, Command, or Server URL is required";
			}
		}
		if (type === "prompts" && !template) {
			return "Template is required";
		}
		if (type === "sandboxes" && !image) {
			return "Image is required";
		}
		return null;
	}

	function handleSubmit() {
		const err = validateForSubmit();
		if (err) {
			toast.error(err);
			return;
		}
		onSubmit(buildBody());
	}

	function handleDraft() {
		if (!name) {
			toast.error("Name is required");
			return;
		}
		onSaveDraft(buildBody());
	}

	function addEnvVar() {
		setEnvVars((prev) => [
			...prev,
			{ name: "", description: "", required: true },
		]);
	}

	function updateEnvVar(
		index: number,
		field: keyof EnvVar,
		value: string | boolean,
	) {
		setEnvVars((prev) =>
			prev.map((ev, i) => (i === index ? { ...ev, [field]: value } : ev)),
		);
	}

	function removeEnvVar(index: number) {
		setEnvVars((prev) => prev.filter((_, i) => i !== index));
	}

	function toggleIde(ide: string) {
		setSupportedIdes((prev) =>
			prev.includes(ide) ? prev.filter((i) => i !== ide) : [...prev, ide],
		);
	}

	const busy = isSubmitting || isSavingDraft;
	const typeLabel =
		type === "mcps"
			? "MCP Server"
			: type === "sandboxes"
				? "Sandbox"
				: type.charAt(0).toUpperCase() + type.slice(1, -1);

	const submitError = validateForSubmit();
	const jsonExample = mcpExampleConfig(isEditMode, name);

	return (
		<Dialog
			open={open}
			onOpenChange={(v) => {
				if (!v) reset();
				onOpenChange(v);
			}}
		>
			<DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
				<DialogHeader>
					<DialogTitle>
						{isEditMode ? `Edit ${typeLabel}` : `Submit ${typeLabel}`}
					</DialogTitle>
				</DialogHeader>

				<div className="space-y-4 pt-2">
					<div className="flex items-start gap-2 rounded-md border border-border/50 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
						<Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
						<span>
							Only submit components you created (private) or are the
							point-of-contact for (external).
						</span>
					</div>

					{/* ── Common fields ──────────────────────────────── */}
					<div className="grid grid-cols-2 gap-3">
						<div className="space-y-1.5">
							<Label htmlFor="comp-name">Name *</Label>
							<Input
								id="comp-name"
								value={name}
								onChange={(e) => setName(e.target.value)}
								placeholder="my-component"
							/>
						</div>
						<div className="space-y-1.5">
							<Label htmlFor="comp-version">Version</Label>
							<Input
								id="comp-version"
								value={version}
								onChange={(e) => setVersion(e.target.value)}
								placeholder="0.1.0"
							/>
						</div>
					</div>

					<div className="space-y-1.5">
						<Label htmlFor="comp-desc">Description *</Label>
						<Textarea
							id="comp-desc"
							value={description}
							onChange={(e) => setDescription(e.target.value)}
							placeholder="What does this component do?"
							rows={3}
						/>
					</div>

					{/* ── MCP-specific ──────────────────────────────── */}
					{type === "mcps" && (
						<>
							<div className="space-y-1.5">
								<Label>Category</Label>
								<PickerSelect
									value={category}
									onValueChange={setCategory}
									options={MCP_CATEGORIES.map((c) => ({ value: c, label: c }))}
								/>
							</div>

							{/* ── JSON paste mode (default) ─────────────── */}
							{mcpMode === "json" && (
								<>
									<div className="space-y-1.5">
										<div className="flex items-center justify-between gap-3">
											<Label htmlFor="mcp-json">
												{isEditMode
													? "Paste Updated Config (JSON)"
													: "Server Config (JSON)"}
											</Label>
											<Button
												type="button"
												variant="ghost"
												size="sm"
												onClick={() => handleJsonInput(jsonExample)}
												className="h-7 text-xs"
											>
												{jsonInput ? "Replace example" : "Insert example"}
											</Button>
										</div>
										<CodeEditor
											id="mcp-json"
											value={jsonInput}
											onChange={handleJsonInput}
											language="json"
											placeholder="Paste MCP JSON here, or insert the example."
										/>
										<p className="text-xs text-muted-foreground">
											Paste directly or type JSON. Brackets and quotes auto-close.
										</p>
										{jsonError && (
											<p className="text-xs text-destructive">{jsonError}</p>
										)}
										{jsonParsed && (
											<div className="flex items-center gap-1.5 text-xs text-green-600">
												<Check className="h-3 w-3" />
												<span>
													{isEditMode ? "Config updated" : "Config parsed"}:{" "}
													{command && `${command} `}
													{args && `${args} `}
													{mcpUrl && `${mcpUrl} `}
													{envVars.length > 0 &&
														`(${envVars.length} env var${envVars.length > 1 ? "s" : ""})`}
													{isEditMode && ` — version bumped to ${version}`}
												</span>
											</div>
										)}
									</div>

									<button
										type="button"
										onClick={() => setMcpMode("manual")}
										className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2"
									>
										Switch to manual entry
									</button>
								</>
							)}

							{/* ── Manual mode (field-by-field) ──────────── */}
							{mcpMode === "manual" && (
								<>
									<button
										type="button"
										onClick={() => setMcpMode("json")}
										className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2"
									>
										Switch to paste config
									</button>

									<div className="space-y-1.5">
										<Label>Transport</Label>
										<PickerSelect
											value={transport || "auto"}
											onValueChange={(v) => setTransport(v === "auto" ? "" : v)}
											options={[
												{ value: "auto", label: "Auto-detect" },
												...MCP_TRANSPORTS.map((t) => ({ value: t, label: t })),
											]}
										/>
									</div>

									<div className="space-y-1.5">
										<Label htmlFor="mcp-git-url">Git URL</Label>
										<Input
											id="mcp-git-url"
											value={gitUrl}
											onChange={(e) => setGitUrl(e.target.value)}
											placeholder="https://github.com/user/mcp-server"
										/>
									</div>

									<div className="grid grid-cols-2 gap-3">
										<div className="space-y-1.5">
											<Label htmlFor="mcp-command">Command</Label>
											<Input
												id="mcp-command"
												value={command}
												onChange={(e) => setCommand(e.target.value)}
												placeholder="npx, uvx, node..."
											/>
										</div>
										<div className="space-y-1.5">
											<Label htmlFor="mcp-args">Args</Label>
											<Input
												id="mcp-args"
												value={args}
												onChange={(e) => setArgs(e.target.value)}
												placeholder="space-separated args"
											/>
										</div>
									</div>

									<div className="space-y-1.5">
										<Label htmlFor="mcp-url">Server URL (SSE/HTTP)</Label>
										<Input
											id="mcp-url"
											value={mcpUrl}
											onChange={(e) => setMcpUrl(e.target.value)}
											placeholder="http://localhost:3000/sse"
										/>
									</div>

									{!gitUrl && !command && !mcpUrl && (
										<p className="text-xs text-destructive">
											At least one of Git URL, Command, or Server URL is
											required for submission.
										</p>
									)}

									<div className="grid grid-cols-2 gap-3">
										<div className="space-y-1.5">
											<Label>Framework</Label>
											<PickerSelect
												value={framework || "none"}
												onValueChange={(v) => setFramework(v === "none" ? "" : v)}
												options={[
													{ value: "none", label: "None" },
													...MCP_FRAMEWORKS.map((f) => ({ value: f, label: f })),
												]}
											/>
										</div>
										<div className="space-y-1.5">
											<Label htmlFor="mcp-docker">Docker Image</Label>
											<Input
												id="mcp-docker"
												value={dockerImage}
												onChange={(e) => setDockerImage(e.target.value)}
												placeholder="user/image:tag"
											/>
										</div>
									</div>

									{/* Environment Variables */}
									<div className="space-y-2">
										<div className="flex items-center justify-between">
											<Label>Environment Variables</Label>
											<Button
												type="button"
												variant="ghost"
												size="sm"
												className="h-7 text-xs"
												onClick={addEnvVar}
											>
												<Plus className="h-3 w-3 mr-1" /> Add
											</Button>
										</div>
										{envVars.map((ev, i) => (
											<div key={i} className="flex items-center gap-2">
												<Input
													value={ev.name}
													onChange={(e) =>
														updateEnvVar(i, "name", e.target.value)
													}
													placeholder="ENV_NAME"
													className="flex-1 h-8 text-xs font-mono"
												/>
												<Input
													value={ev.description}
													onChange={(e) =>
														updateEnvVar(i, "description", e.target.value)
													}
													placeholder="Description"
													className="flex-1 h-8 text-xs"
												/>
												<Button
													type="button"
													variant="ghost"
													size="sm"
													className="h-7 w-7 p-0 shrink-0"
													onClick={() => removeEnvVar(i)}
												>
													<X className="h-3 w-3" />
												</Button>
											</div>
										))}
									</div>

									<div className="space-y-1.5">
										<Label htmlFor="mcp-setup">Setup Instructions</Label>
										<Textarea
											id="mcp-setup"
											value={setupInstructions}
											onChange={(e) => setSetupInstructions(e.target.value)}
											placeholder="Steps to configure this MCP server..."
											rows={3}
											className="text-sm"
										/>
									</div>
								</>
							)}
						</>
					)}

					{/* ── Skill-specific ────────────────────────────── */}
					{type === "skills" && (
						<>
							<div className="space-y-1.5">
								<Label>Task Type</Label>
								<PickerSelect
									value={taskType}
									onValueChange={setTaskType}
									options={SKILL_TASK_TYPES.map((t) => ({ value: t, label: t }))}
								/>
							</div>

							<Tabs value={skillMode} onValueChange={(v) => setSkillMode(v as "git" | "paste")} className="w-full">
								<TabsList className="grid w-full grid-cols-2">
									<TabsTrigger value="git">Git Submit</TabsTrigger>
									<TabsTrigger value="paste">Registry Submit</TabsTrigger>
								</TabsList>

								<TabsContent value="git" className="space-y-3 pt-3">
									<div className="grid grid-cols-2 gap-3">
										<div className="space-y-1.5">
											<Label htmlFor="skill-git-url">Git URL *</Label>
											<Input
												id="skill-git-url"
												value={skillGitUrl}
												onChange={(e) => handleSkillGitUrl(e.target.value)}
												placeholder="https://github.com/org/skills"
											/>
											{skillDiscovering && (
												<p className="text-xs text-muted-foreground flex items-center gap-1">
													<Loader2 className="h-3 w-3 animate-spin" />
													Looking for SKILL.md…
												</p>
											)}
											{skillPathHint && !skillDiscovering && (
												<p
													className={`text-xs ${skillPathAuto ? "text-green-600" : "text-amber-600"}`}
												>
													{skillPathHint}
												</p>
											)}
										</div>
										{!skillPathAuto && (
											<div className="space-y-1.5">
												<Label htmlFor="skill-path">Skill Path</Label>
												<Input
													id="skill-path"
													value={skillPath}
													onChange={(e) => {
														setSkillPath(e.target.value);
														setSkillPathAuto(false);
													}}
													placeholder="skills/my-skill"
												/>
											</div>
										)}
									</div>
									<div className="space-y-1.5">
										<Label htmlFor="skill-git-ref">Git Ref (branch / tag)</Label>
										<Input
											id="skill-git-ref"
											value={skillGitRef}
											onChange={(e) => setSkillGitRef(e.target.value)}
											placeholder="main"
										/>
									</div>
								</TabsContent>

								<TabsContent value="paste" className="space-y-3 pt-3">
									<div className="space-y-1.5">
										<Label htmlFor="skill-md-content">SKILL.md *</Label>
										<Textarea
											id="skill-md-content"
											value={skillMdContent}
											onChange={(e) => {
												const raw = e.target.value;
												setSkillMdContent(raw);
												// Auto-fill name/description from frontmatter
												const fmMatch = raw.match(/^---\r?\n([\s\S]*?)\r?\n---/);
												if (fmMatch) {
													const lines = fmMatch[1].split(/\r?\n/);
													for (const line of lines) {
														const nm = line.match(/^name:\s*(.+)$/);
														if (nm && !name) setName(nm[1].trim());
														const dm = line.match(
															/^description:\s*["']?(.+?)["']?$/,
														);
														if (dm && !description) setDescription(dm[1].trim());
													}
												}
											}}
											placeholder={`---\nname: my-skill\ndescription: What this skill does\ncommand: /my-skill\n---\n\n## Instructions\n\nYour skill instructions here...`}
											rows={10}
											className="font-mono text-xs"
										/>
										<p className="text-xs text-muted-foreground">
											Frontmatter auto-fills name and description above.
										</p>
									</div>
									<div className="space-y-1.5">
										<Label htmlFor="skill-script-filename">Script Filename (optional)</Label>
										<Input
											id="skill-script-filename"
											value={skillScriptFilename}
											onChange={(e) => setSkillScriptFilename(e.target.value)}
											placeholder="run.sh"
											className="font-mono"
										/>
										<p className="text-xs text-muted-foreground">
											Name of the script file that will be written on install.
										</p>
									</div>
									<div className="space-y-1.5">
										<Label htmlFor="skill-script-content">Script (optional)</Label>
										<Textarea
											id="skill-script-content"
											value={skillScriptContent}
											onChange={(e) => setSkillScriptContent(e.target.value)}
											placeholder={"#!/bin/bash\n# Script that the skill can invoke\n# Stored in the registry and delivered on install"}
											rows={8}
											className="font-mono text-xs"
										/>
										<p className="text-xs text-muted-foreground">
											Script content stored in the registry and delivered on install. Similar to hook scripts.
										</p>
									</div>
								</TabsContent>
							</Tabs>
						</>
					)}

					{/* ── Hook-specific ─────────────────────────────── */}
					{type === "hooks" && (
						<>
							<div className="grid grid-cols-2 gap-3">
								<div className="space-y-1.5">
									<Label>Event</Label>
									<PickerSelect
										value={event}
										onValueChange={setEvent}
										options={HOOK_EVENTS.map((e) => ({ value: e, label: e }))}
									/>
								</div>
								<div className="space-y-1.5">
									<Label>Handler Type</Label>
									<PickerSelect
										value={handlerType}
										onValueChange={setHandlerType}
										options={HOOK_HANDLER_TYPES.map((h) => ({ value: h, label: h }))}
									/>
								</div>
							</div>
							<div className="grid grid-cols-2 gap-3">
								<div className="space-y-1.5">
									<Label>Execution Mode</Label>
									<PickerSelect
										value={executionMode}
										onValueChange={setExecutionMode}
										options={HOOK_EXECUTION_MODES.map((m) => ({ value: m, label: m }))}
									/>
								</div>
								<div className="space-y-1.5">
									<Label>Scope</Label>
									<PickerSelect
										value={hookScope}
										onValueChange={setHookScope}
										options={HOOK_SCOPES.map((s) => ({ value: s, label: s }))}
									/>
								</div>
							</div>
							<div className="space-y-1.5">
								<Label htmlFor="hook-config">Handler Config (JSON)</Label>
								<Textarea
									id="hook-config"
									value={handlerConfig}
									onChange={(e) => setHandlerConfig(e.target.value)}
									placeholder='{"command": "./my-hook.sh"}'
									rows={3}
									className="font-mono text-sm"
								/>
							</div>
							<div className="space-y-1.5">
								<Label htmlFor="hook-script-filename">
									Script Filename (optional)
								</Label>
								<input
									id="hook-script-filename"
									type="text"
									value={scriptFilename}
									onChange={(e) => setScriptFilename(e.target.value)}
									placeholder="my-hook.sh"
									className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring font-mono"
								/>
								<p className="text-xs text-muted-foreground">
									Name of the script file that will be written on install.
								</p>
							</div>
							<div className="space-y-1.5">
								<Label htmlFor="hook-script">Hook Script (optional)</Label>
								<Textarea
									id="hook-script"
									value={scriptContent}
									onChange={(e) => setScriptContent(e.target.value)}
									placeholder={
										"#!/bin/bash\nINPUT=$(cat)\n# Your hook logic here\nexit 0"
									}
									rows={8}
									className="font-mono text-sm"
								/>
								<p className="text-xs text-muted-foreground">
									Script content stored in the registry and delivered on
									install. Leave empty for inline commands.
								</p>
							</div>
						</>
					)}

					{/* ── Prompt-specific ───────────────────────────── */}
					{type === "prompts" && (
						<>
							<div className="space-y-1.5">
								<Label>Category</Label>
								<PickerSelect
									value={promptCategory}
									onValueChange={setPromptCategory}
									options={PROMPT_CATEGORIES.map((c) => ({ value: c, label: c }))}
								/>
							</div>
							<div className="space-y-1.5">
								<Label htmlFor="prompt-template">Template *</Label>
								<Textarea
									id="prompt-template"
									value={template}
									onChange={(e) => setTemplate(e.target.value)}
									placeholder={
										"You are a {{role}} that helps with {{task}}.\n\nUse {{variable}} syntax for template variables."
									}
									rows={6}
									className="font-mono text-sm"
								/>
							</div>
						</>
					)}

					{/* ── Sandbox-specific ──────────────────────────── */}
					{type === "sandboxes" && (
						<>
							<div className="grid grid-cols-2 gap-3">
								<div className="space-y-1.5">
									<Label>Runtime Type</Label>
									<PickerSelect
										value={runtimeType}
										onValueChange={setRuntimeType}
										options={SANDBOX_RUNTIME_TYPES.map((r) => ({ value: r, label: r }))}
									/>
								</div>
								<div className="space-y-1.5">
									<Label>Network Policy</Label>
									<PickerSelect
										value={networkPolicy}
										onValueChange={setNetworkPolicy}
										options={SANDBOX_NETWORK_POLICIES.map((p) => ({ value: p, label: p }))}
									/>
								</div>
							</div>
							<div className="grid grid-cols-2 gap-3">
								<div className="space-y-1.5">
									<Label htmlFor="sandbox-image">Image *</Label>
									<Input
										id="sandbox-image"
										value={image}
										onChange={(e) => setImage(e.target.value)}
										placeholder="ubuntu:22.04"
									/>
								</div>
								<div className="space-y-1.5">
									<Label htmlFor="sandbox-entry">Entrypoint</Label>
									<Input
										id="sandbox-entry"
										value={entrypoint}
										onChange={(e) => setEntrypoint(e.target.value)}
										placeholder="/bin/bash"
									/>
								</div>
							</div>
						</>
					)}

					{/* ── Supported harnesses (all types) ────────────────── */}
					<div className="space-y-1.5">
						<Label>Supported harnesses</Label>
						<div className="flex flex-wrap gap-1.5">
							{(ideList ?? []).map((ide) => (
								<button
									key={ide.name}
									type="button"
									onClick={() => toggleIde(ide.name)}
									className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
										supportedIdes.includes(ide.name)
											? "bg-primary text-primary-foreground"
											: "bg-muted/50 text-muted-foreground hover:bg-muted"
									}`}
								>
									{ide.display_name}
								</button>
							))}
						</div>
					</div>

					{/* ── Actions ───────────────────────────────────── */}
					<div className="flex justify-end gap-2 pt-2">
						{isEditMode ? (
							<>
								{isPendingEdit ? (
									<Button
										onClick={() => {
											const err = validateForSubmit();
											if (err) {
												toast.error(err);
												return;
											}
											onUpdateDraft?.(
												(editItem as Record<string, unknown>).id as string,
												buildBody(),
											);
										}}
										disabled={busy || !!submitError}
										title={submitError ?? undefined}
									>
										{isSavingDraft && (
											<Loader2 className="h-4 w-4 animate-spin mr-1.5" />
										)}
										Save Changes
									</Button>
								) : (
									<>
										<Button
											variant="outline"
											onClick={() => {
												if (!name) {
													toast.error("Name is required");
													return;
												}
												onUpdateDraft?.(
													(editItem as Record<string, unknown>).id as string,
													buildBody(),
												);
											}}
											disabled={busy || !name}
										>
											{isSavingDraft && (
												<Loader2 className="h-4 w-4 animate-spin mr-1.5" />
											)}
											Save Changes
										</Button>
										<Button
											onClick={() => {
												const err = validateForSubmit();
												if (err) {
													toast.error(err);
													return;
												}
												onUpdateDraft?.(
													(editItem as Record<string, unknown>).id as string,
													buildBody(),
												);
												onSubmit(buildBody());
											}}
											disabled={busy || !!submitError}
											title={submitError ?? undefined}
										>
											{isSubmitting && (
												<Loader2 className="h-4 w-4 animate-spin mr-1.5" />
											)}
											Save & Resubmit
										</Button>
									</>
								)}
							</>
						) : (
							<>
								<Button
									variant="outline"
									onClick={handleDraft}
									disabled={busy || !name}
								>
									{isSavingDraft && (
										<Loader2 className="h-4 w-4 animate-spin mr-1.5" />
									)}
									Save Draft
								</Button>
								<Button
									onClick={handleSubmit}
									disabled={busy || !!submitError}
									title={submitError ?? undefined}
								>
									{isSubmitting && (
										<Loader2 className="h-4 w-4 animate-spin mr-1.5" />
									)}
									Submit for Review
								</Button>
							</>
						)}
					</div>
				</div>
			</DialogContent>
		</Dialog>
	);
}
