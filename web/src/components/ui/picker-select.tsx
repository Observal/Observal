// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useMemo, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface PickerSelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface PickerSelectProps {
  value: string;
  onValueChange: (value: string) => void;
  options: PickerSelectOption[];
  placeholder?: string;
  emptyLabel?: string;
  disabled?: boolean;
  className?: string;
  inputClassName?: string;
}

export function PickerSelect({
  value,
  onValueChange,
  options,
  placeholder = "Select...",
  emptyLabel = "No matches",
  disabled,
  className,
  inputClassName,
}: PickerSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selected = options.find((option) => option.value === value);

  const filteredOptions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((option) => `${option.label} ${option.value}`.toLowerCase().includes(needle));
  }, [options, query]);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const choose = (next: string) => {
    onValueChange(next);
    setOpen(false);
  };
  const scrollList = filteredOptions.length > 12;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <div className={cn("relative", className)}>
          <Input
            value={open ? query : selected?.label ?? ""}
            onChange={(event) => {
              setQuery(event.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                const first = filteredOptions.find((option) => !option.disabled);
                if (first) choose(first.value);
              }
              if (event.key === "Escape") setOpen(false);
            }}
            placeholder={placeholder}
            disabled={disabled}
            className={cn("pr-9", inputClassName)}
          />
          <button
            type="button"
            onClick={() => setOpen((current) => !current)}
            disabled={disabled}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded text-muted-foreground hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
            aria-label="Show options"
          >
            <ChevronsUpDown className="h-3.5 w-3.5" />
          </button>
        </div>
      </PopoverAnchor>
      <PopoverContent
        align="start"
        className={cn(
          "w-[var(--radix-popover-trigger-width)] p-1",
          scrollList && "max-h-[min(24rem,var(--radix-popover-content-available-height))] overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        )}
      >
        {filteredOptions.length ? (
          filteredOptions.map((option) => (
            <button
              key={option.value}
              type="button"
              disabled={option.disabled}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(option.value)}
              className={cn(
                "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50",
                value === option.value && "bg-accent text-accent-foreground",
              )}
            >
              <Check className={cn("h-3.5 w-3.5", value === option.value ? "opacity-100" : "opacity-0")} />
              <span className="truncate">{option.label}</span>
            </button>
          ))
        ) : (
          <div className="px-2 py-3 text-xs text-muted-foreground">{emptyLabel}</div>
        )}
      </PopoverContent>
    </Popover>
  );
}
