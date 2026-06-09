// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import { Button } from "@/components/ui/button";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  actionLabel?: string;
  actionHref?: string;
  onAction?: () => void;
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  actionLabel,
  actionHref,
  onAction,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-md border border-dashed py-16">
      <Icon className="h-10 w-10 text-muted-foreground/50" />
      <p className="mt-4 text-sm font-medium">{title}</p>
      {description && (
        <p className="mt-1 max-w-sm text-center text-xs text-muted-foreground">
          {description}
        </p>
      )}
      {actionLabel && (actionHref || onAction) && (
        actionHref ? (
          <a
            href={actionHref}
            {...(actionHref.startsWith("http")
              ? { target: "_blank", rel: "noopener noreferrer" }
              : {})}
          >
            <Button variant="outline" size="sm" className="mt-4">
              {actionLabel}
            </Button>
          </a>
        ) : (
          <Button variant="outline" size="sm" className="mt-4" onClick={onAction}>
            {actionLabel}
          </Button>
        )
      )}
    </div>
  );
}
