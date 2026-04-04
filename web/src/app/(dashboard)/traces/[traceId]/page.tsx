"use client";

import { use } from "react";
import { useTrace } from "@/hooks/use-api";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { TraceDetail } from "@/components/traces/trace-detail";

export default function TraceDetailPage({ params }: { params: Promise<{ traceId: string }> }) {
  const { traceId } = use(params);
  const { data: trace, isLoading } = useTrace(traceId);

  return (
    <DashboardShell>
      <PageHeader
        title={`Trace ${traceId.slice(0, 8)}…`}
        breadcrumbs={[{ label: "Dashboard", href: "/" }, { label: "Traces", href: "/traces" }, { label: traceId.slice(0, 8) }]}
      />
      <TraceDetail trace={trace as never} isLoading={isLoading} />
    </DashboardShell>
  );
}
