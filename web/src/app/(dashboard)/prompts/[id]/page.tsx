"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { PageHeader } from "@/components/layouts/page-header";
import { RegistryDetail } from "@/components/registry/registry-detail";
import { FeedbackList } from "@/components/registry/feedback-list";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useRegistryItem, useFeedback } from "@/hooks/use-api";
import { registry } from "@/lib/api";

export default function PromptDetailPage() {
  const { id } = useParams<{ id: string }>();
  const item = useRegistryItem("prompts", id);
  const fb = useFeedback("prompts", id);
  const data = item.data as Record<string, unknown> | undefined;

  return (
    <DashboardShell>
      <PageHeader
        title={String(data?.name ?? "Prompt")}
        breadcrumbs={[{ label: "Home", href: "/" }, { label: "Prompts", href: "/prompts" }, { label: String(data?.name ?? id) }]}
      />
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="render">Render Preview</TabsTrigger>
          <TabsTrigger value="feedback">Feedback</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <RegistryDetail type="prompts" data={data} isLoading={item.isLoading} />
        </TabsContent>
        <TabsContent value="render">
          <RenderPreview id={id} template={String(data?.template ?? "")} />
        </TabsContent>
        <TabsContent value="feedback">
          <FeedbackList data={fb.data as Record<string, unknown>[] | undefined} isLoading={fb.isLoading} />
        </TabsContent>
      </Tabs>
    </DashboardShell>
  );
}

function RenderPreview({ id, template }: { id: string; template: string }) {
  const [vars, setVars] = useState<Record<string, string>>({});
  const [rendered, setRendered] = useState("");
  const [loading, setLoading] = useState(false);

  // Extract {{var}} placeholders from template
  const placeholders = Array.from(new Set(template.match(/\{\{(\w+)\}\}/g)?.map((m) => m.slice(2, -2)) ?? []));

  async function handleRender() {
    setLoading(true);
    try {
      const result = await registry.install("prompts", id, { variables: vars });
      setRendered(typeof result === "string" ? result : JSON.stringify(result, null, 2));
    } catch (e) {
      setRendered(`Error: ${e instanceof Error ? e.message : "Render failed"}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Render Preview</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {template && (
          <pre className="rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">{template}</pre>
        )}
        {placeholders.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-2">
            {placeholders.map((p) => (
              <div key={p} className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">{p}</label>
                <Input
                  placeholder={p}
                  value={vars[p] ?? ""}
                  onChange={(e) => setVars((prev) => ({ ...prev, [p]: e.target.value }))}
                />
              </div>
            ))}
          </div>
        )}
        <Button size="sm" onClick={handleRender} disabled={loading}>
          {loading ? "Rendering…" : "Render"}
        </Button>
        {rendered && (
          <pre className="rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">{rendered}</pre>
        )}
      </CardContent>
    </Card>
  );
}
