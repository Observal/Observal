// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { cn } from "@/lib/utils";

// Status vocabulary from the mockup's --status-* tokens. Existing keys keep
// their colours; the additions cover live/visibility states the mockup defines.
// A dot marks states that describe a *current* condition; `ping` is reserved
// for states that are actively in progress.
const statusConfig: Record<string, { bg: string; text: string; dot?: string; ping?: boolean }> = {
  draft:     { bg: "bg-muted", text: "text-muted-foreground", dot: "bg-muted-foreground" },
  pending:   { bg: "bg-light-yellow", text: "text-dark-yellow", dot: "bg-dark-yellow" },
  approved:  { bg: "bg-light-green",  text: "text-dark-green",  dot: "bg-dark-green" },
  active:    { bg: "bg-light-green",  text: "text-dark-green",  dot: "bg-dark-green",  ping: true },
  rejected:  { bg: "bg-light-red",    text: "text-dark-red",    dot: "bg-dark-red" },
  inactive:  { bg: "bg-light-red",    text: "text-dark-red",    dot: "bg-dark-red" },
  failed:    { bg: "bg-light-red",    text: "text-dark-red",    dot: "bg-dark-red" },
  error:     { bg: "bg-light-red",    text: "text-dark-red",    dot: "bg-dark-red" },
  running:   { bg: "bg-light-blue",   text: "text-dark-blue",   dot: "bg-dark-blue",   ping: true },
  completed: { bg: "bg-light-green",  text: "text-dark-green",  dot: "bg-dark-green" },
  success:   { bg: "bg-light-green",  text: "text-dark-green",  dot: "bg-dark-green" },
  archived:  { bg: "bg-light-yellow", text: "text-dark-yellow", dot: "bg-dark-yellow" },
  deleted:   { bg: "bg-light-red",    text: "text-dark-red",    dot: "bg-dark-red" },

  // Live / health states
  live:      { bg: "bg-light-green",  text: "text-dark-green",  dot: "bg-dark-green",  ping: true },
  healthy:   { bg: "bg-light-green",  text: "text-dark-green",  dot: "bg-dark-green" },
  degraded:  { bg: "bg-light-yellow", text: "text-dark-yellow", dot: "bg-dark-yellow" },

  // Visibility states
  private:   { bg: "bg-muted",        text: "text-muted-foreground", dot: "bg-muted-foreground" },
  internal:  { bg: "bg-light-blue",   text: "text-dark-blue",   dot: "bg-dark-blue" },
  public:    { bg: "bg-light-blue",   text: "text-dark-blue",   dot: "bg-dark-blue" },
  team:      { bg: "bg-light-blue",   text: "text-dark-blue",   dot: "bg-dark-blue" },
  neutral:   { bg: "bg-muted",        text: "text-muted-foreground", dot: "bg-muted-foreground" },
};

const fallback = { bg: "bg-muted", text: "text-muted-foreground" };

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const s = statusConfig[status.toLowerCase()] ?? fallback;

  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-2xs font-medium", s.bg, s.text, className)}>
      {s.dot && (
        <span className="relative inline-flex h-1.5 w-1.5">
          {s.ping && (
            <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-75", s.dot)} />
          )}
          <span className={cn("relative inline-flex h-1.5 w-1.5 rounded-full", s.dot)} />
        </span>
      )}
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}
