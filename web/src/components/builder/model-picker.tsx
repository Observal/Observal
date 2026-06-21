// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useMemo } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useHarnesses } from "@/hooks/use-harnesses";

interface ModelPickerProps {
  modelName: string;
  onModelNameChange: (value: string) => void;
  modelsByHarness: Record<string, string>;
  onModelsByHarnessChange: (value: Record<string, string>) => void;
}

export function ModelPicker({
  modelName,
  onModelNameChange,
  modelsByHarness,
  onModelsByHarnessChange,
}: ModelPickerProps) {
  const { data: harnesses } = useHarnesses();
  const allHarnesses = useMemo(() => harnesses ?? [], [harnesses]);
  const allModels = Array.from(new Set(allHarnesses.flatMap((harness) => harness.supported_models ?? [])));
  const overrideCount = Object.keys(modelsByHarness).length;

  function setOverride(harness: string, value: string) {
    const next = { ...modelsByHarness };
    const trimmed = value.trim();
    if (trimmed) next[harness] = trimmed;
    else delete next[harness];
    onModelsByHarnessChange(next);
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="agent-default-model" className="text-sm font-medium">
          Default model
        </Label>
        <Input
          id="agent-default-model"
          value={modelName}
          onChange={(event) => onModelNameChange(event.target.value)}
          placeholder="auto (let the harness pick)"
          list="agent-default-models"
        />
        <datalist id="agent-default-models">
          {allModels.map((model) => <option key={model} value={model} />)}
        </datalist>
        <p className="text-xs text-muted-foreground">
          Used only when a harness override is blank. Leave blank to let each harness choose.
        </p>
      </div>

      {allHarnesses.length > 0 ? (
        <div className="space-y-3 rounded-md border border-border bg-muted/20 p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <Label className="text-sm font-medium">Harness override</Label>
              <p className="text-xs text-muted-foreground">
                Set the exact model value per harness. Suggestions come from the harness registry, but custom values are allowed.
              </p>
            </div>
            {overrideCount > 0 ? (
              <span className="rounded bg-primary/10 px-2 py-1 text-xs text-primary">
                {overrideCount} set
              </span>
            ) : null}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {allHarnesses.map((harness) => {
              const models = harness.supported_models ?? [];
              const listId = `agent-harness-models-${harness.name}`;
              return (
                <div key={harness.name} className="space-y-1.5">
                  <Label className="text-xs font-medium">{harness.display_name}</Label>
                  <Input
                    value={modelsByHarness[harness.name] ?? ""}
                    onChange={(event) => setOverride(harness.name, event.target.value)}
                    placeholder="Use default"
                    disabled={models.length === 0}
                    list={listId}
                  />
                  <datalist id={listId}>
                    {models.map((model) => <option key={model} value={model} />)}
                  </datalist>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
