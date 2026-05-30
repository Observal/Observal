// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { Badge } from "@/components/ui/badge";
import { IDE_DISPLAY_NAMES, type IdeName } from "@/lib/ide-features";

interface IdeBadgesProps {
  supportedIdes?: string[];
  inferredSupportedIdes?: string[];
  /** Maximum badges to show before "+N more" overflow. */
  max?: number;
  className?: string;
}

export function IdeBadges({
  supportedIdes,
  inferredSupportedIdes,
  max = 4,
  className,
}: IdeBadgesProps) {
  const ides =
    supportedIdes && supportedIdes.length > 0
      ? supportedIdes
      : inferredSupportedIdes ?? [];

  if (ides.length === 0) return null;

  const visible = ides.slice(0, max);
  const overflow = ides.length - max;

  return (
    <div className={["flex flex-wrap items-center gap-1", className ?? ""].join(" ")}>
      {visible.map((ide) => (
        <Badge
          key={ide}
          variant="outline"
          className="text-[10px] px-1.5 py-0 font-normal leading-4"
        >
          {IDE_DISPLAY_NAMES[ide as IdeName] ?? ide}
        </Badge>
      ))}
      {overflow > 0 && (
        <span className="text-[10px] text-muted-foreground">
          +{overflow} more
        </span>
      )}
    </div>
  );
}
