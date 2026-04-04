"use client";

import { useParams } from "next/navigation";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { PageHeader } from "@/components/layouts/page-header";
import { RegistryDetail } from "@/components/registry/registry-detail";
import { MetricsPanel } from "@/components/registry/metrics-panel";
import { FeedbackList } from "@/components/registry/feedback-list";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useRegistryItem, useRegistryMetrics, useFeedback } from "@/hooks/use-api";

export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const item = useRegistryItem("agents", id);
  const metrics = useRegistryMetrics("agents", id);
  const fb = useFeedback("agents", id);
  const data = item.data as Record<string, unknown> | undefined;

  return (
    <DashboardShell>
      <PageHeader
        title={String(data?.name ?? "Agent")}
        breadcrumbs={[{ label: "Home", href: "/" }, { label: "Agents", href: "/agents" }, { label: String(data?.name ?? id) }]}
      />
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="metrics">Metrics</TabsTrigger>
          <TabsTrigger value="feedback">Feedback</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <RegistryDetail type="agents" data={data} isLoading={item.isLoading} />
        </TabsContent>
        <TabsContent value="metrics">
          <MetricsPanel type="agents" data={metrics.data as Record<string, unknown> | undefined} isLoading={metrics.isLoading} />
        </TabsContent>
        <TabsContent value="feedback">
          <FeedbackList data={fb.data as Record<string, unknown>[] | undefined} isLoading={fb.isLoading} />
        </TabsContent>
      </Tabs>
    </DashboardShell>
  );
}
