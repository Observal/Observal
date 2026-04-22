"use client";

import { Suspense, useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Search,
  Plus,
  Trash2,
  Loader2,
  ArrowRight,
  Save,
  FileText,
  Info,
} from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { PageHeader } from "@/components/layouts/page-header";
import { useRegistryList, useRegistryItem, useAgentValidation, useWhoami, useSaveDraft, useUpdateDraft } from "@/hooks/use-api";
import { useAuthGuard } from "@/hooks/use-auth";
import { registry, type RegistryType } from "@/lib/api";
import type { RegistryItem } from "@/lib/types";
import type { ValidationResult } from "@/lib/types";

const DRAFT_STORAGE_KEY = "observal_agent_draft";

import { SortableComponentList } from "@/components/builder/sortable-component-list";
import { ValidationPanel } from "@/components/builder/validation-panel";
import { PreviewPanel } from "@/components/builder/preview-panel";

const COMPONENT_TYPES: { value: RegistryType; label: string }[] = [
  { value: "mcps", label: "MCPs" },
  { value: "skills", label: "Skills" },
  { value: "hooks", label: "Hooks" },
  { value: "prompts", label: "Prompts" },
  { value: "sandboxes", label: "Sandboxes" },
];

interface CustomPrompt {
  id: string;
  title: string;
  content: string;
}

interface GoalSection {
  id: string;
  title: string;
  content: string;
}

function generateId() {
  return Math.random().toString(36).slice(2, 10);
}

// ── Version bump utility ──────────────────────────────────────────

type BumpType = "patch" | "minor" | "major";

function bumpVersion(current: string, type: BumpType): string {
  const parts = current.split(".").map(Number);
  if (parts.length !== 3 || parts.some(isNaN)) return current;
  if (type === "major") return `${parts[0] + 1}.0.0`;
  if (type === "minor") return `${parts[0]}.${parts[1] + 1}.0`;
  return `${parts[0]}.${parts[1]}.${parts[2] + 1}`;
}

// ── Version Bump Dialog ───────────────────────────────────────────

