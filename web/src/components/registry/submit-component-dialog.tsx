"use client";

import { useState } from "react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Info, Loader2, Plus, X } from "lucide-react";
import { toast } from "sonner";
import type { RegistryType } from "@/lib/api";
import { useRegistryList, useMyComponents } from "@/hooks/use-api";

const MCP_CATEGORIES = [
  "browser-automation", "cloud-platforms", "code-execution", "communication",
  "databases", "developer-tools", "devops", "file-systems", "finance",
  "knowledge-memory", "monitoring", "multimedia", "productivity", "search",
  "security", "version-control", "ai-ml", "data-analytics", "general",
];

const MCP_FRAMEWORKS = ["python", "docker", "typescript", "go"];

const MCP_TRANSPORTS = ["stdio", "sse", "streamable-http"];

const VALID_IDES = [
  "cursor", "kiro", "claude-code", "gemini-cli", "vscode", "codex", "copilot", "opencode",
];

const SKILL_TASK_TYPES = [
  "code-review", "code-generation", "testing", "documentation",
  "debugging", "refactoring", "deployment", "security-audit",
  "performance", "general",
];

const HOOK_EVENTS = [
  "PreToolUse", "PostToolUse", "Notification", "Stop",
  "SubagentStop", "SessionStart", "UserPromptSubmit",
];

const HOOK_HANDLER_TYPES = ["command", "http"];
const HOOK_EXECUTION_MODES = ["async", "sync", "blocking"];
const HOOK_SCOPES = ["agent", "session", "global"];

const PROMPT_CATEGORIES = [
  "system-prompt", "code-review", "code-generation", "testing",
  "documentation", "debugging", "general",
];

const SANDBOX_RUNTIME_TYPES = ["docker", "lxc", "firecracker", "wasm"];
const SANDBOX_NETWORK_POLICIES = ["none", "host", "bridge", "restricted"];

interface EnvVar {
  name: string;
  description: string;
  required: boolean;
}

interface SubmitComponentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  type: RegistryType;
  onSubmit: (body: Record<string, unknown>) => void;
  onSaveDraft: (body: Record<string, unknown>) => void;
  isSubmitting: boolean;
  isSavingDraft: boolean;
}

