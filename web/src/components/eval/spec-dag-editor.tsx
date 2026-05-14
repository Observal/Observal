// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
//
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { useMemo, useState } from "react";
import {
  Ban,
  CheckCircle2,
  ClipboardCopy,
  Eye,
  ListChecks,
  Plus,
  ShieldOff,
  Sparkles,
  Target,
  Trash2,
  Wand2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { useRegisterSpecDag } from "@/hooks/use-api";
import { toast } from "sonner";
import {
  CheckEditor,
  defaultParamsFor,
} from "@/components/eval/check-editor";
import type {
  DomainInvariant,
  InvariantSeverity,
  OutcomeAssertion,
  OutcomeCheck,
  SpecDagV2Payload,
  SpecSource,
  StepConstraint,
  StepSeverity,
} from "@/lib/types";

const SOURCES: SpecSource[] = ["hand_authored", "mined", "llm_inferred"];

function blankAssertion(id = ""): OutcomeAssertion {
  return {
    assertion_id: id,
    description: "",
    check: { check_type: "response_contains", params: defaultParamsFor("response_contains") },
    weight: 1.0,
    required: true,
  };
}

function blankConstraint(id = ""): StepConstraint {
  return {
    constraint_id: id,
    description: "",
    before_tool: "",
    after_tool: "",
    weight: 1.0,
    severity: "soft",
  };
}

function blankInvariant(id = ""): DomainInvariant {
  return {
    invariant_id: id,
    description: "",
    check: { check_type: "tool_was_called", params: defaultParamsFor("tool_was_called") },
    severity: "major",
  };
}

export function SpecDagEditor() {
  const [taskType, setTaskType] = useState("cancel_order");
  const [version, setVersion] = useState("1");
  const [source, setSource] = useState<SpecSource>("hand_authored");

  const [assertions, setAssertions] = useState<OutcomeAssertion[]>([
    {
      assertion_id: "order_cancelled",
      description: "order 12345 status is cancelled",
      check: {
        check_type: "tool_was_called",
        params: {
          tool_name: "update_order",
          min_count: 1,
          param_constraints: { order_id: "12345", status: "cancelled" },
        },
      },
      weight: 1.0,
      required: true,
    },
    {
      assertion_id: "user_notified",
      description: "response confirms cancellation",
      check: {
        check_type: "response_contains",
        params: { pattern: "cancelled", match_type: "substring" },
      },
      weight: 0.5,
      required: false,
    },
  ]);

  const [constraints, setConstraints] = useState<StepConstraint[]>([]);
  const [invariants, setInvariants] = useState<DomainInvariant[]>([]);

  const register = useRegisterSpecDag();

  const payload: SpecDagV2Payload = useMemo(
    () => ({
      schema_version: 2,
      task_type: taskType,
      version,
      source,
      outcome_assertions: assertions,
      step_constraints: constraints,
      domain_invariants: invariants,
    }),
    [taskType, version, source, assertions, constraints, invariants]
  );

  const issues = useMemo(() => validate(payload), [payload]);
  const canSubmit =
    issues.length === 0 && taskType.trim() && version.trim() && assertions.length > 0;

  function addAssertion() {
    setAssertions((prev) => [...prev, blankAssertion(`assertion_${prev.length + 1}`)]);
  }
  function removeAssertion(i: number) {
    setAssertions((prev) => prev.filter((_, k) => k !== i));
  }
  function setAssertion(i: number, fn: (a: OutcomeAssertion) => OutcomeAssertion) {
    setAssertions((prev) => prev.map((a, k) => (k === i ? fn(a) : a)));
  }

  function addConstraint() {
    setConstraints((prev) => [...prev, blankConstraint(`constraint_${prev.length + 1}`)]);
  }
  function removeConstraint(i: number) {
    setConstraints((prev) => prev.filter((_, k) => k !== i));
  }
  function setConstraint(i: number, fn: (c: StepConstraint) => StepConstraint) {
    setConstraints((prev) => prev.map((c, k) => (k === i ? fn(c) : c)));
  }

  function addInvariant() {
    setInvariants((prev) => [...prev, blankInvariant(`invariant_${prev.length + 1}`)]);
  }
  function removeInvariant(i: number) {
    setInvariants((prev) => prev.filter((_, k) => k !== i));
  }
  function setInvariant(i: number, fn: (d: DomainInvariant) => DomainInvariant) {
    setInvariants((prev) => prev.map((d, k) => (k === i ? fn(d) : d)));
  }

  async function handleRegister() {
    try {
      await register.mutateAsync(payload);
    } catch {
      // toast in hook
    }
  }

  function copyJson() {
    void navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    toast.success("Copied JSON to clipboard");
  }

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-[1fr_460px] gap-4">
      {/* ── Editor ── */}
      <div className="flex min-h-0 flex-col gap-4">
        {/* Header card */}
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="rounded-md bg-primary-accent/10 p-2 text-primary-accent">
                <Sparkles className="h-4 w-4" />
              </div>
              <div>
                <h2 className="text-base font-[family-name:var(--font-display)] font-semibold">
                  Spec DAG Authoring
                  <span className="ml-2 rounded-sm bg-muted px-1.5 py-0.5 text-[10px] font-[family-name:var(--font-mono)] text-muted-foreground">
                    v2 · outcome-oriented
                  </span>
                </h2>
                <p className="text-xs text-muted-foreground">
                  Don&apos;t spec the path. Spec what success looks like.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={copyJson}>
                <ClipboardCopy className="h-3.5 w-3.5 mr-1.5" />
                Copy JSON
              </Button>
              <Button
                size="sm"
                disabled={!canSubmit || register.isPending}
                onClick={handleRegister}
              >
                {register.isPending ? "Registering…" : "Register Version"}
              </Button>
            </div>
          </div>
          <Separator className="my-4" />
          <div className="grid gap-3 md:grid-cols-3">
            <div>
              <Label className="text-xs text-muted-foreground">Task Type</Label>
              <Input
                value={taskType}
                onChange={(e) => setTaskType(e.target.value)}
                placeholder="e.g. cancel_order"
                className="font-[family-name:var(--font-mono)] text-sm"
              />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Version</Label>
              <Input
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="1"
                className="font-[family-name:var(--font-mono)] text-sm"
              />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Source</Label>
              <Select value={source} onValueChange={(v) => setSource(v as SpecSource)}>
                <SelectTrigger className="font-[family-name:var(--font-mono)] text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SOURCES.map((s) => (
                    <SelectItem key={s} value={s} className="font-[family-name:var(--font-mono)] text-xs">
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        <Tabs defaultValue="outcomes" className="flex min-h-0 flex-1 flex-col">
          <TabsList className="self-start">
            <TabsTrigger value="outcomes" className="gap-1.5">
              <Target className="h-3.5 w-3.5" />
              Outcomes <span className="text-xs text-muted-foreground">({assertions.length})</span>
            </TabsTrigger>
            <TabsTrigger value="constraints" className="gap-1.5">
              <ListChecks className="h-3.5 w-3.5" />
              Step Constraints <span className="text-xs text-muted-foreground">({constraints.length})</span>
            </TabsTrigger>
            <TabsTrigger value="invariants" className="gap-1.5">
              <ShieldOff className="h-3.5 w-3.5" />
              Domain Invariants <span className="text-xs text-muted-foreground">({invariants.length})</span>
            </TabsTrigger>
          </TabsList>

          {/* Outcome Assertions */}
          <TabsContent value="outcomes" className="mt-3 flex-1 overflow-y-auto">
            <div className="flex flex-col gap-3">
              {assertions.map((a, idx) => (
                <div key={idx} className="rounded-lg border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 grid grid-cols-1 md:grid-cols-[1fr_120px_auto] gap-3 items-end">
                      <div>
                        <Label className="text-xs text-muted-foreground">Assertion ID</Label>
                        <Input
                          value={a.assertion_id}
                          onChange={(e) =>
                            setAssertion(idx, (p) => ({ ...p, assertion_id: e.target.value }))
                          }
                          className="font-[family-name:var(--font-mono)] text-sm"
                        />
                      </div>
                      <div>
                        <Label className="text-xs text-muted-foreground">Weight</Label>
                        <Input
                          type="number"
                          min={0}
                          step="0.5"
                          value={a.weight}
                          onChange={(e) =>
                            setAssertion(idx, (p) => ({ ...p, weight: parseFloat(e.target.value || "0") }))
                          }
                          className="font-[family-name:var(--font-mono)] text-sm"
                        />
                      </div>
                      <label className="flex items-center gap-2 text-xs text-muted-foreground select-none cursor-pointer pb-2">
                        <Switch
                          checked={a.required}
                          onCheckedChange={(v) => setAssertion(idx, (p) => ({ ...p, required: v }))}
                        />
                        <span>required</span>
                      </label>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="opacity-50 hover:opacity-100 hover:text-destructive"
                      onClick={() => removeAssertion(idx)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                  <div className="mt-3">
                    <Label className="text-xs text-muted-foreground">Description</Label>
                    <Input
                      value={a.description ?? ""}
                      onChange={(e) =>
                        setAssertion(idx, (p) => ({ ...p, description: e.target.value }))
                      }
                      placeholder="What end-state is being asserted"
                      className="text-sm"
                    />
                  </div>
                  <div className="mt-3">
                    <CheckEditor
                      value={a.check}
                      onChange={(c: OutcomeCheck) => setAssertion(idx, (p) => ({ ...p, check: c }))}
                    />
                  </div>
                </div>
              ))}
              <Button variant="outline" onClick={addAssertion} className="self-start">
                <Plus className="h-3.5 w-3.5 mr-1.5" /> Add Outcome Assertion
              </Button>
            </div>
          </TabsContent>

          {/* Step Constraints */}
          <TabsContent value="constraints" className="mt-3 flex-1 overflow-y-auto">
            <div className="rounded-lg border border-border bg-card p-3 mb-3 text-xs text-muted-foreground flex items-start gap-2">
              <ListChecks className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
              <p>
                Safety-critical ordering only. Most specs should have <em>zero</em> of these.
                Soft severity warns; hard severity reduces the correctness score.
              </p>
            </div>
            <div className="flex flex-col gap-3">
              {constraints.map((c, idx) => (
                <div key={idx} className="rounded-lg border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 grid grid-cols-1 md:grid-cols-[1fr_1fr_1fr_120px_120px] gap-3 items-end">
                      <Field label="Constraint ID">
                        <Input
                          value={c.constraint_id}
                          onChange={(e) => setConstraint(idx, (p) => ({ ...p, constraint_id: e.target.value }))}
                          className="font-[family-name:var(--font-mono)] text-sm"
                        />
                      </Field>
                      <Field label="Before Tool">
                        <Input
                          value={c.before_tool}
                          onChange={(e) => setConstraint(idx, (p) => ({ ...p, before_tool: e.target.value }))}
                          placeholder="verify_identity"
                          className="font-[family-name:var(--font-mono)] text-sm"
                        />
                      </Field>
                      <Field label="After Tool">
                        <Input
                          value={c.after_tool}
                          onChange={(e) => setConstraint(idx, (p) => ({ ...p, after_tool: e.target.value }))}
                          placeholder="update_account"
                          className="font-[family-name:var(--font-mono)] text-sm"
                        />
                      </Field>
                      <Field label="Severity">
                        <Select
                          value={c.severity}
                          onValueChange={(v) =>
                            setConstraint(idx, (p) => ({ ...p, severity: v as StepSeverity }))
                          }
                        >
                          <SelectTrigger className="text-sm font-[family-name:var(--font-mono)]">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="soft" className="text-xs font-[family-name:var(--font-mono)]">
                              soft
                            </SelectItem>
                            <SelectItem value="hard" className="text-xs font-[family-name:var(--font-mono)]">
                              hard
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      </Field>
                      <Field label="Weight">
                        <Input
                          type="number"
                          min={0}
                          step="0.5"
                          value={c.weight}
                          onChange={(e) =>
                            setConstraint(idx, (p) => ({ ...p, weight: parseFloat(e.target.value || "0") }))
                          }
                          className="font-[family-name:var(--font-mono)] text-sm"
                        />
                      </Field>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="opacity-50 hover:opacity-100 hover:text-destructive"
                      onClick={() => removeConstraint(idx)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                  <div className="mt-3">
                    <Label className="text-xs text-muted-foreground">Description</Label>
                    <Input
                      value={c.description ?? ""}
                      onChange={(e) =>
                        setConstraint(idx, (p) => ({ ...p, description: e.target.value }))
                      }
                      placeholder="must verify identity before modifying account"
                      className="text-sm"
                    />
                  </div>
                </div>
              ))}
              <Button variant="outline" onClick={addConstraint} className="self-start">
                <Plus className="h-3.5 w-3.5 mr-1.5" /> Add Step Constraint
              </Button>
            </div>
          </TabsContent>

          {/* Domain Invariants */}
          <TabsContent value="invariants" className="mt-3 flex-1 overflow-y-auto">
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 mb-3 text-xs flex items-start gap-2">
              <Ban className="h-3.5 w-3.5 mt-0.5 flex-shrink-0 text-destructive" />
              <p className="text-muted-foreground">
                Domain-level safety rules. <strong>Critical</strong> severity zeros the correctness score on violation.
                <strong> Major</strong> hits the safety category only. The check is interpreted as the negative
                condition — if it &ldquo;passes&rdquo; (e.g. the forbidden tool <em>was</em> called), the invariant is violated.
              </p>
            </div>
            <div className="flex flex-col gap-3">
              {invariants.map((inv, idx) => (
                <div key={idx} className="rounded-lg border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 grid grid-cols-1 md:grid-cols-[1fr_140px] gap-3 items-end">
                      <Field label="Invariant ID">
                        <Input
                          value={inv.invariant_id}
                          onChange={(e) => setInvariant(idx, (p) => ({ ...p, invariant_id: e.target.value }))}
                          className="font-[family-name:var(--font-mono)] text-sm"
                        />
                      </Field>
                      <Field label="Severity">
                        <Select
                          value={inv.severity}
                          onValueChange={(v) =>
                            setInvariant(idx, (p) => ({ ...p, severity: v as InvariantSeverity }))
                          }
                        >
                          <SelectTrigger className="text-sm font-[family-name:var(--font-mono)]">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="major" className="text-xs font-[family-name:var(--font-mono)]">
                              major
                            </SelectItem>
                            <SelectItem value="critical" className="text-xs font-[family-name:var(--font-mono)]">
                              critical
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      </Field>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="opacity-50 hover:opacity-100 hover:text-destructive"
                      onClick={() => removeInvariant(idx)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                  <div className="mt-3">
                    <Label className="text-xs text-muted-foreground">Description</Label>
                    <Input
                      value={inv.description ?? ""}
                      onChange={(e) =>
                        setInvariant(idx, (p) => ({ ...p, description: e.target.value }))
                      }
                      placeholder="never call delete_production_data"
                      className="text-sm"
                    />
                  </div>
                  <div className="mt-3">
                    <CheckEditor
                      value={inv.check}
                      onChange={(c: OutcomeCheck) => setInvariant(idx, (p) => ({ ...p, check: c }))}
                    />
                  </div>
                </div>
              ))}
              <Button variant="outline" onClick={addInvariant} className="self-start">
                <Plus className="h-3.5 w-3.5 mr-1.5" /> Add Domain Invariant
              </Button>
            </div>
          </TabsContent>
        </Tabs>
      </div>

      {/* ── Live preview ── */}
      <aside className="flex min-h-0 flex-col rounded-lg border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Eye className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold">Live Preview</h3>
          </div>
          <span
            className={
              "text-xs font-[family-name:var(--font-mono)] px-2 py-0.5 rounded-sm " +
              (issues.length === 0
                ? "bg-success/15 text-success"
                : "bg-destructive/15 text-destructive")
            }
          >
            {issues.length === 0 ? "valid" : `${issues.length} issue${issues.length === 1 ? "" : "s"}`}
          </span>
        </div>
        {issues.length > 0 && (
          <div className="border-b border-border px-4 py-2 bg-destructive/5 space-y-1">
            {issues.map((m, i) => (
              <div key={i} className="text-xs text-destructive flex items-start gap-1.5">
                <Wand2 className="h-3 w-3 mt-0.5 flex-shrink-0" />
                <span>{m}</span>
              </div>
            ))}
          </div>
        )}
        <div className="grid grid-cols-3 gap-px bg-border text-center">
          <Stat label="Outcomes" value={assertions.length} icon={Target} />
          <Stat label="Constraints" value={constraints.length} icon={ListChecks} />
          <Stat
            label="Invariants"
            value={invariants.length}
            icon={CheckCircle2}
          />
        </div>
        <div className="flex-1 overflow-auto p-4">
          <pre className="text-[11px] font-[family-name:var(--font-mono)] leading-relaxed whitespace-pre-wrap break-all text-muted-foreground">
{JSON.stringify(payload, null, 2)}
          </pre>
        </div>
      </aside>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function Stat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="bg-card px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground flex items-center justify-center gap-1">
        <Icon className="h-3 w-3" />
        {label}
      </div>
      <div className="text-base font-[family-name:var(--font-mono)] tabular-nums">{value}</div>
    </div>
  );
}

function validate(payload: SpecDagV2Payload): string[] {
  const issues: string[] = [];
  if (!payload.task_type.trim()) issues.push("task_type is required");
  if (!payload.version.trim()) issues.push("version is required");
  if (payload.outcome_assertions.length === 0)
    issues.push("at least one outcome assertion is required");

  const aIds = new Set<string>();
  for (const a of payload.outcome_assertions) {
    if (!a.assertion_id.trim()) issues.push("every assertion needs an id");
    if (aIds.has(a.assertion_id)) issues.push(`duplicate assertion id: ${a.assertion_id}`);
    aIds.add(a.assertion_id);
    if (a.weight < 0) issues.push(`assertion ${a.assertion_id} has negative weight`);
    const ct = a.check.check_type;
    if (ct === "tool_was_called" && !String(a.check.params.tool_name ?? "").trim())
      issues.push(`assertion ${a.assertion_id}: tool_name required`);
    if (
      (ct === "response_contains" || ct === "tool_result_contains") &&
      !String(a.check.params.pattern ?? "").trim()
    )
      issues.push(`assertion ${a.assertion_id}: pattern required`);
    if (ct === "artifact_exists" && !String(a.check.params.path_pattern ?? "").trim())
      issues.push(`assertion ${a.assertion_id}: path_pattern required`);
    if (ct === "custom_python") {
      const fp = String(a.check.params.function_path ?? "");
      if (!fp.startsWith("services.eval.spec_dag.custom_checks."))
        issues.push(`assertion ${a.assertion_id}: function_path must start with services.eval.spec_dag.custom_checks.`);
    }
  }

  for (const c of payload.step_constraints) {
    if (!c.constraint_id.trim()) issues.push("every step constraint needs an id");
    if (!c.before_tool.trim() || !c.after_tool.trim())
      issues.push(`constraint ${c.constraint_id}: before_tool and after_tool required`);
    if (c.before_tool === c.after_tool && c.before_tool)
      issues.push(`constraint ${c.constraint_id} is a self-loop`);
  }

  for (const inv of payload.domain_invariants) {
    if (!inv.invariant_id.trim()) issues.push("every domain invariant needs an id");
  }
  return issues;
}
