// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { ArrowRight, Loader2, RotateCcw, Construction } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { usePublishComponentVersion, useComponentVersionSuggestions } from "@/hooks/use-api";
import { VersionBumpDialog } from "@/components/registry/version-bump-dialog";
import type { RegistryType } from "@/lib/api";
import type { RegistryItem } from "@/lib/types";

// ── Constants ──────────────────────────────────────────────────────

const HOOK_EVENTS = [
  "SessionStart",
  "PreToolUse",
  "PostToolUse",
  "PostToolUseFailure",
  "SubagentStart",
  "SubagentStop",
  "BeforeShellExecution",
  "AfterShellExecution",
  "AfterFileEdit",
  "PreCompact",
  "Stop",
  "UserPromptSubmit",
];

const HANDLER_TYPES = ["shell", "http", "script"];
const EXECUTION_MODES = ["async", "blocking"];
const SCOPE_OPTIONS = ["agent", "global"];

// ── Types ──────────────────────────────────────────────────────────

interface ComponentEditFormProps {
  listingId: string;
  type: RegistryType;
  currentVersion: string;
  item: RegistryItem;
  onSuccess?: () => void;
}

interface HookFieldState {
  event: string;
  handler_type: string;
  execution_mode: string;
  priority: string;
  handler_config: string;
  scope: string;
  tool_filter: string;
  file_pattern: string;
}

interface SkillFieldState {
  task_type: string;
  skill_path: string;
  triggers: string;
  slash_command: string;
  has_scripts: boolean;
  has_templates: boolean;
  is_power: boolean;
  power_md: string;
  activation_keywords: string;
}

interface PromptFieldState {
  category: string;
  template: string;
  variables: string;
  model_hints: string;
  tags: string;
}

// ── WIP Stub ───────────────────────────────────────────────────────

function WipStub({ type }: { type: string }) {
  return (
    <div className="rounded-md border border-dashed border-border p-8 text-center space-y-3">
      <Construction className="h-8 w-8 mx-auto text-muted-foreground" />
      <h3 className="text-sm font-semibold font-[family-name:var(--font-display)]">
        {type === "mcp" ? "MCP" : "Sandbox"} Editing — Coming Soon
      </h3>
      <p className="text-xs text-muted-foreground max-w-md mx-auto">
        Version editing for {type === "mcp" ? "MCP servers" : "sandboxes"} requires lock file
        support and semver resolution, which is planned for Phase 2.
      </p>
      <Badge variant="secondary" className="text-[10px]">Phase 2</Badge>
    </div>
  );
}

// ── Sub-form: Hook fields ──────────────────────────────────────────

