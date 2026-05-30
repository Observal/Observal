// SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { Suspense, useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useRouter, useSearch } from "@tanstack/react-router";
import {
  Search,
  Plus,
  Trash2,
  Loader2,
  ArrowRight,
  Save,
  Info,
} from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { useRegistryList, useRegistryItem, useAgentValidation, useWhoami, useSaveDraft, useUpdateDraft, useStartEdit } from "@/hooks/use-api";
import { useAuthGuard } from "@/hooks/use-auth";
import { registry, type RegistryType } from "@/lib/api";
import type { RegistryItem } from "@/lib/types";
import type { ValidationResult } from "@/lib/types";

const DRAFT_STORAGE_KEY = "observal_agent_draft";

import { SortableComponentList } from "@/components/builder/sortable-component-list";
import { SubmitComponentDialog } from "@/components/registry/submit-component-dialog";
import { ValidationPanel } from "@/components/builder/validation-panel";
import { PreviewPanel } from "@/components/builder/preview-panel";
import { ModelPicker } from "@/components/builder/model-picker";

const COMPONENT_TYPES: { value: RegistryType; label: string; singular: string }[] = [
  { value: "mcps", label: "MCPs", singular: "MCP" },
  { value: "skills", label: "Skills", singular: "Skill" },
  { value: "hooks", label: "Hooks", singular: "Hook" },
  { value: "prompts", label: "Prompts", singular: "Prompt" },
  { value: "sandboxes", label: "Sandboxes", singular: "Sandbox" },
];




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
  label,
  selected,
  onToggle,
  onCreateNew,
}: {
  type: RegistryType;
  label: string;
  selected: Set<string>;
  onToggle: (item: RegistryItem) => void;
  onCreateNew: () => void;
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
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={`Search ${label}...`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 pl-9 text-sm"
          />
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 shrink-0 text-xs"
          onClick={onCreateNew}
        >
          <Plus className="mr-1 h-3 w-3" />
          Create new
        </Button>
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
  const { edit: editId, draft: draftParam } = useSearch({ from: "/_authed/agents/builder" });
  const isEditMode = !!editId;

  const { data: whoami } = useWhoami();
  const { data: existingAgent } = useRegistryItem("agents", editId ?? draftParam ?? undefined);

  const [name, setName] = useState("");
  const [nameError, setNameError] = useState("");
  const [promptError, setPromptError] = useState("");
  const [description, setDescription] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [category, setCategory] = useState("");
  const [modelName, setModelName] = useState("");
  const [modelsByIde, setModelsByIde] = useState<Record<string, string>>({});
  const [publishing, setPublishing] = useState(false);
  const [activeTab, setActiveTab] = useState<RegistryType>("mcps");

  // Version bump dialog
  const [showVersionDialog, setShowVersionDialog] = useState(false);

  // Draft state
  const [draftId, setDraftId] = useState<string | null>(null);
  const [savingDraft, setSavingDraft] = useState(false);
  const [showRestoreBanner, setShowRestoreBanner] = useState(false);
  // Components created in-builder, held in memory until agent submit
  const [pendingComponents, setPendingComponents] = useState<Array<{
    id: string; // local temp id
    type: RegistryType;
    name: string;
    body: Record<string, unknown>;
  }>>([]);
  const [createDialogType, setCreateDialogType] = useState<RegistryType | null>(null);
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

  const [systemPrompt, setSystemPrompt] = useState<string>("");

  // Goal template sections

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
    const agentModelsByIde = (existingAgent as Record<string, unknown>).models_by_ide;
    if (agentModelsByIde && typeof agentModelsByIde === "object" && !Array.isArray(agentModelsByIde)) {
      setModelsByIde(agentModelsByIde as Record<string, string>);
    }
    const agentCategory = (existingAgent as Record<string, unknown>).category;
    if (typeof agentCategory === "string") setCategory(agentCategory);

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


    const promptField = (existingAgent as Record<string, unknown>).prompt;
    if (typeof promptField === "string") setSystemPrompt(promptField);
  }, [existingAgent, draftParam]);

  // Edit lock for pending agents — acquire on mount, release on unmount
  const agentIdParam = editId ?? draftParam;
  const startEdit = useStartEdit("agents");
  const editLockAcquiredRef = useRef(false);

  useEffect(() => {
    if (!agentIdParam || !existingAgent) return;
    if ((existingAgent as Record<string, unknown>).status !== "pending") return;
    if (editLockAcquiredRef.current) return;
    editLockAcquiredRef.current = true;

    startEdit.mutate(agentIdParam, {
      onError: () => { editLockAcquiredRef.current = false; },
    });

    const releaseLock = () => {
      const token = sessionStorage.getItem("observal_access_token");
      fetch(`/api/v1/agents/${agentIdParam}/cancel-edit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        keepalive: true,
      });
    };

    window.addEventListener("beforeunload", releaseLock);
    return () => {
      window.removeEventListener("beforeunload", releaseLock);
      releaseLock();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentIdParam, existingAgent]);

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
        systemPrompt.trim().length > 0;

      if (!hasContent) return;

      try {
        const draft = {
          name,
          description,
          version,
          model_name: modelName,
          models_by_ide: modelsByIde,
          components: selectedComponents,
          prompt: systemPrompt,
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
  }, [name, description, version, modelName, selectedComponents, systemPrompt, draftId, isEditMode]);

  function restoreLocalDraft() {
    try {
      const stored = localStorage.getItem(DRAFT_STORAGE_KEY);
      if (!stored) return;
      const draft = JSON.parse(stored);
      if (draft.name) setName(draft.name);
      if (draft.description) setDescription(draft.description);
      if (draft.version) setVersion(draft.version);
      if (draft.model_name) setModelName(draft.model_name);
      if (draft.models_by_ide && typeof draft.models_by_ide === "object") {
        setModelsByIde(draft.models_by_ide);
      }
      if (draft.components) setSelectedComponents(draft.components);
      if (typeof draft.prompt === "string") setSystemPrompt(draft.prompt);
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
    const hasPromptComponent = Object.values(selectedComponents).flat().some(
      (item: RegistryItem) => selectedComponents.prompts?.find((p) => p.id === item.id)
    ) || (selectedComponents.prompts ?? []).length > 0;
    if (!systemPrompt.trim() && !hasPromptComponent) {
      setPromptError("An agent prompt is required.");
      toast.error("An agent prompt is required.");
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




  function buildRequestBody(versionOverride?: string) {
    const components: { component_type: string; component_id: string }[] = [];
    for (const [type, items] of Object.entries(selectedComponents)) {
      const singularType = TYPE_MAP[type] ?? type;
      for (const item of items) {
        components.push({ component_type: singularType, component_id: item.id });
      }
    }


    return {
      name: name.trim(),
      version: (versionOverride ?? version).trim() || "1.0.0",
      description: description.trim(),
      category: category || undefined,
      owner: whoami?.name || whoami?.email || "unknown",
      prompt: systemPrompt.trim(),
      model_name: modelName,
      models_by_ide: modelsByIde,
      components: components.length > 0 ? components : [],
    };
  }

  async function handlePublish() {
    if (!name.trim()) {
      toast.error("Agent name is required");
      return;
    }
    const hasPromptComponent = Object.values(selectedComponents).flat().some(
      (item: RegistryItem) => selectedComponents.prompts?.find((p) => p.id === item.id)
    ) || (selectedComponents.prompts ?? []).length > 0;
    if (!systemPrompt.trim() && !hasPromptComponent) {
      setPromptError("An agent prompt is required.");
      toast.error("An agent prompt is required.");
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
      // Flush in-memory components to registry first, collect real IDs
      const flushedIds: { type: RegistryType; id: string; name: string }[] = [];
      for (const pc of pendingComponents) {
        const created = await registry.submit(pc.type, pc.body);
        flushedIds.push({ type: pc.type, id: created.id, name: created.name });
      }
      if (flushedIds.length) {
        // Merge flushed IDs into selectedComponents
        const next = { ...selectedComponents };
        for (const { type, id, name } of flushedIds) {
          const plural = type as string;
          next[plural] = [...(next[plural] ?? []), { id, name }];
        }
        // Update selected components synchronously via ref trick — rebuild body after
        for (const { type, id, name } of flushedIds) {
          const plural = type as string;
          selectedComponents[plural] = [...(selectedComponents[plural] ?? []), { id, name }];
        }
        setPendingComponents([]);
      }
      const body = buildRequestBody();
      if (draftId) {
        await updateDraft.mutateAsync({ id: draftId, body });
        const agentStatus = existingAgent?.status;
        if (agentStatus && agentStatus !== "pending") {
          await registry.submitDraft(draftId);
        }
        toast.success(!agentStatus || agentStatus === "pending" ? "Changes saved." : "Agent resubmitted for review.");
        router.navigate({ to: "/agents/$agentId", params: { agentId: draftId } });
      } else {
        const created = await registry.create("agents", body);
        toast.success("Agent submitted for review. An admin must approve it before it becomes visible.");
        router.navigate({ to: "/agents/$agentId", params: { agentId: created.id } });
      }
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
      router.navigate({ to: "/agents/$agentId", params: { agentId: editId } });
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
          <div className="mb-4 flex items-center gap-3 rounded-lg border border-info/20 bg-info/5 px-4 py-3">
            <p className="flex-1 text-sm text-info">
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
                  <span className="ml-1 text-destructive">*</span>
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
                  <span className="ml-1 text-destructive">*</span>
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
                <div className="space-y-2 flex-1 max-w-[200px]">
                  <Label htmlFor="agent-category" className="text-sm font-medium">
                    Category
                  </Label>
                  <Select
                    value={category || "__none__"}
                    onValueChange={(v) => setCategory(v === "__none__" ? "" : v)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select category..." />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        <SelectItem value="__none__">Select category...</SelectItem>
                      </SelectGroup>
                      <SelectGroup>
                        <SelectLabel>Categories</SelectLabel>
                        <SelectItem value="Code Review">Code Review</SelectItem>
                        <SelectItem value="Testing">Testing</SelectItem>
                        <SelectItem value="Documentation">Documentation</SelectItem>
                        <SelectItem value="DevOps">DevOps</SelectItem>
                        <SelectItem value="Security">Security</SelectItem>
                        <SelectItem value="Data">Data</SelectItem>
                        <SelectItem value="Incident Response">Incident Response</SelectItem>
                        <SelectItem value="Deployment">Deployment</SelectItem>
                        <SelectItem value="Cost Optimization">Cost Optimization</SelectItem>
                        <SelectItem value="Other">Other</SelectItem>
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex-1">
                  <ModelPicker
                    modelName={modelName}
                    onModelNameChange={setModelName}
                    modelsByIde={modelsByIde}
                    onModelsByIdeChange={setModelsByIde}
                  />
                </div>
              </div>
            </section>

            {/* Agent Prompt */}
            <section className="space-y-4 animate-in stagger-1">
              <div className="space-y-2">
                <Label htmlFor="agent-prompt" className="text-sm font-medium">
                  Agent Prompt
                  <span className="ml-1 text-destructive">*</span>
                </Label>
                <Textarea
                  id="agent-prompt"
                  placeholder="You are a senior Python engineer. You write tests first, prefer composition over inheritance, always explain your reasoning, and never delete existing tests."
                  value={systemPrompt}
                  onChange={(e) => { setSystemPrompt(e.target.value); if (e.target.value.trim()) setPromptError(""); }}
                  rows={8}
                  className={`resize-y text-sm font-mono${promptError ? " border-destructive" : ""}`}
                />
                {promptError ? (
                  <p className="text-sm text-destructive">{promptError}</p>
                ) : (
                  <p className="text-xs text-muted-foreground">Required. Or link a Prompt component in the Components section below.</p>
                )}
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
                      label={ct.label}
                      selected={selectedIds}
                      onToggle={handleToggle(ct.value)}
                      onCreateNew={() => setCreateDialogType(ct.value)}
                    />
                    {/* In-memory components not yet submitted */}
                    {pendingComponents.filter((p) => p.type === ct.value).map((p) => (
                      <div key={p.id} className="mt-2 flex items-center gap-2 rounded border border-dashed border-border px-3 py-1.5 text-xs">
                        <span className="font-medium">{p.name}</span>
                        <span className="text-muted-foreground italic">not yet submitted</span>
                        <button
                          type="button"
                          className="ml-auto text-muted-foreground hover:text-destructive"
                          onClick={() => setPendingComponents((prev) => prev.filter((x) => x.id !== p.id))}
                        >✕</button>
                      </div>
                    ))}

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
                {isEditMode ? "Update Agent" : existingAgent?.status === "pending" ? "Save Changes" : "Submit for Review"}
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
                  Object.entries({
                    ...Object.fromEntries(
                      Object.entries(selectedComponents).map(([k, v]) =>
                        [k, v.map((item) => ({ id: item.id, name: item.name }))]
                      )
                    ),
                    // Merge in-memory pending components so they show in preview
                    ...pendingComponents.reduce((acc, pc) => {
                      acc[pc.type as string] = [...(acc[pc.type as string] ?? []), { id: pc.id, name: `${pc.name} (pending)` }];
                      return acc;
                    }, {} as Record<string, { id: string; name: string }[]>),
                  }).map(([k, v]) => [k, v])
                )}
                prompt={systemPrompt}
                pendingComponentBodies={Object.fromEntries(pendingComponents.map((pc) => [pc.id, pc.body]))}
                validationResult={validationResult}
              />
            </div>
          </aside>
        </div>
      </div>

      {/* Create in-memory component dialog */}
      {createDialogType && (
        <SubmitComponentDialog
          key={createDialogType}
          open={!!createDialogType}
          onOpenChange={(v) => { if (!v) setCreateDialogType(null); }}
          type={createDialogType}
          editItem={null}
          onSubmit={(body) => {
            const tempId = Math.random().toString(36).slice(2);
            const name = (body.name as string) || createDialogType.replace(/s$/, "");
            setPendingComponents((prev) => [...prev, { id: tempId, type: createDialogType!, name, body }]);
            setCreateDialogType(null);
            toast.success(`${name} added — will be submitted with the agent.`);
          }}
          onSaveDraft={(body) => {
            const tempId = Math.random().toString(36).slice(2);
            const name = (body.name as string) || createDialogType.replace(/s$/, "");
            setPendingComponents((prev) => [...prev, { id: tempId, type: createDialogType!, name, body }]);
            setCreateDialogType(null);
            toast.success(`${name} added — will be submitted with the agent.`);
          }}
          isSubmitting={false}
          isSavingDraft={false}
        />
      )}

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
