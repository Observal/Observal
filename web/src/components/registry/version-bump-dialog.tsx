// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useState, useMemo } from "react";
import { ArrowRight, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { VersionSuggestions } from "@/lib/types";

type BumpType = "patch" | "minor" | "major";

function bumpVersion(current: string, type: BumpType): string {
  const parts = current.split(".").map(Number);
  if (parts.length !== 3 || parts.some(isNaN)) return current;
  if (type === "major") return `${parts[0] + 1}.0.0`;
  if (type === "minor") return `${parts[0]}.${parts[1] + 1}.0`;
  return `${parts[0]}.${parts[1]}.${parts[2] + 1}`;
}

export { bumpVersion };

interface VersionBumpDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentVersion: string;
  suggestions: VersionSuggestions | undefined;
  onConfirm: (version: string) => void;
  publishing: boolean;
  title?: string;
  description?: string;
}

export function VersionBumpDialog({
  open,
  onOpenChange,
  currentVersion,
  suggestions,
  onConfirm,
  publishing,
  title = "Release New Version",
  description = "Choose how to bump the version for this release.",
}: VersionBumpDialogProps) {
  const [selection, setSelection] = useState<BumpType>("patch");

  const previewVersion = useMemo(() => {
    if (suggestions) return suggestions.suggestions[selection];
    return bumpVersion(currentVersion, selection);
  }, [currentVersion, selection, suggestions]);

  const options: { value: BumpType; label: string; description: string }[] =
    useMemo(
      () => [
        {
          value: "patch",
          label: "Patch",
          description: `${currentVersion} → ${suggestions?.suggestions.patch ?? bumpVersion(currentVersion, "patch")}`,
        },
        {
          value: "minor",
          label: "Minor",
          description: `${currentVersion} → ${suggestions?.suggestions.minor ?? bumpVersion(currentVersion, "minor")}`,
        },
        {
          value: "major",
          label: "Major",
          description: `${currentVersion} → ${suggestions?.suggestions.major ?? bumpVersion(currentVersion, "major")}`,
        },
      ],
      [currentVersion, suggestions],
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
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
                <span className="block font-mono text-xs text-muted-foreground">
                  {opt.description}
                </span>
              </span>
            </label>
          ))}
        </div>

        <div className="rounded-md bg-muted/50 px-4 py-2.5 text-center">
          <span className="text-xs text-muted-foreground">New version: </span>
          <span className="font-mono text-sm font-semibold">{previewVersion}</span>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={publishing}
          >
            Cancel
          </Button>
          <Button onClick={() => onConfirm(previewVersion)} disabled={publishing}>
            {publishing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <ArrowRight className="mr-2 h-4 w-4" />
            )}
            Release
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
