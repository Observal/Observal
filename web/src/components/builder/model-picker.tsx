// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, X } from "lucide-react";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useModels } from "@/hooks/use-api";
import { annotateForDisplay, formatModel } from "@/lib/model-display";
import { cn } from "@/lib/utils";

interface ModelPickerProps {
  modelName: string;
  onModelNameChange: (value: string) => void;
}

export function ModelPicker({
  modelName,
  onModelNameChange,
}: ModelPickerProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [inputValue, setInputValue] = useState(modelName);
  const { data: catalog, isLoading } = useModels();
  const models = useMemo(() => catalog?.models ?? [], [catalog]);
  const rows = useMemo(() => annotateForDisplay(models), [models]);

  useEffect(() => {
    setInputValue(modelName);
  }, [modelName]);

  const filtered = useMemo(() => {
    const q = inputValue.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((m) =>
      [m.model_id, m.display_name, m.provider, m.family]
        .filter(Boolean)
        .some((v) => v.toLowerCase().includes(q)),
    );
  }, [inputValue, rows]);

  function labelForModel(m: (typeof rows)[number]) {
    const fm = formatModel({
      display_name: m.display_name,
      model_id: m.model_id,
      release_date: m.release_date,
      disambiguate: true,
    });
    return fm.secondary ? `${fm.primary} (${fm.secondary})` : fm.primary;
  }

  function commit(value: string) {
    setInputValue(value);
    onModelNameChange(value);
  }

  function handleBlur() {
    setTimeout(() => {
      if (inputValue !== modelName) onModelNameChange(inputValue);
      setOpen(false);
    }, 150);
  }

  return (
    <div className="space-y-2">
      <Label htmlFor={inputId} className="text-sm font-medium">
        Default model
      </Label>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <div className="relative">
            <input
              ref={inputRef}
              id={inputId}
              type="text"
              placeholder={isLoading ? "Loading models…" : "auto (let the IDE pick)"}
              value={inputValue}
              onChange={(e) => {
                setInputValue(e.target.value);
                if (!open) setOpen(true);
              }}
              onFocus={() => setOpen(true)}
              onBlur={handleBlur}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commit(inputValue);
                  setOpen(false);
                }
                if (e.key === "Escape") setOpen(false);
              }}
              className={cn(
                "flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm transition-colors",
                "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                "pr-16",
              )}
            />
            <div className="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center gap-0.5">
              {inputValue ? (
                <button
                  type="button"
                  className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  onClick={() => {
                    commit("");
                    inputRef.current?.focus();
                  }}
                  tabIndex={-1}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              ) : null}
              <button
                type="button"
                className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                onClick={() => {
                  setOpen((v) => !v);
                  inputRef.current?.focus();
                }}
                tabIndex={-1}
              >
                <ChevronDown className="h-4 w-4" />
              </button>
            </div>
          </div>
        </PopoverTrigger>
        <PopoverContent
          className="w-[var(--radix-popover-trigger-width)] p-0"
          align="start"
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          <Command shouldFilter={false}>
            <CommandList>
              <CommandEmpty>
                {inputValue ? (
                  <span className="text-xs text-muted-foreground">
                    Press Enter to use <span className="font-mono font-medium">{inputValue}</span>
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">Type a model ID or choose from the catalog</span>
                )}
              </CommandEmpty>
              <CommandGroup heading="Default">
                <CommandItem
                  value="auto"
                  onSelect={() => {
                    commit("");
                    setOpen(false);
                  }}
                  onMouseDown={(e) => e.preventDefault()}
                >
                  <Check className={cn("mr-2 h-3.5 w-3.5", modelName ? "opacity-0" : "opacity-100")} />
                  <span>auto (let the IDE pick)</span>
                </CommandItem>
              </CommandGroup>
              {filtered.length > 0 ? (
                <CommandGroup heading="Models">
                  {filtered.slice(0, 100).map((m) => (
                    <CommandItem
                      key={m.model_id}
                      value={m.model_id}
                      onSelect={() => {
                        commit(m.model_id);
                        setOpen(false);
                      }}
                      onMouseDown={(e) => e.preventDefault()}
                    >
                      <Check
                        className={cn(
                          "mr-2 h-3.5 w-3.5 shrink-0",
                          modelName === m.model_id ? "opacity-100" : "opacity-0",
                        )}
                      />
                      <div className="min-w-0">
                        <div className="truncate text-sm">
                          {labelForModel(m)}{m.deprecated ? " · deprecated" : ""}
                        </div>
                        <div className="truncate font-mono text-xs text-muted-foreground">
                          {m.model_id}
                        </div>
                      </div>
                    </CommandItem>
                  ))}
                </CommandGroup>
              ) : null}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      <p className="text-xs text-muted-foreground">
        Pick from the models.dev catalog or type any model ID. Leave blank to let
        the IDE choose.
      </p>
      {catalog?.degraded ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          Catalog is using the offline snapshot. Typed model IDs still save.
        </p>
      ) : null}
    </div>
  );
}
