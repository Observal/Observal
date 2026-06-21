// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useEffect, useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useIdes } from "@/hooks/use-ides";

interface ModelPickerProps {
  modelName: string;
  onModelNameChange: (value: string) => void;
  modelsByIde: Record<string, string>;
  onModelsByIdeChange: (value: Record<string, string>) => void;
}

export function ModelPicker({
  modelName,
  onModelNameChange,
  modelsByIde,
  onModelsByIdeChange,
}: ModelPickerProps) {
  const { data: ides, defaultIde } = useIdes();
  const allIdes = useMemo(() => ides ?? [], [ides]);
  const [selectedIde, setSelectedIde] = useState("");

  useEffect(() => {
    if (allIdes.length === 0) return;
    const fallback = defaultIde && allIdes.some((ide) => ide.name === defaultIde)
      ? defaultIde
      : allIdes[0].name;
    if (!selectedIde || !allIdes.some((ide) => ide.name === selectedIde)) {
      setSelectedIde(fallback);
    }
  }, [allIdes, defaultIde, selectedIde]);

  const selectedIdeMeta = allIdes.find((ide) => ide.name === selectedIde);
  const overrideCount = Object.keys(modelsByIde).length;

  function setOverride(ide: string, value: string) {
    if (!ide) return;
    const next = { ...modelsByIde };
    const trimmed = value.trim();
    if (trimmed) next[ide] = trimmed;
    else delete next[ide];
    onModelsByIdeChange(next);
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
          placeholder="auto (let the IDE pick)"
        />
        <p className="text-xs text-muted-foreground">
          Type the model value that your target harness accepts. Leave blank to let the IDE choose.
        </p>
      </div>

      {allIdes.length > 0 ? (
        <div className="space-y-3 rounded-md border border-border bg-muted/20 p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <Label className="text-sm font-medium">Per harness override</Label>
              <p className="text-xs text-muted-foreground">
                Pick any supported harness, then enter the exact model value that harness accepts.
              </p>
            </div>
            {overrideCount > 0 ? (
              <span className="rounded bg-primary/10 px-2 py-1 text-xs text-primary">
                {overrideCount} set
              </span>
            ) : null}
          </div>

          <div className="grid gap-3 md:grid-cols-[minmax(160px,220px)_1fr]">
            <Select value={selectedIde} onValueChange={setSelectedIde}>
              <SelectTrigger className="h-10">
                <SelectValue placeholder="Select harness" />
              </SelectTrigger>
              <SelectContent>
                {allIdes.map((ide) => (
                  <SelectItem key={ide.name} value={ide.name}>
                    {ide.display_name}
                    {!ide.accepts_model_choice ? " · no model setting" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={modelsByIde[selectedIde] ?? ""}
              onChange={(event) => setOverride(selectedIde, event.target.value)}
              placeholder={selectedIdeMeta ? `Use default for ${selectedIdeMeta.display_name}` : "Use default"}
              disabled={!selectedIdeMeta?.accepts_model_choice}
            />
          </div>

          {selectedIdeMeta && !selectedIdeMeta.accepts_model_choice ? (
            <p className="text-xs text-muted-foreground">
              {selectedIdeMeta.display_name} does not accept a saved model choice. It is shown here because it is an available harness.
            </p>
          ) : null}

          {overrideCount > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(modelsByIde).map(([ide, model]) => {
                const label = allIdes.find((item) => item.name === ide)?.display_name ?? ide;
                return (
                  <button
                    key={ide}
                    type="button"
                    className="rounded bg-primary/10 px-2 py-1 text-left text-xs text-primary hover:bg-primary/15"
                    onClick={() => setSelectedIde(ide)}
                  >
                    {label}: <span className="font-mono">{model}</span>
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