function HookFields({
  state,
  onChange,
}: {
  state: HookFieldState;
  onChange: (patch: Partial<HookFieldState>) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="hook-event" className="text-sm font-medium">
            Event
          </Label>
          <select
            id="hook-event"
            value={state.event}
            onChange={(e) => onChange({ event: e.target.value })}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="">Select event…</option>
            {HOOK_EVENTS.map((ev) => (
              <option key={ev} value={ev}>
                {ev}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="hook-handler-type" className="text-sm font-medium">
            Handler Type
          </Label>
          <select
            id="hook-handler-type"
            value={state.handler_type}
            onChange={(e) => onChange({ handler_type: e.target.value })}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="">Select type…</option>
            {HANDLER_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="hook-execution-mode" className="text-sm font-medium">
            Execution Mode
          </Label>
          <select
            id="hook-execution-mode"
            value={state.execution_mode}
            onChange={(e) => onChange({ execution_mode: e.target.value })}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="">Select mode…</option>
            {EXECUTION_MODES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="hook-scope" className="text-sm font-medium">
            Scope
          </Label>
          <select
            id="hook-scope"
            value={state.scope}
            onChange={(e) => onChange({ scope: e.target.value })}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="">Select scope…</option>
            {SCOPE_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="hook-priority" className="text-sm font-medium">
            Priority
          </Label>
          <Input
            id="hook-priority"
            type="number"
            placeholder="0"
            value={state.priority}
            onChange={(e) => onChange({ priority: e.target.value })}
          />
          <p className="text-xs text-muted-foreground">
            Lower numbers run first.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="hook-file-pattern" className="text-sm font-medium">
            File Pattern
          </Label>
          <Input
            id="hook-file-pattern"
            placeholder="*.ts, *.py (comma-separated)"
            value={state.file_pattern}
            onChange={(e) => onChange({ file_pattern: e.target.value })}
          />
          <p className="text-xs text-muted-foreground">
            Comma-separated glob patterns.
          </p>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="hook-handler-config" className="text-sm font-medium">
          Handler Config
        </Label>
        <Textarea
          id="hook-handler-config"
          placeholder='{"command": "echo hello"}'
          value={state.handler_config}
          onChange={(e) => onChange({ handler_config: e.target.value })}
          rows={4}
          className="resize-y font-[family-name:var(--font-mono)] text-xs"
        />
        <p className="text-xs text-muted-foreground">JSON configuration for the handler.</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="hook-tool-filter" className="text-sm font-medium">
          Tool Filter
        </Label>
        <Textarea
          id="hook-tool-filter"
          placeholder='{"tools": ["bash", "edit"]}'
          value={state.tool_filter}
          onChange={(e) => onChange({ tool_filter: e.target.value })}
          rows={3}
          className="resize-y font-[family-name:var(--font-mono)] text-xs"
        />
        <p className="text-xs text-muted-foreground">JSON filter for which tools trigger this hook.</p>
      </div>
    </div>
  );
}

// ── Sub-form: Skill fields ─────────────────────────────────────────

function SkillFields({
  state,
  onChange,
}: {
  state: SkillFieldState;
  onChange: (patch: Partial<SkillFieldState>) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="skill-task-type" className="text-sm font-medium">
            Task Type
          </Label>
          <Input
            id="skill-task-type"
            placeholder="code-review"
            value={state.task_type}
            onChange={(e) => onChange({ task_type: e.target.value })}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="skill-skill-path" className="text-sm font-medium">
            Skill Path
          </Label>
          <Input
            id="skill-skill-path"
            placeholder="skills/review.md"
            value={state.skill_path}
            onChange={(e) => onChange({ skill_path: e.target.value })}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="skill-slash-command" className="text-sm font-medium">
            Slash Command
          </Label>
          <Input
            id="skill-slash-command"
            placeholder="/review"
            value={state.slash_command}
            onChange={(e) => onChange({ slash_command: e.target.value })}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="skill-activation-keywords" className="text-sm font-medium">
            Activation Keywords
          </Label>
          <Input
            id="skill-activation-keywords"
            placeholder="review, check, inspect (comma-separated)"
            value={state.activation_keywords}
            onChange={(e) => onChange({ activation_keywords: e.target.value })}
          />
          <p className="text-xs text-muted-foreground">Comma-separated keywords.</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-6">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={state.has_scripts}
            onChange={(e) => onChange({ has_scripts: e.target.checked })}
            className="h-4 w-4 rounded border-input accent-primary"
          />
          <span className="text-sm">Has Scripts</span>
        </label>

        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={state.has_templates}
            onChange={(e) => onChange({ has_templates: e.target.checked })}
            className="h-4 w-4 rounded border-input accent-primary"
          />
          <span className="text-sm">Has Templates</span>
        </label>

        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={state.is_power}
            onChange={(e) => onChange({ is_power: e.target.checked })}
            className="h-4 w-4 rounded border-input accent-primary"
          />
          <span className="text-sm">Power Skill</span>
        </label>
      </div>

      {state.is_power && (
        <div className="space-y-2">
          <Label htmlFor="skill-power-md" className="text-sm font-medium">
            Power Skill Documentation
          </Label>
          <Textarea
            id="skill-power-md"
            placeholder="Describe the extended capabilities of this power skill…"
            value={state.power_md}
            onChange={(e) => onChange({ power_md: e.target.value })}
            rows={5}
            className="resize-y"
          />
        </div>
      )}

      <div className="space-y-2">
        <Label htmlFor="skill-triggers" className="text-sm font-medium">
          Triggers
        </Label>
        <Textarea
          id="skill-triggers"
          placeholder='{"on_commit": true}'
          value={state.triggers}
          onChange={(e) => onChange({ triggers: e.target.value })}
          rows={3}
          className="resize-y font-[family-name:var(--font-mono)] text-xs"
        />
        <p className="text-xs text-muted-foreground">JSON trigger configuration.</p>
      </div>
    </div>
  );
}

// ── Sub-form: Prompt fields ────────────────────────────────────────

function PromptFields({
  state,
  onChange,
}: {
  state: PromptFieldState;
  onChange: (patch: Partial<PromptFieldState>) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="prompt-category" className="text-sm font-medium">
            Category
          </Label>
          <Input
            id="prompt-category"
            placeholder="code-review"
            value={state.category}
            onChange={(e) => onChange({ category: e.target.value })}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="prompt-tags" className="text-sm font-medium">
            Tags
          </Label>
          <Input
            id="prompt-tags"
            placeholder="review, quality (comma-separated)"
            value={state.tags}
            onChange={(e) => onChange({ tags: e.target.value })}
          />
          <p className="text-xs text-muted-foreground">Comma-separated tags.</p>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="prompt-template" className="text-sm font-medium">
          Template
        </Label>
        <Textarea
          id="prompt-template"
          placeholder="You are a helpful assistant…"
          value={state.template}
          onChange={(e) => onChange({ template: e.target.value })}
          rows={8}
          className="resize-y font-[family-name:var(--font-mono)] text-xs leading-relaxed"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="prompt-variables" className="text-sm font-medium">
          Variables
        </Label>
        <Textarea
          id="prompt-variables"
          placeholder='[{"name": "language", "type": "string"}]'
          value={state.variables}
          onChange={(e) => onChange({ variables: e.target.value })}
          rows={3}
          className="resize-y font-[family-name:var(--font-mono)] text-xs"
        />
        <p className="text-xs text-muted-foreground">JSON array of variable definitions.</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="prompt-model-hints" className="text-sm font-medium">
          Model Hints
        </Label>
        <Textarea
          id="prompt-model-hints"
          placeholder='{"preferred_model": "claude-sonnet"}'
          value={state.model_hints}
          onChange={(e) => onChange({ model_hints: e.target.value })}
          rows={3}
          className="resize-y font-[family-name:var(--font-mono)] text-xs"
        />
        <p className="text-xs text-muted-foreground">JSON hints for model selection.</p>
      </div>
    </div>
  );
}

// ── Inner form (for hook/skill/prompt) ────────────────────────────

function EditFormInner({
  listingId,
  type,
  singularType,
  currentVersion,
  item,
  onSuccess,
}: {
  listingId: string;
  type: RegistryType;
  singularType: string;
  currentVersion: string;
  item: RegistryItem;
  onSuccess?: () => void;
}) {
  // ── Init helpers ──────────────────────────────────────────────

  function safeJson(value: unknown): string {
    if (value == null) return "";
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return "";
    }
  }

  function commaList(value: unknown): string {
    if (Array.isArray(value)) return value.join(", ");
    if (typeof value === "string") return value;
    return "";
  }

  // ── Shared state ──────────────────────────────────────────────
  const initialDescription = (item.description as string) ?? "";
  const initialChangelog = "";

  const [description, setDescription] = useState(initialDescription);
  const [changelog, setChangelog] = useState(initialChangelog);

  // ── Type-specific state ───────────────────────────────────────
  const initialHook: HookFieldState = {
    event: (item.event as string) ?? "",
    handler_type: (item.handler_type as string) ?? "",
    execution_mode: (item.execution_mode as string) ?? "",
    priority: item.priority != null ? String(item.priority) : "",
    handler_config: safeJson(item.handler_config),
    scope: (item.scope as string) ?? "",
    tool_filter: safeJson(item.tool_filter),
    file_pattern: commaList(item.file_pattern),
  };
  const initialSkill: SkillFieldState = {
    task_type: (item.task_type as string) ?? "",
    skill_path: (item.skill_path as string) ?? "",
    triggers: safeJson(item.triggers),
    slash_command: (item.slash_command as string) ?? "",
    has_scripts: !!(item.has_scripts as boolean),
    has_templates: !!(item.has_templates as boolean),
    is_power: !!(item.is_power as boolean),
    power_md: (item.power_md as string) ?? "",
    activation_keywords: commaList(item.activation_keywords),
  };
  const initialPrompt: PromptFieldState = {
    category: (item.category as string) ?? "",
    template: (item.template as string) ?? "",
    variables: safeJson(item.variables),
    model_hints: safeJson(item.model_hints),
    tags: commaList(item.tags),
  };

  const [hookState, setHookState] = useState<HookFieldState>(initialHook);
  const [skillState, setSkillState] = useState<SkillFieldState>(initialSkill);
  const [promptState, setPromptState] = useState<PromptFieldState>(initialPrompt);

  // ── Dialog / loading state ────────────────────────────────────
  const [showVersionDialog, setShowVersionDialog] = useState(false);
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false);
  const [publishing, setPublishing] = useState(false);

  // ── Dirty tracking ────────────────────────────────────────────
  const initialRef = useRef({
    description: initialDescription,
    changelog: initialChangelog,
    hook: initialHook,
    skill: initialSkill,
    prompt: initialPrompt,
  });
  const [isDirty, setIsDirty] = useState(false);

  useEffect(() => {
    const init = initialRef.current;
    const dirty =
      description !== init.description ||
      changelog !== init.changelog ||
      JSON.stringify(hookState) !== JSON.stringify(init.hook) ||
      JSON.stringify(skillState) !== JSON.stringify(init.skill) ||
      JSON.stringify(promptState) !== JSON.stringify(init.prompt);
    setIsDirty(dirty);
  }, [description, changelog, hookState, skillState, promptState]);

  // ── API ───────────────────────────────────────────────────────
  const publishVersion = usePublishComponentVersion();
  const { data: versionSuggestions } = useComponentVersionSuggestions(type, listingId);

  // ── Build request body ────────────────────────────────────────

  function tryParseJson(value: string): unknown {
    if (!value.trim()) return undefined;
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  }

  function buildBody(version: string): Record<string, unknown> {
    const extra: Record<string, unknown> = {};

    if (singularType === "hook") {
      if (hookState.event) extra.event = hookState.event;
      if (hookState.handler_type) extra.handler_type = hookState.handler_type;
      if (hookState.execution_mode) extra.execution_mode = hookState.execution_mode;
      if (hookState.priority !== "") extra.priority = Number(hookState.priority);
      if (hookState.scope) extra.scope = hookState.scope;
      if (hookState.handler_config) extra.handler_config = tryParseJson(hookState.handler_config);
      if (hookState.tool_filter) extra.tool_filter = tryParseJson(hookState.tool_filter);
      if (hookState.file_pattern) {
        extra.file_pattern = hookState.file_pattern.split(",").map((s) => s.trim()).filter(Boolean);
      }
    } else if (singularType === "skill") {
      if (skillState.task_type) extra.task_type = skillState.task_type;
      if (skillState.skill_path) extra.skill_path = skillState.skill_path;
      if (skillState.slash_command) extra.slash_command = skillState.slash_command;
      extra.has_scripts = skillState.has_scripts;
      extra.has_templates = skillState.has_templates;
      extra.is_power = skillState.is_power;
      if (skillState.is_power && skillState.power_md) extra.power_md = skillState.power_md;
      if (skillState.triggers) extra.triggers = tryParseJson(skillState.triggers);
      if (skillState.activation_keywords) {
        extra.activation_keywords = skillState.activation_keywords
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      }
    } else if (singularType === "prompt") {
      if (promptState.category) extra.category = promptState.category;
      if (promptState.template) extra.template = promptState.template;
      if (promptState.variables) extra.variables = tryParseJson(promptState.variables);
      if (promptState.model_hints) extra.model_hints = tryParseJson(promptState.model_hints);
      if (promptState.tags) {
        extra.tags = promptState.tags.split(",").map((s) => s.trim()).filter(Boolean);
      }
    }

    return {
      version,
      description: description.trim() || undefined,
      changelog: changelog.trim() || undefined,
      extra: Object.keys(extra).length > 0 ? extra : undefined,
    };
  }

  // ── Handlers ─────────────────────────────────────────────────

  async function handleRelease(selectedVersion: string) {
    setPublishing(true);
    try {
      const body = buildBody(selectedVersion);
      await publishVersion.mutateAsync({ type, listingId, body });
      setShowVersionDialog(false);
      // Reset dirty state
      initialRef.current = {
        description,
        changelog,
        hook: hookState,
        skill: skillState,
        prompt: promptState,
      };
      setIsDirty(false);
      onSuccess?.();
    } catch {
      // toast is handled by the mutation
    } finally {
      setPublishing(false);
    }
  }

  function handleDiscard() {
    if (isDirty) {
      setShowDiscardConfirm(true);
    }
  }

  function confirmDiscard() {
    const init = initialRef.current;
    setDescription(init.description);
    setChangelog(init.changelog);
    setHookState(init.hook);
    setSkillState(init.skill);
    setPromptState(init.prompt);
    setIsDirty(false);
    setShowDiscardConfirm(false);
  }

  return (
    <div className="space-y-6">
      {/* Shared fields */}
      <section className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="comp-name" className="text-sm font-medium">
            Name
          </Label>
          <Input
            id="comp-name"
            value={item.name}
            disabled
            className="max-w-md bg-muted/40 text-muted-foreground"
          />
          <p className="text-xs text-muted-foreground">
            Component name cannot be changed after creation.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="comp-description" className="text-sm font-medium">
            Description
          </Label>
          <Textarea
            id="comp-description"
            placeholder={`What does this ${singularType} do?`}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="max-w-lg resize-y"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="comp-changelog" className="text-sm font-medium">
            Changelog
          </Label>
          <Textarea
            id="comp-changelog"
            placeholder="What changed in this version?"
            value={changelog}
            onChange={(e) => setChangelog(e.target.value)}
            rows={2}
            className="max-w-lg resize-y"
          />
          <p className="text-xs text-muted-foreground">
            Briefly describe what changed for users reviewing this version.
          </p>
        </div>
      </section>

      <Separator />

      {/* Type-specific fields */}
      <section className="space-y-4">
        <div>
          <h3 className="text-sm font-medium font-[family-name:var(--font-display)]">
            {singularType === "hook"
              ? "Hook Configuration"
              : singularType === "skill"
              ? "Skill Configuration"
              : "Prompt Configuration"}
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Configure the {singularType}-specific fields for this version.
          </p>
        </div>

        {singularType === "hook" && (
          <HookFields
            state={hookState}
            onChange={(patch) => setHookState((prev) => ({ ...prev, ...patch }))}
          />
        )}

        {singularType === "skill" && (
          <SkillFields
            state={skillState}
            onChange={(patch) => setSkillState((prev) => ({ ...prev, ...patch }))}
          />
        )}

        {singularType === "prompt" && (
          <PromptFields
            state={promptState}
            onChange={(patch) => setPromptState((prev) => ({ ...prev, ...patch }))}
          />
        )}
      </section>

      <Separator />

      {/* Actions */}
      <div className="flex items-center gap-3">
        <Button
          onClick={() => setShowVersionDialog(true)}
          disabled={publishing || !isDirty}
          className="min-w-[160px]"
        >
          {publishing ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <ArrowRight className="mr-2 h-4 w-4" />
          )}
          Save &amp; Release
        </Button>

        <Button
          variant="ghost"
          onClick={handleDiscard}
          disabled={!isDirty || publishing}
          className="text-muted-foreground hover:text-foreground"
        >
          <RotateCcw className="mr-2 h-4 w-4" />
          Discard
        </Button>
      </div>

      {/* Version Bump Dialog */}
      <VersionBumpDialog
        open={showVersionDialog}
        onOpenChange={setShowVersionDialog}
        currentVersion={currentVersion}
        suggestions={versionSuggestions}
        onConfirm={handleRelease}
        publishing={publishing}
      />

      {/* Discard Confirm Dialog */}
      <Dialog open={showDiscardConfirm} onOpenChange={setShowDiscardConfirm}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Discard changes?</DialogTitle>
            <DialogDescription>
              All unsaved changes will be lost. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDiscardConfirm(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmDiscard}>
              Discard
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ── Public export ──────────────────────────────────────────────────

export function ComponentEditForm({
  listingId,
  type,
  currentVersion,
  item,
  onSuccess,
}: ComponentEditFormProps) {
  const singularType = type === "sandboxes" ? "sandbox" : type.replace(/s$/, "");

  if (singularType === "mcp" || singularType === "sandbox") {
    return <WipStub type={singularType} />;
  }

  return (
    <EditFormInner
      listingId={listingId}
      type={type}
      singularType={singularType}
      currentVersion={currentVersion}
      item={item}
      onSuccess={onSuccess}
    />
  );
}
