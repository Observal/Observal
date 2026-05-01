"use client";

import {
  useState,
  useEffect,
  useMemo,
  useCallback,
  useRef,
} from "react";
import {
  ArrowRight,
  FileText,
  Loader2,
  Plus,
  Save,
  Trash2,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Search } from "lucide-react";
import {
  useRegistryList,
  useAgentValidation,
  useCreateAgentVersion,
  useUpdateAgent,
} from "@/hooks/use-api";
import type { RegistryItem, ValidationResult } from "@/lib/types";
import type { RegistryType } from "@/lib/api";
import { SortableComponentList } from "@/components/builder/sortable-component-list";
import { ValidationPanel } from "@/components/builder/validation-panel";

// ── Types ─────────────────────────────────────────────────────────

interface AgentDetail {
  name: string;
  status?: string;
  version?: string;
  owner?: string;
  visibility?: string;
  team_accesses?: { group_name: string; permission: "view" | "edit" }[];
  user_permission?: string;
  description?: string;
  prompt?: string;
  model_name?: string;
  component_links?: ComponentLink[];
  mcp_links?: ComponentLink[];
  goal_template?: {
    description?: string;
    sections?: { name: string; description?: string }[];
  };
  supported_ides?: string[];
  [key: string]: unknown;
}

interface ComponentLink {
  component_name?: string;
  mcp_name?: string;
  name?: string;
  component_type?: string;
  component_id?: string;
  mcp_id?: string;
}

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

export interface AgentEditFormProps {
  agentId: string;
  agent: AgentDetail;
  versionDetail?: Record<string, unknown>;
  currentVersion: string;
  onSuccess?: () => void;
}

// ── Constants ─────────────────────────────────────────────────────

const COMPONENT_TYPES: { value: RegistryType; label: string }[] = [
  { value: "mcps", label: "MCPs" },
  { value: "skills", label: "Skills" },
  { value: "hooks", label: "Hooks" },
  { value: "prompts", label: "Prompts" },
  { value: "sandboxes", label: "Sandboxes" },
];

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


// ── Utilities ─────────────────────────────────────────────────────

