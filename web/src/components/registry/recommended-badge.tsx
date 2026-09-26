// SPDX-FileCopyrightText: 2026 Chandhini <chandhini@example.com>
// SPDX-License-Identifier: Apache-2.0

import { Award } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * A small "Recommended" pill that mirrors the existing StatusBadge treatment.
 * Uses the primary-accent OKLCH token so it works in both light and dark themes.
 */
export function RecommendedBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full bg-primary-accent/15 px-2.5 py-0.5 text-2xs font-medium text-primary-accent",
        className,
      )}
    >
      <Award className="h-3 w-3" />
      Recommended
    </span>
  );
}
