"use client";

import { useParams } from "next/navigation";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { PageHeader } from "@/components/layouts/page-header";
import { RegistryDetail } from "@/components/registry/registry-detail";
import { FeedbackList } from "@/components/registry/feedback-list";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useRegistryItem, useFeedback } from "@/hooks/use-api";

export default function SandboxDetailPage() {
  const { id } = useParams<{ id: string }>();
  const item = useRegistryItem("sandboxes", id);
  const fb = useFeedback("sandboxes", id);
  const data = item.data as Record<string, unknown> | undefined;

  return (
    <DashboardShell>
      <PageHeader
        title={String(data?.name ?? "Sandbox")}
        breadcrumbs={[{ label: "Home", href: "/" }, { label: "Sandboxes", href: "/sandboxes" }, { label: String(data?.name ?? id) }]}
      />
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="feedback">Feedback</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <RegistryDetail type="sandboxes" data={data} isLoading={item.isLoading} />
        </TabsContent>
        <TabsContent value="feedback">
          <FeedbackList data={fb.data as Record<string, unknown>[] | undefined} isLoading={fb.isLoading} />
        </TabsContent>
      </Tabs>
    </DashboardShell>
  );
}
