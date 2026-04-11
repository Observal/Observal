"use client";

import { useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Search,
  X,
  Plus,
  Trash2,
  Loader2,
  ArrowRight,
} from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Card, CardContent } from "@/components/ui/card";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import { PageHeader } from "@/components/layouts/page-header";
import { useRegistryList } from "@/hooks/use-api";
import { registry, type RegistryType } from "@/lib/api";
import type { RegistryItem } from "@/lib/types";

const COMPONENT_TYPES: { value: RegistryType; label: string }[] = [
  { value: "mcps", label: "MCPs" },
  { value: "skills", label: "Skills" },
  { value: "hooks", label: "Hooks" },
  { value: "prompts", label: "Prompts" },
  { value: "sandboxes", label: "Sandboxes" },
];

interface GoalSection {
  id: string;
  title: string;
  content: string;
}

function generateId() {
  return Math.random().toString(36).slice(2, 10);
}

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

function PreviewPanel({
  name,
  description,
  selectedComponents,
  goalSections,
}: {
  name: string;
  description: string;
  selectedComponents: Record<string, RegistryItem[]>;
  goalSections: GoalSection[];
}) {
  const lines: string[] = [];

  lines.push(`name: ${name || "(untitled)"}`);
  if (description) {
    lines.push(`description: |`);
    description.split("\n").forEach((l) => lines.push(`  ${l}`));
  }

  const hasComponents = Object.values(selectedComponents).some(
    (arr) => arr.length > 0,
  );
  if (hasComponents) {
    lines.push("");
    lines.push("components:");
    for (const [type, items] of Object.entries(selectedComponents)) {
      if (items.length === 0) continue;
      lines.push(`  ${type}:`);
      items.forEach((item) => lines.push(`    - ${item.name}`));
    }
  }

  const nonEmptyGoals = goalSections.filter((s) => s.title || s.content);
  if (nonEmptyGoals.length > 0) {
    lines.push("");
    lines.push("goal:");
    nonEmptyGoals.forEach((section) => {
      lines.push(`  ${section.title || "(section)"}:`);
      if (section.content) {
        section.content
          .split("\n")
          .forEach((l) => lines.push(`    ${l}`));
      }
    });
  }

  return (
    <pre className="min-h-[200px] whitespace-pre-wrap rounded-md border bg-muted/30 p-4 text-sm leading-relaxed font-[family-name:var(--font-mono)] text-foreground/80">
      {lines.join("\n")}
    </pre>
  );
}

export default function AgentBuilderPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [activeTab, setActiveTab] = useState<RegistryType>("mcps");

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

  // Goal template sections
  const [goalSections, setGoalSections] = useState<GoalSection[]>([
    { id: generateId(), title: "", content: "" },
  ]);

  // Compute selected IDs for quick lookup
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

  async function handlePublish() {
    if (!name.trim()) {
      toast.error("Agent name is required");
      return;
    }

    setPublishing(true);
    try {
      const componentLinks: string[] = [];
      Object.values(selectedComponents).forEach((items) =>
        items.forEach((item) => componentLinks.push(item.id)),
      );

      const goal = goalSections
        .filter((s) => s.title || s.content)
        .reduce(
          (acc, section) => {
            if (section.title) {
              acc[section.title] = section.content;
            }
            return acc;
          },
          {} as Record<string, string>,
        );

      const body = {
        name: name.trim(),
        description: description.trim() || undefined,
        component_links: componentLinks.length > 0 ? componentLinks : undefined,
        goal: Object.keys(goal).length > 0 ? goal : undefined,
      };

      const created = await registry.create("agents", body);
      toast.success("Agent published to registry");
      router.push(`/agents/${created.id}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to publish agent";
      toast.error(msg);
    } finally {
      setPublishing(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Agent Builder"
        breadcrumbs={[
          { label: "Registry", href: "/" },
          { label: "Agents", href: "/agents" },
          { label: "Builder" },
        ]}
      />

      <div className="p-6 lg:p-8 max-w-[1400px]">
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
                  onChange={(e) => setName(e.target.value)}
                  className="max-w-md"
                  required
                />
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
                  this agent.
                </p>
              </div>

              <Tabs
                value={activeTab}
                onValueChange={(v) => setActiveTab(v as RegistryType)}
              >
                <TabsList>
                  {COMPONENT_TYPES.map((ct) => {
                    const count = (selectedComponents[ct.value] ?? []).length;
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

                    {/* Selected badges */}
                    {(selectedComponents[ct.value] ?? []).length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {(selectedComponents[ct.value] ?? []).map((item) => (
                          <Badge
                            key={item.id}
                            variant="secondary"
                            className="gap-1 pr-1"
                          >
                            {item.name}
                            <button
                              type="button"
                              onClick={() =>
                                removeComponent(ct.value, item.id)
                              }
                              className="ml-0.5 rounded-sm p-0.5 transition-colors hover:bg-foreground/10"
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </Badge>
                        ))}
                      </div>
                    )}
                  </TabsContent>
                ))}
              </Tabs>
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
                    Define the agent's objective in structured sections.
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
                {goalSections.map((section, i) => (
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
            <div className="animate-in stagger-3">
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
                Publish to Registry
              </Button>
            </div>
          </div>

          {/* Right column: Preview */}
          <aside className="w-full lg:w-1/3 animate-in stagger-1">
            <div className="sticky top-28 space-y-3">
              <h3 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
                Preview
              </h3>
              <Card>
                <CardContent className="p-0">
                  <PreviewPanel
                    name={name}
                    description={description}
                    selectedComponents={selectedComponents}
                    goalSections={goalSections}
                  />
                </CardContent>
              </Card>
            </div>
          </aside>
        </div>
      </div>
    </>
  );
}
