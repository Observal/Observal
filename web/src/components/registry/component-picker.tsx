// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useMemo, useState } from "react";
import { Loader2, Plus, Search } from "lucide-react";
import type { RegistryItem } from "@/lib/types";
import type { RegistryType } from "@/lib/api";
import { useRegistryList } from "@/hooks/use-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function ComponentPicker({
  type,
  label,
  selected,
  onToggle,
  onCreateNew,
}: {
  type: RegistryType;
  label?: string;
  selected: Set<string>;
  onToggle: (item: RegistryItem) => void;
  onCreateNew?: () => void;
}) {
  const { data: items, isLoading } = useRegistryList(type);
  const [search, setSearch] = useState("");
  const searchLabel = label ?? type;

  const filtered = useMemo(() => {
    if (!items) return [];
    if (!search) return items;
    const query = search.toLowerCase();
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(query) ||
        (item.description?.toLowerCase().includes(query) ?? false),
    );
  }, [items, search]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={`Search ${searchLabel}...`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 pl-9 text-sm"
          />
        </div>
        {onCreateNew && (
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
        )}
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
