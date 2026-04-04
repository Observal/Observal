"use client";

import { useParams } from "next/navigation";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { PageHeader } from "@/components/layouts/page-header";
import { RegistryDetail } from "@/components/registry/registry-detail";
import { MetricsPanel } from "@/components/registry/metrics-panel";
import { FeedbackList } from "@/components/registry/feedback-list";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useRegistryItem, useRegistryMetrics, useFeedback } from "@/hooks/use-api";

export default function McpDetailPage() {
  const { id } = useParams<{ id: string }>();
  const item = useRegistryItem("mcps", id);
  const metrics = useRegistryMetrics("mcps", id);
  const fb = useFeedback("mcps", id);
  const data = item.data as Record<string, unknown> | undefined;

  return (
    <DashboardShell>
      <PageHeader
        title={String(data?.name ?? "MCP Server")}
        breadcrumbs={[{ label: "Home", href: "/" }, { label: "MCP Servers", href: "/mcps" }, { label: String(data?.name ?? id) }]}
      />
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="metrics">Metrics</TabsTrigger>
          <TabsTrigger value="feedback">Feedback</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <RegistryDetail type="mcps" data={data} isLoading={item.isLoading} />
        </TabsContent>
        <TabsContent value="metrics">
          <MetricsPanel type="mcps" data={metrics.data as Record<string, unknown> | undefined} isLoading={metrics.isLoading} />
        </TabsContent>
        <TabsContent value="feedback">
          <FeedbackList data={fb.data as Record<string, unknown>[] | undefined} isLoading={fb.isLoading} />
        </TabsContent>
      </Tabs>
    </DashboardShell>
  );
}
