"use client";

import { Settings } from "lucide-react";
import { useAdminSettings } from "@/hooks/use-api";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

export default function SettingsPage() {
  const { data: settings, isLoading, isError, error, refetch } = useAdminSettings();

  const entries: [string, unknown][] = Array.isArray(settings)
    ? settings.map((s: any) => [s.key, s.value])
    : Object.entries(settings ?? {});

  return (
    <>
      <PageHeader
        title="Settings"
        breadcrumbs={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Settings" },
        ]}
      />
      <div className="p-6 max-w-6xl mx-auto space-y-4">
        {isLoading ? (
          <TableSkeleton rows={5} cols={2} />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : entries.length === 0 ? (
          <EmptyState
            icon={Settings}
            title="No settings configured"
            description="System settings will appear here once they are configured."
          />
        ) : (
          <div className="animate-in space-y-0">
            {entries.map(([key, value], i) => (
              <div
                key={key}
                className={`flex items-start gap-6 py-3 ${
                  i < entries.length - 1 ? "border-b border-border" : ""
                }`}
              >
                <span className="text-xs font-[family-name:var(--font-mono)] text-muted-foreground shrink-0 min-w-[180px] pt-0.5 select-all">
                  {key}
                </span>
                <span className="text-sm text-foreground break-all">
                  {String(value)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
