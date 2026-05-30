// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { Link } from "@tanstack/react-router";
import { ArrowDownToLine, Puzzle, Star } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { IdeBadges } from "@/components/registry/ide-badges";
import { compactNumber } from "@/lib/utils";

interface AgentCardProps {
  id: string;
  name: string;
  description?: string;
  model_name?: string;
  owner?: string;
  created_by_username?: string | null;
  downloads?: number;
  score?: number;
  version?: string;
  component_count?: number;
  status?: string;
  supported_ides?: string[];
  inferred_supported_ides?: string[];
  className?: string;
}

export function AgentCard({
  id,
  name,
  description,
  owner,
  created_by_username,
  downloads,
  score,
  version,
  component_count,
  supported_ides,
  inferred_supported_ides,
  className,
}: AgentCardProps) {
  return (
    <Link
      to="/agents/$agentId" params={{ agentId: id }}
      className={[
        "group block border border-border bg-card p-4 rounded-md",
        "transition-all duration-200 ease-out",
        "hover:-translate-y-0.5 hover:border-foreground/20 hover:bg-accent/40",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className ?? "",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-display text-sm font-semibold leading-tight truncate">
          {name}
        </h3>
        {version && (
          <Badge variant="secondary" className="shrink-0 text-[10px] px-1.5 py-0">
            {version}
          </Badge>
        )}
      </div>

      {description && (
        <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed line-clamp-2">
          {description}
        </p>
      )}

      {(created_by_username || owner) && (
        <p className="mt-2 text-[11px] text-muted-foreground/70 truncate">
          {created_by_username ? `@${created_by_username}` : owner}
        </p>
      )}

      <div className="mt-3 flex items-center gap-4 text-xs text-muted-foreground">
        {downloads != null && (
          <span className="inline-flex items-center gap-1">
            <ArrowDownToLine className="h-3 w-3" />
            {compactNumber(downloads)}
          </span>
        )}
        {score != null && (
          <span className="inline-flex items-center gap-1">
            <Star className="h-3 w-3" />
            {score.toFixed(1)}
          </span>
        )}
        {component_count != null && component_count > 0 && (
          <span className="inline-flex items-center gap-1">
            <Puzzle className="h-3 w-3" />
            {component_count}
          </span>
        )}
      </div>

      <IdeBadges
        supportedIdes={supported_ides}
        inferredSupportedIdes={inferred_supported_ides}
        max={3}
        className="mt-2"
      />
    </Link>
  );
}