export function SubmitComponentDialog({
  open,
  onOpenChange,
  type,
  onSubmit,
  onSaveDraft,
  isSubmitting,
  isSavingDraft,
}: SubmitComponentDialogProps) {
  // ── Common ──────────────────────────────────────────────
  const [name, setName] = useState("");
  const [version, setVersion] = useState("0.1.0");
  const [description, setDescription] = useState("");
  const [owner, setOwner] = useState("");
  const [supportedIdes, setSupportedIdes] = useState<string[]>([]);

  // ── MCP ─────────────────────────────────────────────────
  const [category, setCategory] = useState("general");
  const [gitUrl, setGitUrl] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [transport, setTransport] = useState("");
  const [framework, setFramework] = useState("");
  const [dockerImage, setDockerImage] = useState("");
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [setupInstructions, setSetupInstructions] = useState("");

  // ── Skill ───────────────────────────────────────────────
  const [taskType, setTaskType] = useState("general");
  const [skillGitUrl, setSkillGitUrl] = useState("");
  const [skillPath, setSkillPath] = useState("/");
  const [mcpServerName, setMcpServerName] = useState("");

  // ── Hook ────────────────────────────────────────────────
  const [event, setEvent] = useState("PreToolUse");
  const [handlerType, setHandlerType] = useState("command");
  const [executionMode, setExecutionMode] = useState("async");
  const [hookScope, setHookScope] = useState("agent");
  const [handlerConfig, setHandlerConfig] = useState("");

  // ── Prompt ──────────────────────────────────────────────
  const [promptCategory, setPromptCategory] = useState("general");
  const [template, setTemplate] = useState("");

  // ── Sandbox ─────────────────────────────────────────────
  const [runtimeType, setRuntimeType] = useState("docker");
  const [image, setImage] = useState("");
  const [networkPolicy, setNetworkPolicy] = useState("none");
  const [entrypoint, setEntrypoint] = useState("");

  const { data: approvedMcps } = useRegistryList("mcps");
  const { data: myMcps } = useMyComponents("mcps");
  const availableMcps = (() => {
    if (type !== "skills") return [];
    const approved = approvedMcps ?? [];
    const pending = (myMcps ?? []).filter((m) => m.status === "pending");
    const seen = new Set<string>();
    const merged: typeof approved = [];
    for (const mcp of [...approved, ...pending]) {
      if (!seen.has(mcp.id)) {
        seen.add(mcp.id);
        merged.push(mcp);
      }
    }
    return merged;
  })();

  function reset() {
    setName("");
    setVersion("0.1.0");
    setDescription("");
    setOwner("");
    setSupportedIdes([]);
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
    setMcpServerName("");
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

  function buildBody(): Record<string, unknown> {
    const base: Record<string, unknown> = {
      name,
      version,
      description,
      owner,
    };
    if (supportedIdes.length > 0) base.supported_ides = supportedIdes;

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
          git_url: skillGitUrl || undefined,
          skill_path: skillPath || "/",
        };
        if (mcpServerName) {
          skillBody.mcp_server_config = { server: mcpServerName };
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
      return "At least one of Git URL, Command, or Server URL is required";
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
    setEnvVars((prev) => [...prev, { name: "", description: "", required: true }]);
  }

  function updateEnvVar(index: number, field: keyof EnvVar, value: string | boolean) {
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
    type === "mcps" ? "MCP Server" :
    type === "sandboxes" ? "Sandbox" :
    type.charAt(0).toUpperCase() + type.slice(1, -1);

  const submitError = validateForSubmit();

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
          <DialogTitle>Submit {typeLabel}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 pt-2">
          <div className="flex items-start gap-2 rounded-md border border-border/50 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>Only submit components you created (private) or are the point-of-contact for (external).</span>
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
            <Label htmlFor="comp-owner">Owner</Label>
            <Input
              id="comp-owner"
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              placeholder="your-username"
            />
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
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>Category</Label>
                  <Select value={category} onValueChange={setCategory}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {MCP_CATEGORIES.map((c) => (
                        <SelectItem key={c} value={c}>{c}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>Transport</Label>
                  <Select value={transport || "auto"} onValueChange={(v) => setTransport(v === "auto" ? "" : v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">Auto-detect</SelectItem>
                      {MCP_TRANSPORTS.map((t) => (
                        <SelectItem key={t} value={t}>{t}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
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
                  At least one of Git URL, Command, or Server URL is required for submission.
                </p>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>Framework</Label>
                  <Select value={framework || "none"} onValueChange={(v) => setFramework(v === "none" ? "" : v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">None</SelectItem>
                      {MCP_FRAMEWORKS.map((f) => (
                        <SelectItem key={f} value={f}>{f}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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
                  <Button type="button" variant="ghost" size="sm" className="h-7 text-xs" onClick={addEnvVar}>
                    <Plus className="h-3 w-3 mr-1" /> Add
                  </Button>
                </div>
                {envVars.map((ev, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Input
                      value={ev.name}
                      onChange={(e) => updateEnvVar(i, "name", e.target.value)}
                      placeholder="ENV_NAME"
                      className="flex-1 h-8 text-xs font-mono"
                    />
                    <Input
                      value={ev.description}
                      onChange={(e) => updateEnvVar(i, "description", e.target.value)}
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

          {/* ── Skill-specific ────────────────────────────── */}
          {type === "skills" && (
            <>
              <div className="space-y-1.5">
                <Label>Task Type</Label>
                <Select value={taskType} onValueChange={setTaskType}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {SKILL_TASK_TYPES.map((t) => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="skill-git-url">Git URL</Label>
                  <Input
                    id="skill-git-url"
                    value={skillGitUrl}
                    onChange={(e) => setSkillGitUrl(e.target.value)}
                    placeholder="https://github.com/..."
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="skill-path">Skill Path</Label>
                  <Input
                    id="skill-path"
                    value={skillPath}
                    onChange={(e) => setSkillPath(e.target.value)}
                    placeholder="/"
                  />
                </div>
              </div>
            </>
          )}

          {/* ── Hook-specific ─────────────────────────────── */}
          {type === "hooks" && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>Event</Label>
                  <Select value={event} onValueChange={setEvent}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {HOOK_EVENTS.map((e) => (
                        <SelectItem key={e} value={e}>{e}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>Handler Type</Label>
                  <Select value={handlerType} onValueChange={setHandlerType}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {HOOK_HANDLER_TYPES.map((h) => (
                        <SelectItem key={h} value={h}>{h}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>Execution Mode</Label>
                  <Select value={executionMode} onValueChange={setExecutionMode}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {HOOK_EXECUTION_MODES.map((m) => (
                        <SelectItem key={m} value={m}>{m}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>Scope</Label>
                  <Select value={hookScope} onValueChange={setHookScope}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {HOOK_SCOPES.map((s) => (
                        <SelectItem key={s} value={s}>{s}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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
            </>
          )}

          {/* ── Prompt-specific ───────────────────────────── */}
          {type === "prompts" && (
            <>
              <div className="space-y-1.5">
                <Label>Category</Label>
                <Select value={promptCategory} onValueChange={setPromptCategory}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {PROMPT_CATEGORIES.map((c) => (
                      <SelectItem key={c} value={c}>{c}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="prompt-template">Template *</Label>
                <Textarea
                  id="prompt-template"
                  value={template}
                  onChange={(e) => setTemplate(e.target.value)}
                  placeholder={"You are a {{role}} that helps with {{task}}.\n\nUse {{variable}} syntax for template variables."}
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
                  <Select value={runtimeType} onValueChange={setRuntimeType}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {SANDBOX_RUNTIME_TYPES.map((r) => (
                        <SelectItem key={r} value={r}>{r}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>Network Policy</Label>
                  <Select value={networkPolicy} onValueChange={setNetworkPolicy}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {SANDBOX_NETWORK_POLICIES.map((p) => (
                        <SelectItem key={p} value={p}>{p}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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

          {/* ── Supported IDEs (all types) ────────────────── */}
          <div className="space-y-1.5">
            <Label>Supported IDEs</Label>
            <div className="flex flex-wrap gap-1.5">
              {VALID_IDES.map((ide) => (
                <button
                  key={ide}
                  type="button"
                  onClick={() => toggleIde(ide)}
                  className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                    supportedIdes.includes(ide)
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted/50 text-muted-foreground hover:bg-muted"
                  }`}
                >
                  {ide}
                </button>
              ))}
            </div>
          </div>

          {/* ── Actions ───────────────────────────────────── */}
          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="outline"
              onClick={handleDraft}
              disabled={busy || !name}
            >
              {isSavingDraft && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}
              Save Draft
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={busy || !!submitError}
              title={submitError ?? undefined}
            >
              {isSubmitting && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}
              Submit for Review
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
