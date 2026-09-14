// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { cn } from "@/lib/utils";

// Registry status labels use the same simple pill treatment as teamspace
// visibility labels. Meaning is always carried by the text, not a separate dot.
const statusConfig: Record<string, { bg: string; text: string }> = {
  draft: { bg: "bg-muted", text: "text-muted-foreground" },
  pending: { bg: "bg-light-yellow", text: "text-dark-yellow" },
  approved: { bg: "bg-light-green", text: "text-dark-green" },
  active: { bg: "bg-light-green", text: "text-dark-green" },
  rejected: { bg: "bg-light-red", text: "text-dark-red" },
  inactive: { bg: "bg-light-red", text: "text-dark-red" },
  failed: { bg: "bg-light-red", text: "text-dark-red" },
  error: { bg: "bg-light-red", text: "text-dark-red" },
  running: { bg: "bg-light-blue", text: "text-dark-blue" },
  completed: { bg: "bg-light-green", text: "text-dark-green" },
  success: { bg: "bg-light-green", text: "text-dark-green" },
  archived: { bg: "bg-light-yellow", text: "text-dark-yellow" },
  deleted: { bg: "bg-light-red", text: "text-dark-red" },
  live: { bg: "bg-light-green", text: "text-dark-green" },
  healthy: { bg: "bg-light-green", text: "text-dark-green" },
  degraded: { bg: "bg-light-yellow", text: "text-dark-yellow" },
  private: { bg: "bg-light-yellow", text: "text-dark-yellow" },
  internal: { bg: "bg-light-green", text: "text-dark-green" },
  public: { bg: "bg-primary-accent/15", text: "text-primary-accent" },
  team: { bg: "bg-light-blue", text: "text-dark-blue" },
  neutral: { bg: "bg-muted", text: "text-muted-foreground" },
};

const fallback = { bg: "bg-muted", text: "text-muted-foreground" };

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const style = statusConfig[status.toLowerCase()] ?? fallback;

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-2xs font-medium",
        style.bg,
        style.text,
        className,
      )}
    >
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}
