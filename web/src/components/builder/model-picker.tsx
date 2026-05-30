// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useMemo } from "react";

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
import { useModels } from "@/hooks/use-api";
import {
  IDE_DISPLAY_NAMES,
  type IdeName,
  getModelChoiceIdes,
} from "@/lib/ide-features";
import { annotateForDisplay, formatModel } from "@/lib/model-display";
import type { CatalogModel } from "@/lib/types";

const AUTO_VALUE = "__auto__";

function modelsForIde(catalog: CatalogModel[], ide: string): CatalogModel[] {
  return catalog.filter((m) => (m.supported_ides ?? []).includes(ide));
}

interface ModelPickerProps {
  /** The default model_id used when no per-IDE override is set. */
  modelName: string;
  onModelNameChange: (value: string) => void;
  /** Per-IDE overrides keyed by IDE name. */
  modelsByIde: Record<string, string>;
  onModelsByIdeChange: (next: Record<string, string>) => void;
  /** When false, hide the per-IDE overrides UI to keep the simple form simple. */
  showPerIdeOverrides?: boolean;
}

/**
 * Reusable model picker shared by the agent builder and the agent edit form.
 *
 * - Default model: a single ``Select`` against the live catalog.
 * - Per-IDE overrides: optional ``Select`` per IDE that ``accepts_model_choice``.
 *   Empty value = "auto" sentinel; the server will substitute the IDE's auto
 *   equivalent at install time and warn the user if the saved value is gone.
 */
export function ModelPicker({
  modelName,
  onModelNameChange,
  modelsByIde,
  onModelsByIdeChange,
  showPerIdeOverrides = true,
}: ModelPickerProps) {
  const { data: catalog, isLoading } = useModels();
  const models = useMemo(() => catalog?.models ?? [], [catalog]);
  const annotated = useMemo(() => annotateForDisplay(models), [models]);
  const idesWithChoice = useMemo(() => getModelChoiceIdes(), []);

  function renderSelect(
    value: string,
    onChange: (next: string) => void,
    rows: CatalogModel[],
    placeholder: string,
    {
      includeAuto,
      autoLabel,
    }: { includeAuto: boolean; autoLabel: string },
  ) {
    return (
      <Select
        value={value || AUTO_VALUE}
        onValueChange={(v) => onChange(v === AUTO_VALUE ? "" : v)}
      >
        <SelectTrigger>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {includeAuto && (
            <SelectGroup>
              <SelectItem value={AUTO_VALUE}>{autoLabel}</SelectItem>
            </SelectGroup>
          )}
          <SelectGroup>
            <SelectLabel>Models</SelectLabel>
            {rows.map((m) => {
              const fm = formatModel({
                display_name: m.display_name,
                model_id: m.model_id,
                release_date: m.release_date,
                disambiguate: true,
              });
              const label = fm.secondary
                ? `${fm.primary} (${fm.secondary})`
                : fm.primary;
              return (
                <SelectItem key={m.model_id} value={m.model_id}>
                  {label}
                  {m.deprecated ? " · deprecated" : ""}
                </SelectItem>
              );
            })}
          </SelectGroup>
        </SelectContent>
      </Select>
    );
  }

  const defaultRows = annotated;

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="agent-model" className="text-sm font-medium">
          Default model
        </Label>
        {renderSelect(
          modelName,
          onModelNameChange,
          defaultRows,
          isLoading ? "Loading models…" : "Select a default model",
          { includeAuto: true, autoLabel: "auto (let the IDE pick)" },
        )}
        <p className="text-xs text-muted-foreground">
          Used as the fallback for IDEs that accept a model choice and don&apos;t
          have an explicit override below.
        </p>
      </div>

      {showPerIdeOverrides && (
        <details className="rounded-md border border-border bg-muted/30 p-3">
          <summary className="cursor-pointer select-none text-xs font-medium text-muted-foreground">
            Per-IDE overrides{" "}
            {Object.keys(modelsByIde || {}).length > 0 ? (
              <span className="ml-1 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                {Object.keys(modelsByIde).length} set
              </span>
            ) : null}
          </summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {idesWithChoice.map((ide) => {
              const rows = modelsForIde(models, ide);
              const value = modelsByIde[ide] ?? "";
              return (
                <div key={ide} className="space-y-1.5">
                  <Label className="text-xs font-medium">
                    {IDE_DISPLAY_NAMES[ide as IdeName] ?? ide}
                  </Label>
                  {renderSelect(
                    value,
                    (next) => {
                      const copy: Record<string, string> = { ...modelsByIde };
                      if (!next) delete copy[ide];
                      else copy[ide] = next;
                      onModelsByIdeChange(copy);
                    },
                    rows,
                    isLoading ? "Loading…" : "Use default",
                    { includeAuto: true, autoLabel: "Use default" },
                  )}
                </div>
              );
            })}
          </div>
          {catalog?.degraded ? (
            <p className="mt-3 text-xs text-amber-700 dark:text-amber-400">
              Catalog is in degraded mode (offline snapshot). Saved selections
              will still install — admins can refresh from the diagnostics
              page.
            </p>
          ) : null}
        </details>
      )}
    </div>
  );
}
