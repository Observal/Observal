// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
//
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { Code2 } from "lucide-react";
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
import type { OutcomeCheck, OutcomeCheckType } from "@/lib/types";

const CHECK_TYPES: { value: OutcomeCheckType; label: string; hint: string }[] = [
  { value: "response_contains", label: "response_contains", hint: "Match the final user-facing response." },
  { value: "response_schema", label: "response_schema", hint: "Validate the final response against a JSON schema." },
  { value: "state_equals", label: "state_equals", hint: "End-state value of namespace.key equals expected." },
  { value: "state_changed", label: "state_changed", hint: "namespace.key transitioned from X to Y." },
  { value: "tool_was_called", label: "tool_was_called", hint: "A tool was invoked at least min_count times." },
  { value: "tool_result_contains", label: "tool_result_contains", hint: "A tool's output contains a pattern." },
  { value: "artifact_exists", label: "artifact_exists", hint: "A file matching path_pattern was written." },
  { value: "custom_python", label: "custom_python", hint: "Escape hatch — pure Python check." },
];

interface CheckEditorProps {
  value: OutcomeCheck;
  onChange: (next: OutcomeCheck) => void;
}

export function CheckEditor({ value, onChange }: CheckEditorProps) {
  function setParam(k: string, v: unknown) {
    onChange({ ...value, params: { ...value.params, [k]: v } });
  }

  function setCheckType(t: OutcomeCheckType) {
    // Reset params on type change to avoid leaking stale fields
    onChange({ check_type: t, params: defaultParamsFor(t) });
  }

  const hint = CHECK_TYPES.find((c) => c.value === value.check_type)?.hint;

  return (
    <div className="rounded-md border border-border bg-muted/20 p-3 space-y-3">
      <div>
        <Label className="text-xs text-muted-foreground">Check Type</Label>
        <Select value={value.check_type} onValueChange={(v) => setCheckType(v as OutcomeCheckType)}>
          <SelectTrigger className="font-[family-name:var(--font-mono)] text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CHECK_TYPES.map((c) => (
              <SelectItem key={c.value} value={c.value} className="font-[family-name:var(--font-mono)] text-xs">
                {c.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {hint && <p className="text-[11px] text-muted-foreground mt-1">{hint}</p>}
      </div>

      <div className="grid gap-2 md:grid-cols-2">
        {renderParamFields(value, setParam)}
      </div>
    </div>
  );
}

export function defaultParamsFor(t: OutcomeCheckType): Record<string, unknown> {
  switch (t) {
    case "response_contains":
      return { pattern: "", match_type: "substring" };
    case "response_schema":
      return { schema: { type: "object" } };
    case "state_equals":
      return { namespace: "", key: "", expected_value: "" };
    case "state_changed":
      return { namespace: "", key: "", from_value: "", to_value: "" };
    case "tool_was_called":
      return { tool_name: "", min_count: 1 };
    case "tool_result_contains":
      return { tool_name: "", pattern: "", match_type: "substring" };
    case "artifact_exists":
      return { path_pattern: "" };
    case "custom_python":
      return {
        function_path: "services.eval.spec_dag.custom_checks.",
        description: "",
      };
  }
}

function renderParamFields(
  check: OutcomeCheck,
  setParam: (k: string, v: unknown) => void
) {
  const { check_type: t, params } = check;
  switch (t) {
    case "response_contains":
    case "tool_result_contains":
      return (
        <>
          {t === "tool_result_contains" && (
            <Field label="tool_name">
              <Input
                value={String(params.tool_name ?? "")}
                onChange={(e) => setParam("tool_name", e.target.value)}
                className="font-[family-name:var(--font-mono)] text-sm"
              />
            </Field>
          )}
          <Field label="pattern" full>
            <Input
              value={String(params.pattern ?? "")}
              onChange={(e) => setParam("pattern", e.target.value)}
              className="font-[family-name:var(--font-mono)] text-sm"
            />
          </Field>
          <Field label="match_type">
            <Select
              value={String(params.match_type ?? "substring")}
              onValueChange={(v) => setParam("match_type", v)}
            >
              <SelectTrigger className="font-[family-name:var(--font-mono)] text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {["exact", "substring", "regex", "semantic"].map((m) => (
                  <SelectItem key={m} value={m} className="text-xs font-[family-name:var(--font-mono)]">
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {String(params.match_type) === "semantic" && (
            <Field label="threshold (0–1)">
              <Input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={Number(params.threshold ?? 0.85)}
                onChange={(e) => setParam("threshold", parseFloat(e.target.value))}
                className="font-[family-name:var(--font-mono)] text-sm"
              />
            </Field>
          )}
        </>
      );
    case "response_schema":
      return (
        <Field label="schema (JSON)" full>
          <JsonField
            value={params.schema}
            onChange={(v) => setParam("schema", v)}
          />
        </Field>
      );
    case "state_equals":
      return (
        <>
          <Field label="namespace">
            <Input
              value={String(params.namespace ?? "")}
              onChange={(e) => setParam("namespace", e.target.value)}
              className="font-[family-name:var(--font-mono)] text-sm"
            />
          </Field>
          <Field label="key">
            <Input
              value={String(params.key ?? "")}
              onChange={(e) => setParam("key", e.target.value)}
              className="font-[family-name:var(--font-mono)] text-sm"
            />
          </Field>
          <Field label="expected_value (string or JSON)" full>
            <Input
              value={String(params.expected_value ?? "")}
              onChange={(e) => setParam("expected_value", e.target.value)}
              className="font-[family-name:var(--font-mono)] text-sm"
            />
          </Field>
        </>
      );
    case "state_changed":
      return (
        <>
          <Field label="namespace">
            <Input
              value={String(params.namespace ?? "")}
              onChange={(e) => setParam("namespace", e.target.value)}
              className="font-[family-name:var(--font-mono)] text-sm"
            />
          </Field>
          <Field label="key">
            <Input
              value={String(params.key ?? "")}
              onChange={(e) => setParam("key", e.target.value)}
              className="font-[family-name:var(--font-mono)] text-sm"
            />
          </Field>
          <Field label="from_value">
            <Input
              value={String(params.from_value ?? "")}
              onChange={(e) => setParam("from_value", e.target.value)}
              className="font-[family-name:var(--font-mono)] text-sm"
            />
          </Field>
          <Field label="to_value">
            <Input
              value={String(params.to_value ?? "")}
              onChange={(e) => setParam("to_value", e.target.value)}
              className="font-[family-name:var(--font-mono)] text-sm"
            />
          </Field>
        </>
      );
    case "tool_was_called":
      return (
        <>
          <Field label="tool_name">
            <Input
              value={String(params.tool_name ?? "")}
              onChange={(e) => setParam("tool_name", e.target.value)}
              className="font-[family-name:var(--font-mono)] text-sm"
            />
          </Field>
          <Field label="min_count">
            <Input
              type="number"
              min={1}
              value={Number(params.min_count ?? 1)}
              onChange={(e) => setParam("min_count", parseInt(e.target.value || "1", 10))}
              className="font-[family-name:var(--font-mono)] text-sm"
            />
          </Field>
          <Field label="param_constraints (JSON object, optional)" full>
            <JsonField
              value={params.param_constraints ?? {}}
              onChange={(v) => setParam("param_constraints", v)}
              placeholder='{"order_id": "12345"}'
            />
          </Field>
        </>
      );
    case "artifact_exists":
      return (
        <>
          <Field label="path_pattern (glob or regex)" full>
            <Input
              value={String(params.path_pattern ?? "")}
              onChange={(e) => setParam("path_pattern", e.target.value)}
              placeholder="/tmp/*.py"
              className="font-[family-name:var(--font-mono)] text-sm"
            />
          </Field>
          <Field label="content_pattern (optional)" full>
            <Input
              value={String(params.content_pattern ?? "")}
              onChange={(e) =>
                setParam("content_pattern", e.target.value || undefined)
              }
              className="font-[family-name:var(--font-mono)] text-sm"
            />
          </Field>
        </>
      );
    case "custom_python":
      return (
        <>
          <Field label="function_path (must start with services.eval.spec_dag.custom_checks.)" full>
            <Input
              value={String(params.function_path ?? "")}
              onChange={(e) => setParam("function_path", e.target.value)}
              className="font-[family-name:var(--font-mono)] text-xs"
            />
          </Field>
          <Field label="description" full>
            <Input
              value={String(params.description ?? "")}
              onChange={(e) => setParam("description", e.target.value)}
              className="text-sm"
            />
          </Field>
        </>
      );
  }
}

function Field({
  label,
  children,
  full,
}: {
  label: string;
  children: React.ReactNode;
  full?: boolean;
}) {
  return (
    <div className={full ? "md:col-span-2" : undefined}>
      <Label className="text-xs text-muted-foreground flex items-center gap-1.5">
        <Code2 className="h-3 w-3" />
        {label}
      </Label>
      {children}
    </div>
  );
}

function JsonField({
  value,
  onChange,
  placeholder,
}: {
  value: unknown;
  onChange: (v: unknown) => void;
  placeholder?: string;
}) {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
  return (
    <Textarea
      value={text}
      onChange={(e) => {
        const v = e.target.value;
        try {
          onChange(JSON.parse(v));
        } catch {
          onChange(v); // keep raw text while user types invalid JSON
        }
      }}
      placeholder={placeholder ?? '{"key": "value"}'}
      rows={4}
      className="font-[family-name:var(--font-mono)] text-xs"
    />
  );
}