function generateId() {
  return Math.random().toString(36).slice(2, 10);
}

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

  const options: { value: BumpType | "keep"; label: string; description: string }[] =
    useMemo(
      () => [
        {
          value: "patch",
          label: "Patch",
          description: `${currentVersion} → ${bumpVersion(currentVersion, "patch")}`,
        },
        {
          value: "minor",
          label: "Minor",
          description: `${currentVersion} → ${bumpVersion(currentVersion, "minor")}`,
        },
        {
          value: "major",
          label: "Major",
          description: `${currentVersion} → ${bumpVersion(currentVersion, "major")}`,
        },
        {
          value: "keep",
          label: "Keep current",
          description: currentVersion,
        },
      ],
      [currentVersion],
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Release New Version</DialogTitle>
          <DialogDescription>
            Choose how to bump the version for this release.
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
                <span className="block font-mono text-xs text-muted-foreground">
                  {opt.description}
                </span>
              </span>
            </label>
          ))}
        </div>

        <div className="rounded-md bg-muted/50 px-4 py-2.5 text-center">
          <span className="text-xs text-muted-foreground">New version: </span>
          <span className="font-mono text-sm font-semibold">{previewVersion}</span>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={publishing}
          >
            Cancel
          </Button>
          <Button onClick={() => onConfirm(previewVersion)} disabled={publishing}>
            {publishing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <ArrowRight className="mr-2 h-4 w-4" />
            )}
            Release
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
          {items?.length === 0 ? `No ${type} in registry yet` : "No matches found"}
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
                  isSelected ? "bg-accent text-accent-foreground" : "hover:bg-muted/50"
                }`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{item.name}</span>
                  {item.description && (
                    <span className="block truncate text-xs text-muted-foreground">
                      {item.description}
                    </span>
                  )}
                </span>
                {isSelected && (
                  <span className="shrink-0 text-xs text-muted-foreground">Added</span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────

export function AgentEditForm({
  agentId,
  agent,
  versionDetail,
  currentVersion,
  onSuccess,
}: AgentEditFormProps) {
  // Merge version-specific fields over base agent data
  const vd = versionDetail;
  const initialDescription = (vd?.description as string) ?? agent.description ?? "";
  const initialModelName = (vd?.model_name as string) ?? agent.model_name ?? "";
  const initialPrompt = (vd?.prompt as string) ?? agent.prompt ?? "";

  // ── Form state ───────────────────────────────────────────────
  const [description, setDescription] = useState(initialDescription);
  const [modelName, setModelName] = useState(initialModelName);
  const [activeTab, setActiveTab] = useState<RegistryType>("mcps");
  const [selectedComponents, setSelectedComponents] = useState<
    Record<string, RegistryItem[]>
  >({ mcps: [], skills: [], hooks: [], prompts: [], sandboxes: [] });
  const [customPrompts, setCustomPrompts] = useState<CustomPrompt[]>([]);
  const [goalSections, setGoalSections] = useState<GoalSection[]>([
    { id: generateId(), title: "", content: "" },
  ]);

  // ── Dialog / loading state ────────────────────────────────────
  const [showVersionDialog, setShowVersionDialog] = useState(false);
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);

  // ── Dirty tracking ────────────────────────────────────────────
  const initialStateRef = useRef({
    description: initialDescription,
    modelName: initialModelName,
    customPrompts: [] as CustomPrompt[],
    goalSections: [] as GoalSection[],
    selectedComponents: {} as Record<string, RegistryItem[]>,
  });
  const [isDirty, setIsDirty] = useState(false);

  // ── Validation ────────────────────────────────────────────────
  const validation = useAgentValidation();
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const validateTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // ── Mutations ─────────────────────────────────────────────────
  const createVersion = useCreateAgentVersion();
  const updateAgent = useUpdateAgent();

  // ── Initialize form from agent data ──────────────────────────
  const initializedRef = useRef(false);
  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;

    // Load components from component_links / mcp_links
    const links: ComponentLink[] = agent.component_links ?? agent.mcp_links ?? [];
    if (links.length > 0) {
      const grouped: Record<string, RegistryItem[]> = {
        mcps: [], skills: [], hooks: [], prompts: [], sandboxes: [],
      };
      for (const comp of links) {
        const singularType = comp.component_type ?? "mcp";
        const pluralType = REVERSE_TYPE_MAP[singularType] ?? singularType;
        const compId = comp.component_id ?? comp.mcp_id;
        const compName = comp.component_name ?? comp.mcp_name ?? comp.name ?? compId ?? "";
        if (grouped[pluralType] && compId) {
          grouped[pluralType].push({ id: compId, name: compName });
        }
      }
      setSelectedComponents(grouped);
      initialStateRef.current.selectedComponents = grouped;
    }

    // Load goal template sections
    const gt = agent.goal_template;
    if (gt?.sections && gt.sections.length > 0) {
      const loaded = gt.sections.map((s) => ({
        id: generateId(),
        title: s.name ?? "",
        content: s.description ?? "",
      }));
      setGoalSections(loaded);
      initialStateRef.current.goalSections = loaded;
    }

    // Load custom prompts from prompt string
    const promptField = initialPrompt;
    if (promptField.trim()) {
      const parts = promptField.split(/\n## /).filter(Boolean);
      const loaded: CustomPrompt[] = parts.map((part) => {
        const lines = part.startsWith("## ")
          ? part.slice(3).split("\n")
          : part.split("\n");
        const title = lines[0]?.trim() ?? "";
        const content = lines.slice(1).join("\n").trim();
        return {
          id: generateId(),
          title: title && content ? title : "",
          content: title && content ? content : (part.startsWith("## ") ? part.slice(3).trim() : part.trim()),
        };
      });
      if (loaded.length > 0) {
        setCustomPrompts(loaded);
        initialStateRef.current.customPrompts = loaded;
      }
    }
  }, [agent, initialPrompt]);

  // ── Dirty detection ───────────────────────────────────────────
  useEffect(() => {
    const init = initialStateRef.current;
    const dirty =
      description !== init.description ||
      modelName !== init.modelName ||
      JSON.stringify(customPrompts) !== JSON.stringify(init.customPrompts) ||
      JSON.stringify(goalSections) !== JSON.stringify(init.goalSections) ||
      JSON.stringify(selectedComponents) !== JSON.stringify(init.selectedComponents);
    setIsDirty(dirty);
  }, [description, modelName, customPrompts, goalSections, selectedComponents]);

  // ── Debounced validation ──────────────────────────────────────
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
            setValidationResult({
              valid: false,
              issues: [{ severity: "error", message: "Validation request failed" }],
            }),
        },
      );
    }, 500);

    return () => {
      if (validateTimerRef.current) clearTimeout(validateTimerRef.current);
    };
  }, [selectedComponents]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Handlers ─────────────────────────────────────────────────

  const selectedIds = useMemo(() => {
    const ids = new Set<string>();
    Object.values(selectedComponents).forEach((items) =>
      items.forEach((item) => ids.add(item.id)),
    );
    return ids;
  }, [selectedComponents]);

  const handleToggle = useCallback(
    (type: string) => (item: RegistryItem) => {
      setSelectedComponents((prev) => {
        const current = prev[type] ?? [];
        const exists = current.some((c) => c.id === item.id);
        return {
          ...prev,
          [type]: exists ? current.filter((c) => c.id !== item.id) : [...current, item],
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

  const handleReorder = useCallback(
    (type: string) => (items: { id: string; name: string }[]) => {
      setSelectedComponents((prev) => {
        const current = prev[type] ?? [];
        const ordered = items
          .map((item) => current.find((c) => c.id === item.id))
          .filter(Boolean) as RegistryItem[];
        return { ...prev, [type]: ordered };
      });
    },
    [],
  );

  const addCustomPrompt = useCallback(() => {
    setCustomPrompts((prev) => [...prev, { id: generateId(), title: "", content: "" }]);
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

  const addGoalSection = useCallback(() => {
    setGoalSections((prev) => [...prev, { id: generateId(), title: "", content: "" }]);
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


  function buildVersionBody(version: string) {
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

    const promptParts = customPrompts
      .filter((p) => p.content.trim())
      .map((p) =>
        p.title.trim()
          ? `## ${p.title.trim()}\n${p.content.trim()}`
          : p.content.trim(),
      );

    return {
      version,
      description: description.trim(),
      prompt: promptParts.join("\n\n"),
      model_name: modelName,
      model_config_json: {},
      external_mcps: [],
      supported_ides: agent.supported_ides ?? [],
      components: components.length > 0 ? components : [],
      goal_template: {
        description: description.trim() || agent.name,
        sections:
          sections.length > 0 ? sections : [{ name: "Default", description: description.trim() || agent.name }],
      },
      yaml_snapshot: null,
      is_prerelease: false,
    };
  }

  async function handleRelease(selectedVersion: string) {
    setPublishing(true);
    try {
      const body = buildVersionBody(selectedVersion);
      await createVersion.mutateAsync({ agentId, body });
      setShowVersionDialog(false);
      // Reset dirty state
      initialStateRef.current = {
        description,
        modelName,
        customPrompts,
        goalSections,
        selectedComponents,
      };
      setIsDirty(false);
      onSuccess?.();
    } catch {
      // toast handled by mutation
    } finally {
      setPublishing(false);
    }
  }

  async function handleSaveDraft() {
    setSavingDraft(true);
    try {
      await updateAgent.mutateAsync({
        id: agentId,
        body: {
          description: description.trim(),
          model_name: modelName,
        },
      });
      initialStateRef.current.description = description;
      initialStateRef.current.modelName = modelName;
      setIsDirty(false);
    } catch {
      // toast handled by mutation
    } finally {
      setSavingDraft(false);
    }
  }

  function handleDiscard() {
    if (isDirty) {
      setShowDiscardConfirm(true);
    }
  }

  function confirmDiscard() {
    const init = initialStateRef.current;
    setDescription(init.description);
    setModelName(init.modelName);
    setCustomPrompts(init.customPrompts);
    setGoalSections(
      init.goalSections.length > 0
        ? init.goalSections
        : [{ id: generateId(), title: "", content: "" }],
    );
    setSelectedComponents(
      Object.keys(init.selectedComponents).length > 0
        ? init.selectedComponents
        : { mcps: [], skills: [], hooks: [], prompts: [], sandboxes: [] },
    );
    setIsDirty(false);
    setShowDiscardConfirm(false);
  }

  return (
    <div className="space-y-6">
      {/* Agent name — read-only */}
      <section className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="agent-name" className="text-sm font-medium">
            Agent Name
          </Label>
          <Input
            id="agent-name"
            value={agent.name}
            disabled
            className="max-w-md bg-muted/40 text-muted-foreground"
          />
          <p className="text-xs text-muted-foreground">
            Agent name cannot be changed after creation.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="agent-description" className="text-sm font-medium">
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

        <div className="space-y-2 max-w-xs">
          <Label htmlFor="agent-model" className="text-sm font-medium">
            Model
          </Label>
          <Input
            id="agent-model"
            list="edit-model-suggestions"
            placeholder="claude-sonnet-4-20250514"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
          />
          <datalist id="edit-model-suggestions">
            <option value="claude-opus-4-6-20250725" />
            <option value="claude-sonnet-4-6-20250725" />
            <option value="claude-sonnet-4-20250514" />
            <option value="claude-opus-4-20250514" />
            <option value="claude-haiku-4-5-20251001" />
          </datalist>
        </div>
      </section>

      <Separator />

      {/* Components */}
      <section className="space-y-4">
        <div>
          <h3 className="text-sm font-medium font-[family-name:var(--font-display)]">
            Components
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Select the MCPs, skills, hooks, prompts, and sandboxes for this agent. Drag to reorder.
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

              {(selectedComponents[ct.value] ?? []).length > 0 && (
                <div className="mt-3">
                  <SortableComponentList
                    items={(selectedComponents[ct.value] ?? []).map((item) => ({
                      id: item.id,
                      name: item.name,
                    }))}
                    onReorder={handleReorder(ct.value)}
                    onRemove={(id) => removeComponent(ct.value, id)}
                  />
                </div>
              )}

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
                        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <Input
                          placeholder="Prompt title (optional)"
                          value={prompt.title}
                          onChange={(e) =>
                            updateCustomPrompt(prompt.id, "title", e.target.value)
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
                          updateCustomPrompt(prompt.id, "content", e.target.value)
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

        <ValidationPanel
          result={validationResult}
          isValidating={validation.isPending}
        />
      </section>


      <Separator />

      {/* Goal Template */}
      <section className="space-y-4">
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
                  onChange={(e) => updateGoalSection(section.id, "title", e.target.value)}
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
                onChange={(e) => updateGoalSection(section.id, "content", e.target.value)}
                rows={3}
                className="resize-y text-sm"
              />
            </div>
          ))}
        </div>
      </section>

      <Separator />

      {/* Actions */}
      <div className="flex items-center gap-3">
        <Button
          onClick={() => setShowVersionDialog(true)}
          disabled={publishing || savingDraft}
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
          variant="outline"
          onClick={handleSaveDraft}
          disabled={savingDraft || publishing || !isDirty}
          className="min-w-[120px]"
        >
          {savingDraft ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          Save Draft
        </Button>

        <Button
          variant="ghost"
          onClick={handleDiscard}
          disabled={!isDirty || publishing || savingDraft}
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
