"use client";

import { useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { ValidationResult } from "@/lib/types";

const IDE_OPTIONS = [
  { value: "claude-code", label: "Claude Code" },
  { value: "cursor", label: "Cursor" },
  { value: "kiro", label: "Kiro" },
  { value: "vscode", label: "VS Code" },
  { value: "gemini-cli", label: "Gemini CLI" },
  { value: "codex", label: "Codex" },
  { value: "copilot", label: "Copilot" },
] as const;

type Ide = (typeof IDE_OPTIONS)[number]["value"];

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
): string {
  if (mcps.length === 0) return "";
  const servers: Record<string, object> = {};
  for (const mcp of mcps) {
    servers[mcp.name] = {
      command: "observal-shim",
      args: ["--mcp-id", mcp.id, "--", "python", "-m", mcp.name],
    };
  }
  return JSON.stringify({ mcpServers: servers }, null, 2);
}

// ── Per-IDE preview generators ────────────────────────────────

interface PreviewFile {
  path: string;
  content: string;
  language: "markdown" | "json";
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
      language: "markdown",
    },
  ];
}

function generateCursorOrVscode(
  ide: "cursor" | "vscode",
  name: string,
  mcps: { id: string; name: string }[],
  body: string,
): PreviewFile[] {
  const safeName = name || "(untitled)";
  const dir = ide === "cursor" ? ".cursor" : ".vscode";
  const files: PreviewFile[] = [
    {
      path: `${dir}/rules/${safeName}.md`,
      content: body || `# ${safeName}`,
      language: "markdown",
    },
  ];
  if (mcps.length > 0) {
    files.push({
      path: `${dir}/mcp.json`,
      content: buildMcpJson(mcps),
      language: "json",
    });
  }
  return files;
}

function generateKiro(
  name: string,
  description: string,
  modelName: string,
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

  const agent = {
    name: safeName,
    description: (description || "").slice(0, 200),
    prompt: body,
    mcpServers: servers,
    tools: [...mcps.map((m) => `@${m.name}`), "read", "write", "shell"],
    model: modelName || "default",
  };

  return [
    {
      path: `~/.kiro/agents/${safeName}.json`,
      content: JSON.stringify(agent, null, 2),
      language: "json",
    },
  ];
}

function generateGemini(
  mcps: { id: string; name: string }[],
  body: string,
): PreviewFile[] {
  const files: PreviewFile[] = [
    { path: "GEMINI.md", content: body || "", language: "markdown" },
  ];
  if (mcps.length > 0) {
    files.push({
      path: ".gemini/mcp.json",
      content: buildMcpJson(mcps),
      language: "json",
    });
  }
  return files;
}

function generateCodex(body: string): PreviewFile[] {
  return [{ path: "AGENTS.md", content: body || "", language: "markdown" }];
}

function generateCopilot(body: string): PreviewFile[] {
  return [
    {
      path: ".github/copilot-instructions.md",
      content: body || "",
      language: "markdown",
    },
  ];
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

  const mcps = selectedComponents.mcps ?? [];
  const body = buildMarkdownBody(description, selectedComponents, goalSections, customPrompts);

  let files: PreviewFile[];
  switch (ide) {
    case "claude-code":
      files = generateClaudeCode(name, description, modelName ?? "", mcps, body);
      break;
    case "cursor":
      files = generateCursorOrVscode("cursor", name, mcps, body);
      break;
    case "vscode":
      files = generateCursorOrVscode("vscode", name, mcps, body);
      break;
    case "kiro":
      files = generateKiro(name, description, modelName ?? "", mcps, body);
      break;
    case "gemini-cli":
      files = generateGemini(mcps, body);
      break;
    case "codex":
      files = generateCodex(body);
      break;
    case "copilot":
      files = generateCopilot(body);
      break;
  }

  const errorCount = validationResult
    ? validationResult.issues.filter((i) => i.severity === "error").length
    : 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
          Preview
        </h3>
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

      {/* File previews */}
      <Card>
        <CardContent className="p-0 divide-y">
          {files.map((file) => (
            <div key={file.path}>
              <div className="px-4 py-2 text-[11px] font-medium text-muted-foreground bg-muted/40 font-[family-name:var(--font-mono)]">
                {file.path}
              </div>
              <pre className="min-h-[100px] whitespace-pre-wrap p-4 text-sm leading-relaxed font-[family-name:var(--font-mono)] text-foreground/80">
                {file.content}
              </pre>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