function VersionBumpDialog({
  open,
  onOpenChange,
  currentVersion,
  onConfirm,
  publishing,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentVersion: string;
  onConfirm: (version: string) => void;
  publishing: boolean;
}) {
  const [selection, setSelection] = useState<BumpType | "keep">("patch");

  const previewVersion = useMemo(() => {
    if (selection === "keep") return currentVersion;
    return bumpVersion(currentVersion, selection);
  }, [currentVersion, selection]);

  const options: { value: BumpType | "keep"; label: string; description: string }[] = useMemo(() => [
    {
      value: "patch",
      label: "Patch",
      description: `${currentVersion} \u2192 ${bumpVersion(currentVersion, "patch")}`,
    },
    {
      value: "minor",
      label: "Minor",
      description: `${currentVersion} \u2192 ${bumpVersion(currentVersion, "minor")}`,
    },
    {
      value: "major",
      label: "Major",
      description: `${currentVersion} \u2192 ${bumpVersion(currentVersion, "major")}`,
    },
    {
      value: "keep",
      label: "Keep current",
      description: currentVersion,
    },
  ], [currentVersion]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Version Bump</DialogTitle>
          <DialogDescription>
            Choose how to bump the version for this update.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2 py-2">
          {options.map((opt) => (
            <label
              key={opt.value}
              className={`flex cursor-pointer items-center gap-3 rounded-md border px-4 py-3 transition-colors ${
                selection === opt.value
                  ? "border-primary bg-primary/5"
                  : "border-border hover:bg-muted/50"
              }`}
            >
              <input
                type="radio"
                name="version-bump"
                value={opt.value}
                checked={selection === opt.value}
                onChange={() => setSelection(opt.value)}
                className="h-4 w-4 accent-primary"
              />
              <span className="flex-1">
                <span className="block text-sm font-medium">{opt.label}</span>
                <span className="block text-xs text-muted-foreground font-mono">
                  {opt.description}
                </span>
              </span>
            </label>
          ))}
        </div>

        <div className="rounded-md bg-muted/50 px-4 py-2.5 text-center">
          <span className="text-xs text-muted-foreground">New version: </span>
          <span className="text-sm font-semibold font-mono">{previewVersion}</span>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={publishing}
          >
            Cancel
          </Button>
          <Button
            onClick={() => onConfirm(previewVersion)}
            disabled={publishing}
          >
            {publishing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <ArrowRight className="mr-2 h-4 w-4" />
            )}
            Update Agent
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Component Picker ──────────────────────────────────────────────

function ComponentPicker({
  type,
  selected,
  onToggle,
}: {
  type: RegistryType;
  selected: Set<string>;
  onToggle: (item: RegistryItem) => void;
}) {
  const { data: items, isLoading } = useRegistryList(type);
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!items) return [];
    if (!search) return items;
    const q = search.toLowerCase();
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        (item.description?.toLowerCase().includes(q) ?? false),
    );
  }, [items, search]);

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder={`Search ${type}...`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-8 pl-9 text-sm"
        />
      </div>
      {isLoading ? (
        <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading...
        </div>
      ) : filtered.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted-foreground">
          {items?.length === 0
            ? `No ${type} in registry yet`
            : "No matches found"}
        </p>
      ) : (
        <div className="max-h-48 space-y-1 overflow-y-auto">
          {filtered.map((item) => {
            const isSelected = selected.has(item.id);
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onToggle(item)}
                className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors ${
                  isSelected
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-muted/50"
                }`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {item.name}
                  </span>
                  {item.description && (
                    <span className="block truncate text-xs text-muted-foreground">
                      {item.description}
                    </span>
                  )}
                </span>
                {isSelected && (
                  <span className="shrink-0 text-xs text-muted-foreground">
                    Added
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

const TYPE_MAP: Record<string, string> = {
  mcps: "mcp",
  skills: "skill",
  hooks: "hook",
  prompts: "prompt",
  sandboxes: "sandbox",
};

const REVERSE_TYPE_MAP: Record<string, string> = {
  mcp: "mcps",
  skill: "skills",
  hook: "hooks",
  prompt: "prompts",
  sandbox: "sandboxes",
};

const AGENT_NAME_REGEX = /^[a-z0-9][a-z0-9_-]*$/;

function slugifyName(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-/, "");
}

export default function AgentBuilderPage() {
  return (
    <Suspense>
      <AgentBuilderInner />
    </Suspense>
  );
}

function AgentBuilderInner() {
  // Require auth for builder
  const { ready } = useAuthGuard();

  const router = useRouter();
  const searchParams = useSearchParams();
  const editId = searchParams.get("edit");
  const draftParam = searchParams.get("draft");
  const isEditMode = !!editId;

  const { data: whoami } = useWhoami();
  const { data: existingAgent } = useRegistryItem("agents", editId ?? draftParam ?? undefined);

  const [name, setName] = useState("");
  const [nameError, setNameError] = useState("");
  const [description, setDescription] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [modelName, setModelName] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [activeTab, setActiveTab] = useState<RegistryType>("mcps");

  // Version bump dialog
  const [showVersionDialog, setShowVersionDialog] = useState(false);

  // Draft state
  const [draftId, setDraftId] = useState<string | null>(null);
  const [savingDraft, setSavingDraft] = useState(false);
  const [showRestoreBanner, setShowRestoreBanner] = useState(false);
  const saveDraft = useSaveDraft();
  const updateDraft = useUpdateDraft();
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Track whether we have loaded the existing agent data
  const editLoadedRef = useRef(false);

  // Selected components keyed by type
  const [selectedComponents, setSelectedComponents] = useState<
    Record<string, RegistryItem[]>
  >({
    mcps: [],
    skills: [],
    hooks: [],
    prompts: [],
    sandboxes: [],
  });

  // Custom inline prompts
  const [customPrompts, setCustomPrompts] = useState<CustomPrompt[]>([]);

  // Goal template sections
  const [goalSections, setGoalSections] = useState<GoalSection[]>([
    { id: generateId(), title: "", content: "" },
  ]);

  // Validation
  const validation = useAgentValidation();
  const [validationResult, setValidationResult] =
    useState<ValidationResult | null>(null);
  const validateTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Load existing agent data when in edit or draft-resume mode
  useEffect(() => {
    if (!existingAgent || editLoadedRef.current) return;
    editLoadedRef.current = true;

    setName(existingAgent.name ?? "");
    setDescription(existingAgent.description ?? "");
    const agentVersion = (existingAgent as Record<string, unknown>).version;
    if (typeof agentVersion === "string") setVersion(agentVersion);
    const agentModel = (existingAgent as Record<string, unknown>).model_name;
    if (typeof agentModel === "string") setModelName(agentModel);

    if (draftParam) setDraftId(draftParam);

    // Load components if available
    const agentComponents = (existingAgent as Record<string, unknown>).components;
    if (Array.isArray(agentComponents)) {
      const grouped: Record<string, RegistryItem[]> = {
        mcps: [], skills: [], hooks: [], prompts: [], sandboxes: [],
      };
      for (const comp of agentComponents) {
        const c = comp as Record<string, unknown>;
        const pluralType = REVERSE_TYPE_MAP[c.component_type as string] ?? (c.component_type as string);
        if (grouped[pluralType]) {
          grouped[pluralType].push({
            id: c.component_id as string,
            name: (c.name as string) ?? (c.component_id as string),
            description: c.description as string | undefined,
          });
        }
      }
      setSelectedComponents(grouped);
    }

    // Load goal template sections if available
    const goalTemplate = (existingAgent as Record<string, unknown>).goal_template as Record<string, unknown> | undefined;
    if (goalTemplate && Array.isArray(goalTemplate.sections)) {
      const loadedSections = (goalTemplate.sections as Array<Record<string, unknown>>).map((s) => ({
        id: generateId(),
        title: (s.name as string) ?? "",
        content: (s.description as string) ?? "",
      }));
      if (loadedSections.length > 0) setGoalSections(loadedSections);
    }

    // Load custom prompts from the prompt field
    const promptField = (existingAgent as Record<string, unknown>).prompt;
    if (typeof promptField === "string" && promptField.trim()) {
      const parts = promptField.split(/\n## /).filter(Boolean);
      const loaded: CustomPrompt[] = parts.map((part) => {
        const lines = part.startsWith("## ") ? part.slice(3).split("\n") : part.split("\n");
        const title = lines[0]?.trim() ?? "";
        const content = lines.slice(1).join("\n").trim();
        if (title && content) {
          return { id: generateId(), title, content };
        }
        return { id: generateId(), title: "", content: part.startsWith("## ") ? part.slice(3).trim() : part.trim() };
      });
      if (loaded.length > 0) setCustomPrompts(loaded);
    }
  }, [existingAgent, draftParam]);

  // Compute selected IDs for quick lookup
  const selectedIds = useMemo(() => {
    const ids = new Set<string>();
    Object.values(selectedComponents).forEach((items) =>
      items.forEach((item) => ids.add(item.id)),
    );
    return ids;
  }, [selectedComponents]);

  // Debounced validation on component changes
  useEffect(() => {
    if (validateTimerRef.current) clearTimeout(validateTimerRef.current);

    const allComponents = Object.entries(selectedComponents).flatMap(
      ([type, items]) =>
        items.map((item) => ({
          component_type: TYPE_MAP[type] ?? type,
          component_id: item.id,
        })),
    );

    if (allComponents.length === 0) {
      setValidationResult(null);
      return;
    }

    validateTimerRef.current = setTimeout(() => {
      validation.mutate(
        { components: allComponents },
        {
          onSuccess: (result) => setValidationResult(result),
          onError: () =>
            setValidationResult({ valid: false, issues: [{ severity: "error", message: "Validation request failed" }] }),
        },
      );
    }, 500);

    return () => {
      if (validateTimerRef.current) clearTimeout(validateTimerRef.current);
    };
  }, [selectedComponents]); // eslint-disable-line react-hooks/exhaustive-deps

  // Check for localStorage draft on mount (skip if in edit mode)
  useEffect(() => {
    if (isEditMode) return;
    try {
      const stored = localStorage.getItem(DRAFT_STORAGE_KEY);
      if (stored) {
        setShowRestoreBanner(true);
      }
    } catch {
      // localStorage unavailable
    }
  }, [isEditMode]);

  // Debounced localStorage auto-save (2s) — skip in edit mode
  useEffect(() => {
    if (isEditMode) return;
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);

    autoSaveTimerRef.current = setTimeout(() => {
      const hasContent = name || description || modelName || version !== "1.0.0" ||
        Object.values(selectedComponents).some((items) => items.length > 0) ||
        goalSections.some((s) => s.title || s.content) ||
        customPrompts.some((p) => p.title || p.content);

      if (!hasContent) return;

      try {
        const draft = {
          name,
          description,
          version,
          model_name: modelName,
          components: selectedComponents,
          goal_sections: goalSections,
          custom_prompts: customPrompts,
          draft_id: draftId,
          saved_at: new Date().toISOString(),
        };
        localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
      } catch {
        // localStorage full or unavailable
      }
    }, 2000);

    return () => {
      if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    };
  }, [name, description, version, modelName, selectedComponents, goalSections, customPrompts, draftId, isEditMode]);

  function restoreLocalDraft() {
    try {
      const stored = localStorage.getItem(DRAFT_STORAGE_KEY);
      if (!stored) return;
      const draft = JSON.parse(stored);
      if (draft.name) setName(draft.name);
      if (draft.description) setDescription(draft.description);
      if (draft.version) setVersion(draft.version);
      if (draft.model_name) setModelName(draft.model_name);
      if (draft.components) setSelectedComponents(draft.components);
      if (draft.goal_sections) setGoalSections(draft.goal_sections);
      if (Array.isArray(draft.custom_prompts)) setCustomPrompts(draft.custom_prompts);
      if (draft.draft_id) setDraftId(draft.draft_id);
      setShowRestoreBanner(false);
      toast.success("Draft restored");
    } catch {
      toast.error("Failed to restore draft");
    }
  }

  function discardLocalDraft() {
    try {
      localStorage.removeItem(DRAFT_STORAGE_KEY);
    } catch {
      // ignore
    }
    setShowRestoreBanner(false);
  }

  async function handleSaveDraft() {
    if (!name.trim()) {
      toast.error("Agent name is required");
      return;
    }

    setSavingDraft(true);
    try {
      const body = buildRequestBody();

      if (draftId) {
        await updateDraft.mutateAsync({ id: draftId, body });
      } else {
        const created = await saveDraft.mutateAsync(body);
        setDraftId(created.id);
      }

      // Clear localStorage on successful server save
      try {
        localStorage.removeItem(DRAFT_STORAGE_KEY);
      } catch {
        // ignore
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to save draft";
      toast.error(msg);
    } finally {
      setSavingDraft(false);
    }
  }

  const handleToggle = useCallback(
    (type: string) => (item: RegistryItem) => {
      setSelectedComponents((prev) => {
        const current = prev[type] ?? [];
        const exists = current.some((c) => c.id === item.id);
        return {
          ...prev,
          [type]: exists
            ? current.filter((c) => c.id !== item.id)
            : [...current, item],
        };
      });
    },
    [],
  );

  const removeComponent = useCallback((type: string, id: string) => {
    setSelectedComponents((prev) => ({
      ...prev,
      [type]: (prev[type] ?? []).filter((c) => c.id !== id),
    }));
  }, []);

  const addCustomPrompt = useCallback(() => {
    setCustomPrompts((prev) => [
      ...prev,
      { id: generateId(), title: "", content: "" },
    ]);
  }, []);

  const updateCustomPrompt = useCallback(
    (id: string, field: "title" | "content", value: string) => {
      setCustomPrompts((prev) =>
        prev.map((p) => (p.id === id ? { ...p, [field]: value } : p)),
      );
    },
    [],
  );

  const removeCustomPrompt = useCallback((id: string) => {
    setCustomPrompts((prev) => prev.filter((p) => p.id !== id));
  }, []);

  const handleReorder = useCallback(
    (type: string) => (items: { id: string; name: string }[]) => {
      setSelectedComponents((prev) => {
        // Preserve the full RegistryItem objects, just reorder
        const current = prev[type] ?? [];
        const ordered = items
          .map((item) => current.find((c) => c.id === item.id))
          .filter(Boolean) as RegistryItem[];
        return { ...prev, [type]: ordered };
      });
    },
    [],
  );

  const addGoalSection = useCallback(() => {
    setGoalSections((prev) => [
      ...prev,
      { id: generateId(), title: "", content: "" },
    ]);
  }, []);

  const removeGoalSection = useCallback((id: string) => {
    setGoalSections((prev) => prev.filter((s) => s.id !== id));
  }, []);

  const updateGoalSection = useCallback(
    (id: string, field: "title" | "content", value: string) => {
      setGoalSections((prev) =>
        prev.map((s) => (s.id === id ? { ...s, [field]: value } : s)),
      );
    },
    [],
  );

  function buildRequestBody(versionOverride?: string) {
    const components: { component_type: string; component_id: string }[] = [];
    for (const [type, items] of Object.entries(selectedComponents)) {
      const singularType = TYPE_MAP[type] ?? type;
      for (const item of items) {
        components.push({ component_type: singularType, component_id: item.id });
      }
    }

    const sections = goalSections
      .filter((s) => s.title.trim())
      .map((s) => ({
        name: s.title.trim(),
        description: s.content.trim() || null,
      }));

    const goalDescription = description.trim() || name.trim();

    // Build prompt field from custom inline prompts
    const promptParts = customPrompts
      .filter((p) => p.content.trim())
      .map((p) =>
        p.title.trim()
          ? `## ${p.title.trim()}\n${p.content.trim()}`
          : p.content.trim(),
      );

    return {
      name: name.trim(),
      version: (versionOverride ?? version).trim() || "1.0.0",
      description: description.trim(),
      owner: whoami?.name || whoami?.email || "unknown",
      prompt: promptParts.join("\n\n"),
      model_name: modelName,
      components: components.length > 0 ? components : [],
      goal_template: {
        description: goalDescription,
        sections: sections.length > 0 ? sections : [{ name: "Default", description: goalDescription }],
      },
    };
  }

  async function handlePublish() {
    if (!name.trim()) {
      toast.error("Agent name is required");
      return;
    }
    if (!AGENT_NAME_REGEX.test(name)) {
      toast.error(
        "Invalid agent name. Must start with a letter/digit, only lowercase letters, digits, hyphens, underscores.",
      );
      return;
    }

    // In edit mode, show the version bump dialog instead of publishing directly
    if (isEditMode) {
      setShowVersionDialog(true);
      return;
    }

    setPublishing(true);
    try {
      const body = buildRequestBody();
      const created = await registry.create("agents", body);
      toast.success("Agent submitted for review. An admin must approve it before it becomes visible.");
      router.push(`/agents/${created.id}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to publish agent";
      toast.error(msg);
    } finally {
      setPublishing(false);
    }
  }

  async function handleUpdateWithVersion(selectedVersion: string) {
    if (!editId) return;

    setPublishing(true);
    try {
      const body = buildRequestBody(selectedVersion);
      await registry.updateDraft(editId, body);
      setVersion(selectedVersion);
      setShowVersionDialog(false);
      toast.success("Agent updated and submitted for review.");
      router.push(`/agents/${editId}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to update agent";
      toast.error(msg);
    } finally {
      setPublishing(false);
    }
  }

  if (!ready) return null;

  return (
    <>
      <PageHeader
        title={isEditMode ? "Edit Agent" : "Agent Builder"}
        breadcrumbs={[
          { label: "Registry", href: "/" },
          { label: "Agents", href: "/agents" },
          { label: isEditMode ? "Edit" : "Builder" },
        ]}
      />

      <div className="p-6 lg:p-8 w-full mx-auto">
        {/* Restore draft banner */}
        {showRestoreBanner && (
          <div className="mb-4 flex items-center gap-3 rounded-lg border border-blue-500/20 bg-blue-500/5 px-4 py-3">
            <p className="flex-1 text-sm text-blue-700 dark:text-blue-300">
              You have an unsaved draft.
            </p>
            <Button variant="outline" size="sm" onClick={restoreLocalDraft}>
              Restore
            </Button>
            <Button variant="ghost" size="sm" onClick={discardLocalDraft}>
              Discard
            </Button>
          </div>
        )}

        <div className="flex flex-col gap-8 lg:flex-row">
          {/* Left column: Form */}
          <div className="min-w-0 flex-1 space-y-6 lg:max-w-[calc(66.667%-1rem)]">
            {/* Name & Description */}
            <section className="space-y-4 animate-in">
              <div className="space-y-2">
                <Label htmlFor="agent-name" className="text-sm font-medium">
                  Agent Name
                </Label>
                <Input
                  id="agent-name"
                  placeholder="my-agent"
                  value={name}
                  onChange={(e) => {
                    const slugged = slugifyName(e.target.value);
                    setName(slugged);
                    if (slugged && !AGENT_NAME_REGEX.test(slugged)) {
                      setNameError(
                        "Must start with a letter/digit, only lowercase letters, digits, hyphens, underscores.",
                      );
                    } else {
                      setNameError("");
                    }
                  }}
                  className="max-w-md"
                  required
                  disabled={isEditMode}
                />
                {nameError && (
                  <p className="text-sm text-destructive">{nameError}</p>
                )}
              </div>
              <div className="space-y-2">
                <Label
                  htmlFor="agent-description"
                  className="text-sm font-medium"
                >
                  Description
                </Label>
                <Textarea
                  id="agent-description"
                  placeholder="What does this agent do?"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  className="max-w-lg resize-y"
                />
              </div>
              <div className="flex gap-4">
                <div className="space-y-2 flex-1 max-w-[200px]">
                  <Label htmlFor="agent-version" className="text-sm font-medium">
                    Version
                  </Label>
                  <Input
                    id="agent-version"
                    placeholder="1.0.0"
                    value={version}
                    onChange={(e) => setVersion(e.target.value)}
                  />
                </div>
                <div className="space-y-2 flex-1 max-w-xs">
                  <Label htmlFor="agent-model" className="text-sm font-medium">
                    Model
                  </Label>
                  <Input
                    id="agent-model"
                    list="model-suggestions"
                    placeholder="claude-sonnet-4-20250514"
                    value={modelName}
                    onChange={(e) => setModelName(e.target.value)}
                  />
                  <datalist id="model-suggestions">
                    <option value="claude-opus-4-6-20250725" />
                    <option value="claude-sonnet-4-6-20250725" />
                    <option value="claude-sonnet-4-20250514" />
                    <option value="claude-opus-4-20250514" />
                    <option value="claude-haiku-4-5-20251001" />
                  </datalist>
                </div>
              </div>
            </section>

            <Separator />

            {/* Component Selector */}
            <section className="space-y-4 animate-in stagger-1">
              <div>
                <h3 className="text-sm font-medium font-[family-name:var(--font-display)]">
                  Components
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Select the MCPs, skills, hooks, prompts, and sandboxes for
                  this agent. Drag to reorder.
                </p>
              </div>

              <Tabs
                value={activeTab}
                onValueChange={(v) => setActiveTab(v as RegistryType)}
              >
                <TabsList>
                  {COMPONENT_TYPES.map((ct) => {
                    const count =
                      (selectedComponents[ct.value] ?? []).length +
                      (ct.value === "prompts" ? customPrompts.length : 0);
                    return (
                      <TabsTrigger key={ct.value} value={ct.value}>
                        {ct.label}
                        {count > 0 && (
                          <span className="ml-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-medium text-primary-foreground">
                            {count}
                          </span>
                        )}
                      </TabsTrigger>
                    );
                  })}
                </TabsList>

                {COMPONENT_TYPES.map((ct) => (
                  <TabsContent key={ct.value} value={ct.value}>
                    <ComponentPicker
                      type={ct.value}
                      selected={selectedIds}
                      onToggle={handleToggle(ct.value)}
                    />

                    {/* Sortable selected list */}
                    {(selectedComponents[ct.value] ?? []).length > 0 && (
                      <div className="mt-3">
                        <SortableComponentList
                          items={(selectedComponents[ct.value] ?? []).map(
                            (item) => ({ id: item.id, name: item.name }),
                          )}
                          onReorder={handleReorder(ct.value)}
                          onRemove={(id) => removeComponent(ct.value, id)}
                        />
                      </div>
                    )}

                    {/* Custom prompt input — Prompts tab only */}
                    {ct.value === "prompts" && (
                      <div className="mt-4 space-y-3">
                        <div className="flex items-center gap-3">
                          <Separator className="flex-1" />
                          <span className="shrink-0 text-xs text-muted-foreground">
                            or add custom prompt text
                          </span>
                          <Separator className="flex-1" />
                        </div>

                        {customPrompts.map((prompt) => (
                          <div
                            key={prompt.id}
                            className="rounded-md border bg-muted/20 p-4 space-y-3"
                          >
                            <div className="flex items-center gap-2">
                              <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                              <Input
                                placeholder="Prompt title (optional)"
                                value={prompt.title}
                                onChange={(e) =>
                                  updateCustomPrompt(
                                    prompt.id,
                                    "title",
                                    e.target.value,
                                  )
                                }
                                className="h-8 max-w-xs text-sm font-medium"
                              />
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => removeCustomPrompt(prompt.id)}
                                className="ml-auto h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                            <Textarea
                              placeholder="Enter prompt text..."
                              value={prompt.content}
                              onChange={(e) =>
                                updateCustomPrompt(
                                  prompt.id,
                                  "content",
                                  e.target.value,
                                )
                              }
                              rows={4}
                              className="resize-y text-sm"
                            />
                          </div>
                        ))}

                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={addCustomPrompt}
                          className="h-8"
                        >
                          <Plus className="mr-1 h-3.5 w-3.5" />
                          Add Custom Prompt
                        </Button>
                      </div>
                    )}
                  </TabsContent>
                ))}
              </Tabs>

              {/* Validation */}
              <ValidationPanel
                result={validationResult}
                isValidating={validation.isPending}
              />
            </section>

            <Separator />

            {/* Goal Template */}
            <section className="space-y-4 animate-in stagger-2">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium font-[family-name:var(--font-display)]">
                    Goal Template
                  </h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Define the agent&apos;s objective in structured sections.
                  </p>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={addGoalSection}
                  className="h-8"
                >
                  <Plus className="mr-1 h-3.5 w-3.5" />
                  Add Section
                </Button>
              </div>

              <div className="space-y-3">
                {goalSections.map((section) => (
                  <div
                    key={section.id}
                    className="rounded-md border bg-muted/20 p-4 space-y-3"
                  >
                    <div className="flex items-center gap-2">
                      <Input
                        placeholder="Section title"
                        value={section.title}
                        onChange={(e) =>
                          updateGoalSection(
                            section.id,
                            "title",
                            e.target.value,
                          )
                        }
                        className="h-8 max-w-xs text-sm font-medium"
                      />
                      {goalSections.length > 1 && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => removeGoalSection(section.id)}
                          className="ml-auto h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                    <Textarea
                      placeholder="Section content..."
                      value={section.content}
                      onChange={(e) =>
                        updateGoalSection(
                          section.id,
                          "content",
                          e.target.value,
                        )
                      }
                      rows={3}
                      className="resize-y text-sm"
                    />
                  </div>
                ))}
              </div>
            </section>

            <Separator />

            {/* Publish */}
            <div className="flex items-start gap-2 rounded-md border border-border/50 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>Only submit agents you created or are the point-of-contact for.</span>
            </div>
            <div className="flex items-center gap-3 animate-in stagger-3">
              {!isEditMode && (
                <Button
                  variant="outline"
                  onClick={handleSaveDraft}
                  disabled={savingDraft || !name.trim()}
                  className="min-w-[160px]"
                >
                  {savingDraft ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="mr-2 h-4 w-4" />
                  )}
                  Save Draft
                </Button>
              )}
              <Button
                onClick={handlePublish}
                disabled={publishing || !name.trim()}
                className="min-w-[200px]"
              >
                {publishing ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <ArrowRight className="mr-2 h-4 w-4" />
                )}
                {isEditMode ? "Update Agent" : "Submit for Review"}
              </Button>
            </div>
          </div>

          {/* Right column: Preview */}
          <aside className="w-full lg:w-1/3 animate-in stagger-1">
            <div className="sticky top-28 space-y-3">
              <PreviewPanel
                name={name}
                description={description}
                modelName={modelName}
                selectedComponents={Object.fromEntries(
                  Object.entries(selectedComponents).map(([k, v]) =>
                    [k, v.map((item) => ({ id: item.id, name: item.name }))]
                  ),
                )}
                goalSections={goalSections}
                customPrompts={customPrompts}
                validationResult={validationResult}
              />
            </div>
          </aside>
        </div>
      </div>

      {/* Version Bump Dialog — shown when updating an existing agent */}
      <VersionBumpDialog
        open={showVersionDialog}
        onOpenChange={setShowVersionDialog}
        currentVersion={version}
        onConfirm={handleUpdateWithVersion}
        publishing={publishing}
      />
    </>
  );
}
