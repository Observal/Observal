"use client";

import { useState, useMemo } from "react";
import { Copy, Play } from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { useRegistryList } from "@/hooks/use-api";
import { registry } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";

interface PromptItem {
  id: string;
  name: string;
  template?: string;
}

function extractVariables(template: string): string[] {
  const matches = template.match(/\{\{(\w+)\}\}/g) ?? [];
  return [...new Set(matches.map((m) => m.slice(2, -2)))];
}

export default function PromptPlaygroundPage() {
  const { data: prompts, isLoading } = useRegistryList("prompts");
  const items = (prompts ?? []) as PromptItem[];

  const [selectedId, setSelectedId] = useState<string>("");
  const [vars, setVars] = useState<Record<string, string>>({});
  const [rendered, setRendered] = useState("");
  const [rendering, setRendering] = useState(false);

  const selected = items.find((p) => p.id === selectedId);
  const template = selected?.template ?? "";
  const variables = useMemo(() => extractVariables(template), [template]);
  const tokenEstimate = Math.ceil(rendered.length / 4);

  const handleSelect = (id: string) => {
    setSelectedId(id);
    setRendered("");
    setVars({});
  };

  const handleRender = async () => {
    if (!selectedId) return;
    setRendering(true);
    try {
      const result = await registry.install("prompts", selectedId, { variables: vars }) as { rendered?: string };
      setRendered(result?.rendered ?? JSON.stringify(result, null, 2));
    } catch (e) {
      setRendered(`Error: ${e instanceof Error ? e.message : "Unknown error"}`);
    } finally {
      setRendering(false);
    }
  };

  return (
    <DashboardShell>
      <PageHeader
        title="Prompt Playground"
        breadcrumbs={[
          { label: "Home", href: "/" },
          { label: "Prompts", href: "/prompts" },
          { label: "Playground" },
        ]}
      />
      <DashboardContent>
        <div className="flex flex-col gap-4">
          <ResizablePanelGroup orientation="horizontal" className="min-h-[500px] rounded-md border">
            {/* Left: prompt selector + template */}
            <ResizablePanel defaultSize={50} minSize={30}>
              <div className="flex h-full flex-col gap-3 p-3">
                <div>
                  <Label className="mb-1 text-xs">Prompt</Label>
                  <Select value={selectedId} onValueChange={handleSelect}>
                    <SelectTrigger className="h-8 text-sm">
                      <SelectValue placeholder={isLoading ? "Loading…" : "Select a prompt"} />
                    </SelectTrigger>
                    <SelectContent>
                      {items.map((p) => (
                        <SelectItem key={p.id} value={p.id} className="text-sm">
                          {p.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex-1">
                  <Label className="mb-1 text-xs">Template</Label>
                  <Textarea
                    readOnly
                    value={template}
                    placeholder="Select a prompt to view its template"
                    className="h-full min-h-[200px] resize-none font-mono text-xs"
                  />
                </div>
              </div>
            </ResizablePanel>

            <ResizableHandle withHandle />

            {/* Right: variables + render */}
            <ResizablePanel defaultSize={50} minSize={30}>
              <div className="flex h-full flex-col gap-3 p-3">
                <div className="space-y-2">
                  <Label className="text-xs">Variables</Label>
                  {variables.length === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      {template ? "No variables detected" : "Select a prompt first"}
                    </p>
                  ) : (
                    variables.map((v) => (
                      <div key={v} className="flex items-center gap-2">
                        <Badge variant="outline" className="shrink-0 font-mono text-[10px]">
                          {`{{${v}}}`}
                        </Badge>
                        <Input
                          className="h-7 text-sm"
                          placeholder={v}
                          value={vars[v] ?? ""}
                          onChange={(e) => setVars((prev) => ({ ...prev, [v]: e.target.value }))}
                        />
                      </div>
                    ))
                  )}
                </div>
                <Button
                  size="sm"
                  disabled={!selectedId || rendering}
                  onClick={handleRender}
                >
                  <Play className="mr-1 h-3 w-3" />
                  {rendering ? "Rendering…" : "Render"}
                </Button>
                <div className="flex-1">
                  <div className="mb-1 flex items-center justify-between">
                    <Label className="text-xs">Output</Label>
                    <div className="flex items-center gap-2">
                      {rendered && (
                        <span className="text-[10px] text-muted-foreground tabular-nums">
                          ~{tokenEstimate} tokens
                        </span>
                      )}
                      {rendered && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-1.5"
                          onClick={() => navigator.clipboard.writeText(rendered)}
                        >
                          <Copy className="h-3 w-3" />
                        </Button>
                      )}
                    </div>
                  </div>
                  <Textarea
                    readOnly
                    value={rendered}
                    placeholder="Rendered output will appear here"
                    className="h-full min-h-[200px] resize-none font-mono text-xs"
                  />
                </div>
              </div>
            </ResizablePanel>
          </ResizablePanelGroup>
        </div>
      </DashboardContent>
    </DashboardShell>
  );
}
