"use client";

import Link from "next/link";
import { GitBranch } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { RegistryType } from "@/lib/api";

interface ComponentCardProps {
  id: string;
  name: string;
  type: RegistryType;
  description?: string;
  version?: string;
  status?: string;
  git_url?: string;
  className?: string;
}

const TYPE_LABELS: Record<string, string> = {
  mcps: "MCP",
  skills: "Skill",
  hooks: "Hook",
  prompts: "Prompt",
  sandboxes: "Sandbox",
};

export function ComponentCard({
  id,
  name,
  type,
  description,
  version,
  status,
  git_url,
  className,
}: ComponentCardProps) {
  return (
    <Link
      href={`/components/${id}?type=${type}`}
      className={[
        "group block border border-border bg-card p-4 rounded-md",
        "transition-all duration-200 ease-out",
        "hover:-translate-y-0.5 hover:border-foreground/20 hover:bg-accent/40",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className ?? "",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-display text-sm font-semibold leading-tight truncate">
          {name}
        </h3>
        <Badge variant="outline" className="shrink-0 text-[10px] px-1.5 py-0">
          {TYPE_LABELS[type] ?? type}
        </Badge>
      </div>

      {description && (
        <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed line-clamp-2">
          {description}
        </p>
      )}

      <div className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
        {version && (
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
            {version}
          </Badge>
        )}
        {status && status !== "approved" && (
          <Badge
            variant={status === "pending" ? "secondary" : "outline"}
            className="text-[10px] px-1.5 py-0"
          >
            {status}
          </Badge>
        )}
        {git_url && (
          <span className="inline-flex items-center gap-1 ml-auto">
            <GitBranch className="h-3 w-3" />
          </span>
        )}
      </div>
    </Link>
  );
}
