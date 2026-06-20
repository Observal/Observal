// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import {
  useState,
  useEffect,
  useMemo,
  useCallback,
  useRef,
} from "react";
import {
  ArrowRight,
  Loader2,
  Save,
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
  useVersionSuggestions,
} from "@/hooks/use-api";
import type {
  AgentVersionDetail,
  RegistryItem,
  ValidationResult,
} from "@/lib/types";
import type { RegistryType } from "@/lib/api";
import { SortableComponentList } from "@/components/builder/sortable-component-list";
import { ValidationPanel } from "@/components/builder/validation-panel";
import { VersionBumpDialog } from "@/components/registry/version-bump-dialog";

// ── Types ─────────────────────────────────────────────────────────

interface AgentDetail {
  name: string;
  status?: string;
  version?: string;
  owner?: string;
  user_permission?: string;
  description?: string;
  prompt?: string;
  model_name?: string;
  component_links?: ComponentLink[];
  mcp_links?: ComponentLink[];
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



export interface AgentEditFormProps {
  agentId: string;
  agent: AgentDetail;
  versionDetail?: AgentVersionDetail;
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
  const initialDescription = vd?.description ?? agent.description ?? "";
  const initialModelName = vd?.model_name ?? agent.model_name ?? "";
  const initialPrompt = vd?.prompt ?? agent.prompt ?? "";

  // ── Form state ───────────────────────────────────────────────
  const [description, setDescription] = useState(initialDescription);
  const [modelName, setModelName] = useState(initialModelName);
  const [activeTab, setActiveTab] = useState<RegistryType>("mcps");
  const [selectedComponents, setSelectedComponents] = useState<
    Record<string, RegistryItem[]>
  >({ mcps: [], skills: [], hooks: [], prompts: [], sandboxes: [] });
  const [prompt, setPrompt] = useState<string>(initialPrompt);

  // ── Dialog / loading state ────────────────────────────────────
  const [showVersionDialog, setShowVersionDialog] = useState(false);
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);

  // ── Dirty tracking ────────────────────────────────────────────
  const initialStateRef = useRef({
    description: initialDescription,
    modelName: initialModelName,
    prompt: initialPrompt,
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
  const { data: versionSuggestions } = useVersionSuggestions(agentId);

  // ── Initialize form from agent data ──────────────────────────
  const fingerprint = useMemo(
    () =>
      JSON.stringify([
        agent.name,
        currentVersion,
        versionDetail?.description,
        versionDetail?.model_name,
        versionDetail?.prompt,
        versionDetail?.components,
      ]),
    [agent.name, currentVersion, versionDetail],
  );

  useEffect(() => {
    // Reset description / modelName from latest props
    setDescription(initialDescription);
    setModelName(initialModelName);

    const links: ComponentLink[] = versionDetail?.components
      ? versionDetail.components.map((component) => ({
          component_type: component.component_type,
          component_id: component.component_id,
          component_name: component.component_name,
          mcp_name: component.mcp_name,
          name: component.name,
        }))
      : (agent.component_links ?? agent.mcp_links ?? []);
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

    // Load goal template sections

    setPrompt(initialPrompt);

    // Sync initial state ref so dirty detection works correctly after re-init
    initialStateRef.current = {
      description: initialDescription,
      modelName: initialModelName,
      prompt: initialPrompt,
      selectedComponents: grouped,
    };
    setIsDirty(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fingerprint]);

  // ── Dirty detection ───────────────────────────────────────────
  useEffect(() => {
    const init = initialStateRef.current;
    const dirty =
      description !== init.description ||
      modelName !== init.modelName ||
      prompt !== init.prompt ||
      JSON.stringify(selectedComponents) !== JSON.stringify(init.selectedComponents);
    setIsDirty(dirty);
  }, [description, modelName, prompt, selectedComponents]);

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






  function buildVersionBody(version: string) {
    const components: { component_type: string; component_id: string }[] = [];
    for (const [type, items] of Object.entries(selectedComponents)) {
      const singularType = TYPE_MAP[type] ?? type;
      for (const item of items) {
        components.push({ component_type: singularType, component_id: item.id });
      }
    }

    return {
      version,
      description: description.trim(),
      prompt: prompt.trim(),
      model_name: modelName,
      model_config_json: {},
      external_mcps: [],
      supported_ides: agent.supported_ides ?? [],
      components: components.length > 0 ? components : [],
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
        prompt,
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
      const draftVersion = versionSuggestions?.suggestions?.patch ?? currentVersion;
      const body = { ...buildVersionBody(draftVersion), save_as_draft: true };
      await createVersion.mutateAsync({ agentId, body });
      initialStateRef.current = {
        description,
        modelName,
        prompt,
        selectedComponents,
      };
      setIsDirty(false);
      onSuccess?.();
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
    setPrompt(init.prompt ?? "");
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
            <span className="ml-1 text-destructive">*</span>
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

      {/* Agent Prompt */}
      <section className="space-y-2">
        <Label htmlFor="agent-prompt" className="text-sm font-medium">
          Agent Prompt
          <span className="ml-1 text-destructive">*</span>
        </Label>
        <Textarea
          id="agent-prompt"
          placeholder="You are a senior Python engineer. You write tests first, prefer composition over inheritance, always explain your reasoning, and never delete existing tests."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={8}
          className="resize-y text-sm font-mono"
        />
        <p className="text-xs text-muted-foreground">Required. Or link a Prompt component in the Components section below.</p>
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
                0;
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

            </TabsContent>
          ))}
        </Tabs>

        <ValidationPanel
          result={validationResult}
          isValidating={validation.isPending}
        />
      </section>


      <Separator />

      {/* Actions */}
      <div className="flex items-center gap-3">
        <Button
          onClick={() => setShowVersionDialog(true)}
          disabled={publishing || savingDraft || !isDirty}
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
