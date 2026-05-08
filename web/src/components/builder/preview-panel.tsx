"use client";

import { useState, useCallback, useRef } from "react";
import { CheckCircle2, XCircle, Loader2, Maximize2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { IDE_DISPLAY_NAMES, type IdeName } from "@/lib/ide-features";
import { registry } from "@/lib/api";
import type { ValidationResult } from "@/lib/types";

// Curated display order for the builder preview (copilot-cli excluded)
const IDE_DISPLAY_ORDER = [
  "claude-code", "cursor", "kiro", "vscode", "gemini-cli", "codex", "copilot", "opencode",
] as const satisfies readonly IdeName[];

const IDE_OPTIONS = IDE_DISPLAY_ORDER.map((ide) => ({
  value: ide,
  label: IDE_DISPLAY_NAMES[ide],
}));

type Ide = (typeof IDE_DISPLAY_ORDER)[number];

interface PreviewPanelProps {
  name: string;
  description: string;
  modelName?: string;
  selectedComponents: Record<string, { id: string; name: string }[]>;
  goalSections: { id: string; title: string; content: string }[];
  customPrompts?: { id: string; title: string; content: string }[];
  validationResult: ValidationResult | null;
}

// ── Shared helpers ────────────────────────────────────────────

function buildMarkdownBody(
  description: string,
  selectedComponents: Record<string, { id: string; name: string }[]>,
  goalSections: { id: string; title: string; content: string }[],
  customPrompts?: { id: string; title: string; content: string }[],
): string {
  const lines: string[] = [];

  if (description) {
    lines.push(description);
  }

  for (const [type, items] of Object.entries(selectedComponents)) {
    if (items.length === 0) continue;
    const heading =
      type === "mcps"
        ? "MCP Servers"
        : type.charAt(0).toUpperCase() + type.slice(1);
    lines.push("");
    lines.push(`## ${heading}`);
    lines.push("");
    items.forEach((item) => lines.push(`- **${item.name}**`));
  }

  const nonEmptyPrompts = (customPrompts ?? []).filter(
    (p) => p.content.trim(),
  );
  if (nonEmptyPrompts.length > 0) {
    lines.push("");
    lines.push("## Custom Prompts");
    lines.push("");
    nonEmptyPrompts.forEach((prompt) => {
      if (prompt.title.trim()) {
        lines.push(`### ${prompt.title.trim()}`);
      }
      lines.push(prompt.content.trim());
    });
  }

  const nonEmptyGoals = goalSections.filter((s) => s.title || s.content);
  if (nonEmptyGoals.length > 0) {
    lines.push("");
    lines.push("## Goals");
    lines.push("");
    nonEmptyGoals.forEach((section) => {
      lines.push(`### ${section.title || "(section)"}`);
      if (section.content) {
        lines.push(section.content);
      }
    });
  }

  return lines.join("\n");
}

function buildMcpJson(
  mcps: { id: string; name: string }[],
  key: string = "mcpServers",
): string {
  if (mcps.length === 0) return "";
  const servers: Record<string, object> = {};
  for (const mcp of mcps) {
    servers[mcp.name] = {
      command: "observal-shim",
      args: ["--mcp-id", mcp.id, "--", "python", "-m", mcp.name],
    };
  }
  return JSON.stringify({ [key]: servers }, null, 2);
}

// ── Per-IDE preview generators (simplified mode) ─────────────

interface PreviewFile {
  path: string;
  content: string;
}

function generateClaudeCode(
  name: string,
  description: string,
  modelName: string,
  mcps: { id: string; name: string }[],
  body: string,
): PreviewFile[] {
  const safeName = name || "(untitled)";
  const lines: string[] = [];

  lines.push("---");
  lines.push(`name: ${safeName}`);
  if (description) {
    const descLine = description.replace(/\n/g, " ").trim();
    lines.push(`description: "${descLine}"`);
  }
  if (modelName) {
    lines.push(`model: ${modelName}`);
  }
  if (mcps.length > 0) {
    lines.push("mcpServers:");
    mcps.forEach((m) => lines.push(`  - ${m.name}`));
  }
  lines.push("---");
  if (body) {
    lines.push("");
    lines.push(body);
  }

  return [
    {
      path: `.claude/agents/${safeName}.md`,
      content: lines.join("\n"),
    },
  ];
}

function generateCursor(
  name: string,
  mcps: { id: string; name: string }[],
  body: string,
): PreviewFile[] {
  const safeName = name || "(untitled)";
  const files: PreviewFile[] = [
    {
      path: `.cursor/rules/${safeName}.mdc`,
      content: body || `# ${safeName}`,
    },
  ];
  if (mcps.length > 0) {
    files.push({
      path: ".cursor/mcp.json",
      content: buildMcpJson(mcps, "mcpServers"),
    });
  }
  return files;
}

function generateVscode(
  name: string,
  mcps: { id: string; name: string }[],
  body: string,
): PreviewFile[] {
  const safeName = name || "(untitled)";
  const files: PreviewFile[] = [
    {
      path: `.github/instructions/${safeName}.instructions.md`,
      content: body || `# ${safeName}`,
    },
  ];
  if (mcps.length > 0) {
    files.push({
      path: ".vscode/mcp.json",
      content: buildMcpJson(mcps, "servers"),
    });
  }
  return files;
}

function generateKiro(
  name: string,
  description: string,
  mcps: { id: string; name: string }[],
  body: string,
): PreviewFile[] {
  const safeName = name || "(untitled)";
  const servers: Record<string, object> = {};
  for (const mcp of mcps) {
    servers[mcp.name] = {
      command: "observal-shim",
      args: ["--mcp-id", mcp.id, "--", "python", "-m", mcp.name],
    };
  }

  const wrappedPrompt = body
    ? `# ${safeName} — Agent Specialization\n\nYou are a Kiro agent with the following specialization.\n\n## Instructions\n\n${body}`
    : "";

  const agent: Record<string, unknown> = {
    name: safeName,
    description: (description || "").slice(0, 200),
    prompt: wrappedPrompt,
    mcpServers: servers,
    tools: ["*"],
    toolAliases: {},
    allowedTools: [],
    resources: [
      "file://AGENTS.md",
      "file://README.md",
      "skill://.kiro/skills/*/SKILL.md",
      "skill://~/.kiro/skills/*/SKILL.md",
    ],
    hooks: {
      agentSpawn: [{ command: "..." }],
      userPromptSubmit: [{ command: "..." }],
      preToolUse: [{ matcher: "*", command: "..." }],
      postToolUse: [{ matcher: "*", command: "..." }],
      stop: [{ command: "..." }],
    },
    toolsSettings: {},
    includeMcpJson: true,
    model: null,
  };

  return [
    {
      path: `~/.kiro/agents/${safeName}.json`,
      content: JSON.stringify(agent, null, 2),
    },
  ];
}

function generateGemini(
  mcps: { id: string; name: string }[],
  body: string,
): PreviewFile[] {
  const files: PreviewFile[] = [
    { path: "GEMINI.md", content: body || "" },
  ];
  if (mcps.length > 0) {
    const servers: Record<string, object> = {};
    for (const mcp of mcps) {
      servers[mcp.name] = {
        command: "observal-shim",
        args: ["--mcp-id", mcp.id, "--", "python", "-m", mcp.name],
      };
    }
    files.push({
      path: ".gemini/settings.json",
      content: JSON.stringify({ mcpServers: servers }, null, 2),
    });
  }
  return files;
}

function generateCodex(
  mcps: { id: string; name: string }[],
  body: string,
): PreviewFile[] {
  const files: PreviewFile[] = [
    { path: "AGENTS.md", content: body || "" },
  ];
  if (mcps.length > 0) {
    const tomlLines = ["[mcp.servers]"];
    for (const mcp of mcps) {
      tomlLines.push("");
      tomlLines.push(`[mcp.servers.${mcp.name}]`);
      tomlLines.push(`command = "observal-shim"`);
      tomlLines.push(`args = ["--mcp-id", "${mcp.id}", "--", "python", "-m", "${mcp.name}"]`);
    }
    files.push({
      path: "~/.codex/config.toml",
      content: tomlLines.join("\n"),
    });
  }
  return files;
}

function generateCopilot(
  name: string,
  mcps: { id: string; name: string }[],
  body: string,
): PreviewFile[] {
  const safeName = name || "(untitled)";
  const files: PreviewFile[] = [
    {
      path: `.github/agents/${safeName}.agent.md`,
      content: body || "",
    },
  ];
  if (mcps.length > 0) {
    files.push({
      path: ".vscode/mcp.json",
      content: buildMcpJson(mcps, "servers"),
    });
  }
  return files;
}

function generateOpenCode(
  mcps: { id: string; name: string }[],
  body: string,
): PreviewFile[] {
  const files: PreviewFile[] = [
    { path: "AGENTS.md", content: body || "" },
  ];
  if (mcps.length > 0) {
    const mcp: Record<string, object> = {};
    for (const m of mcps) {
      mcp[m.name] = {
        type: "local",
        command: ["observal-shim", "--mcp-id", m.id, "--", "python", "-m", m.name],
      };
    }
    files.push({
      path: "~/.config/opencode/opencode.json",
      content: JSON.stringify({ mcp }, null, 2),
    });
  }
  return files;
}

// ── Main component ────────────────────────────────────────────

export function PreviewPanel({
  name,
  description,
  modelName,
  selectedComponents,
  goalSections,
  customPrompts,
  validationResult,
}: PreviewPanelProps) {
  const [ide, setIde] = useState<Ide>("claude-code");
  const [modalOpen, setModalOpen] = useState(false);
  const [modalIde, setModalIde] = useState<Ide>("claude-code");
  const [fullConfigs, setFullConfigs] = useState<Record<string, Record<string, string>> | null>(null);
  const [fullLoading, setFullLoading] = useState(false);
  const [fullError, setFullError] = useState<string | null>(null);
  const modalScrollRef = useRef<HTMLDivElement>(null);

  const mcps = selectedComponents.mcps ?? [];
  const body = buildMarkdownBody(description, selectedComponents, goalSections, customPrompts);

  // Simplified mode: client-side generators
  let files: PreviewFile[];
  switch (ide) {
    case "claude-code":
      files = generateClaudeCode(name, description, modelName ?? "", mcps, body);
      break;
    case "cursor":
      files = generateCursor(name, mcps, body);
      break;
    case "vscode":
      files = generateVscode(name, mcps, body);
      break;
    case "kiro":
      files = generateKiro(name, description, mcps, body);
      break;
    case "gemini-cli":
      files = generateGemini(mcps, body);
      break;
    case "codex":
      files = generateCodex(mcps, body);
      break;
    case "copilot":
      files = generateCopilot(name, mcps, body);
      break;
    case "opencode":
      files = generateOpenCode(mcps, body);
      break;
  }

  const fetchFullConfig = useCallback(async () => {
    const components: { component_type: string; component_id: string }[] = [];
    for (const [type, items] of Object.entries(selectedComponents)) {
      const componentType = type === "mcps" ? "mcp" : type === "skills" ? "skill" : type === "hooks" ? "hook" : type === "prompts" ? "prompt" : null;
      if (!componentType) continue;
      for (const item of items) {
        components.push({ component_type: componentType, component_id: item.id });
      }
    }

    setFullLoading(true);
    setFullError(null);

    try {
      const res = await registry.previewConfig({
        name: name || "untitled",
        description,
        prompt: body,
        model_name: modelName ?? "",
        components,
      });
      setFullConfigs(res.configs);
    } catch (e) {
      setFullError(e instanceof Error ? e.message : "Failed to generate config");
    } finally {
      setFullLoading(false);
    }
  }, [name, description, body, modelName, selectedComponents]);

  const handleOpenFullPreview = useCallback(() => {
    setModalIde(ide);
    setModalOpen(true);
    fetchFullConfig();
  }, [ide, fetchFullConfig]);

  // Files for the modal view
  const modalFiles: PreviewFile[] =
    fullConfigs && fullConfigs[modalIde]
      ? Object.entries(fullConfigs[modalIde]).map(([path, content]) => ({ path, content }))
      : [];

  const errorCount = validationResult
    ? validationResult.issues.filter((i) => i.severity === "error").length
    : 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
          Preview
        </h3>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleOpenFullPreview}
            className="inline-flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary transition-colors hover:bg-primary/20"
          >
            <Maximize2 className="h-3 w-3" />
            Full Config
          </button>
          {validationResult && (
            <span className="inline-flex items-center gap-1 text-xs">
              {validationResult.valid ? (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
                  <span className="text-emerald-600 dark:text-emerald-400">
                    Valid
                  </span>
                </>
              ) : (
                <>
                  <XCircle className="h-3.5 w-3.5 text-destructive" />
                  <span className="text-destructive">
                    {errorCount} {errorCount === 1 ? "error" : "errors"}
                  </span>
                </>
              )}
            </span>
          )}
        </div>
      </div>

      {/* IDE selector */}
      <div className="flex flex-wrap gap-1">
        {IDE_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => setIde(opt.value)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              ide === opt.value
                ? "bg-primary text-primary-foreground"
                : "bg-muted/50 text-muted-foreground hover:bg-muted"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Simplified file previews */}
      <Card>
        <CardContent className="p-0 divide-y">
          {files.map((file) => (
            <div key={file.path}>
              <div className="px-4 py-2 text-[11px] font-medium text-muted-foreground bg-muted/40 font-[family-name:var(--font-mono)]">
                {file.path}
              </div>
              <pre className="overflow-x-auto min-h-[100px] whitespace-pre p-4 text-sm leading-relaxed font-[family-name:var(--font-mono)] text-foreground/80">
                {file.content}
              </pre>
            </div>
          ))}
        </CardContent>
      </Card>

      <p className="text-[11px] text-muted-foreground">
        Telemetry hooks and environment variables are configured during installation via <code className="font-[family-name:var(--font-mono)]">observal pull</code>.
      </p>

      {/* Full config modal */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col p-0">
          <DialogHeader className="px-6 pt-6 pb-0">
            <DialogTitle>Full Config Preview</DialogTitle>
            <DialogDescription>
              Exact files written by <code className="font-[family-name:var(--font-mono)]">observal pull</code>. Server URLs are placeholders.
            </DialogDescription>
          </DialogHeader>

          {/* IDE tabs inside modal */}
          <div className="flex flex-wrap gap-1 px-6 pt-3">
            {IDE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  setModalIde(opt.value);
                  modalScrollRef.current?.scrollTo({ top: 0 });
                }}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  modalIde === opt.value
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted/50 text-muted-foreground hover:bg-muted"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* File tabs — sticky below IDE tabs */}
          {!fullLoading && !fullError && modalFiles.length > 1 && (
            <div className="flex flex-wrap gap-1 px-6 pb-2 pt-1 border-b border-border">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60 self-center mr-1">Files</span>
              {modalFiles.map((file, i) => (
                <button
                  key={file.path}
                  type="button"
                  onClick={() => {
                    document.getElementById(`preview-file-${i}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                  className="rounded px-2 py-0.5 text-[11px] font-medium font-[family-name:var(--font-mono)] text-muted-foreground border border-border/50 bg-background hover:bg-muted hover:text-foreground transition-colors"
                >
                  {file.path.split("/").pop()}
                </button>
              ))}
            </div>
          )}

          {/* Modal file content */}
          <div ref={modalScrollRef} className="flex-1 overflow-y-auto px-6 pb-6 pt-3">
            {fullLoading ? (
              <div className="flex items-center justify-center py-16 text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin mr-2" />
                <span className="text-sm">Generating configs...</span>
              </div>
            ) : fullError ? (
              <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                <XCircle className="h-5 w-5 mb-2 text-destructive" />
                <span className="text-sm">{fullError}</span>
              </div>
            ) : modalFiles.length === 0 ? (
              <div className="flex items-center justify-center py-16 text-muted-foreground">
                <span className="text-sm">No config generated for this IDE.</span>
              </div>
            ) : (
              <div className="space-y-3">
                {modalFiles.map((file, i) => (
                  <div key={file.path} id={`preview-file-${i}`} className="rounded-md border border-border overflow-hidden">
                    <div className="px-4 py-2 text-[11px] font-medium text-muted-foreground bg-muted/40 font-[family-name:var(--font-mono)]">
                      {file.path}
                    </div>
                    <pre className="overflow-x-auto whitespace-pre p-4 text-sm leading-relaxed font-[family-name:var(--font-mono)] text-foreground/80 bg-background">
                      {file.content}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
