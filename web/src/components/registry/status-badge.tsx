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

  // Inbox states. `open` pings because it is the bucket still awaiting the
  // user; "action required" and "unread" are the two cues the inbox list needs
  // to state in words rather than leaving to a coloured dot alone.
  open:              { bg: "bg-light-blue",   text: "text-dark-blue",   dot: "bg-dark-blue" },
  done:              { bg: "bg-light-green",  text: "text-dark-green",  dot: "bg-dark-green" },
  dismissed:         { bg: "bg-muted",        text: "text-muted-foreground", dot: "bg-muted-foreground" },
  unread:            { bg: "bg-light-blue",   text: "text-dark-blue",   dot: "bg-dark-blue" },
  "action required": { bg: "bg-light-yellow", text: "text-dark-yellow", dot: "bg-dark-yellow" },

  // Visibility states
  private:   { bg: "bg-muted",        text: "text-muted-foreground", dot: "bg-muted-foreground" },
  internal:  { bg: "bg-light-blue",   text: "text-dark-blue",   dot: "bg-dark-blue" },
  public:    { bg: "bg-light-blue",   text: "text-dark-blue",   dot: "bg-dark-blue" },
  team:      { bg: "bg-light-blue",   text: "text-dark-blue",   dot: "bg-dark-blue" },
  neutral:   { bg: "bg-muted",        text: "text-muted-foreground", dot: "bg-muted-foreground" },

  // Review readiness vocabulary (#1728). The source data does not expose the
  // mockup's risk score, so the queue states the real validation result instead.
  ready:         { bg: "bg-light-green",  text: "text-dark-green",  dot: "bg-dark-green" },
  blocked:       { bg: "bg-light-red",    text: "text-dark-red",    dot: "bg-dark-red" },
};

const fallback = { bg: "bg-muted", text: "text-muted-foreground" };

export interface StatusBadgeProps {
  status: string;
  /**
   * `tinted` (default) keeps the existing look: the pill surface and the label
   * both carry the state's colour.
   *
   * `dot` is the mockup's `.badge` — a neutral `surface-raised` pill with
   * muted-foreground text, where only the 5px dot is toned. Use it inside dense
   * tables and rows, where a wall of tinted pills becomes noise. The label text
   * and the `ping` are identical in both variants, so the state never rests on
   * colour in either.
   */
  variant?: "tinted" | "dot";
  className?: string;
}

export function StatusBadge({ status, variant = "tinted", className }: StatusBadgeProps) {
  const s = statusConfig[status.toLowerCase()] ?? fallback;
  const dotOnly = variant === "dot";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-2xs font-medium",
        dotOnly ? "bg-surface-raised text-muted-foreground" : [s.bg, s.text],
        className
      )}
    >
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
