// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0


import { useMemo } from "react";
import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { PickerSelect } from "@/components/ui/picker-select";
import type { AgentVersionSummary } from "@/lib/types";

interface VersionDropdownProps {
  versions: AgentVersionSummary[];
  currentVersion: string;
  onSelect: (version: string) => void;
}

/** Compare two semver strings (descending). Falls back to string compare. */
function semverCompareDesc(a: string, b: string): number {
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  for (let i = 0; i < 3; i++) {
    const diff = (pb[i] ?? 0) - (pa[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

export function VersionDropdown({ versions, currentVersion, onSelect }: VersionDropdownProps) {
  const approvedVersions = useMemo(
    () =>
      versions
        .filter((v) => v.status === "approved")
        .sort((a, b) => semverCompareDesc(a.version, b.version)),
    [versions]
  );

  const latestApproved = approvedVersions[0]?.version;
  const isOlderVersion = currentVersion && latestApproved && currentVersion !== latestApproved;

  if (approvedVersions.length <= 1) {
    return (
      <Badge variant="secondary" className="text-xs">
        v{currentVersion || approvedVersions[0]?.version || "—"}
      </Badge>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <PickerSelect
        value={currentVersion}
        onValueChange={onSelect}
        placeholder="Version"
        className="w-[140px]"
        inputClassName="h-7 text-xs"
        options={approvedVersions.map((v) => ({
          value: v.version,
          label: v.version === latestApproved ? `v${v.version} latest` : `v${v.version}`,
        }))}
      />
      {isOlderVersion && (
        <span className="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
          <AlertTriangle className="h-3 w-3" />
          Not the latest version
        </span>
      )}
    </div>
  );
}
