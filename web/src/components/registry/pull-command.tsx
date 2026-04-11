"use client";

import { useState } from "react";
import { Check, Copy, Terminal } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const IDES = [
  { value: "cursor", label: "Cursor" },
  { value: "vscode", label: "VS Code" },
  { value: "claude-code", label: "Claude Code" },
  { value: "gemini-cli", label: "Gemini CLI" },
  { value: "kiro", label: "Kiro" },
  { value: "codex", label: "Codex" },
  { value: "copilot", label: "Copilot" },
];

export function PullCommand({ agentName }: { agentName: string }) {
  const [ide, setIde] = useState("cursor");
  const [copied, setCopied] = useState(false);

  const command = `observal pull ${agentName} --ide ${ide}`;

  function handleCopy() {
    navigator.clipboard.writeText(command);
    setCopied(true);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="border border-border rounded-md bg-surface-sunken">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
        <Terminal className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-medium text-muted-foreground">Install</span>
        <div className="ml-auto">
          <Select value={ide} onValueChange={setIde}>
            <SelectTrigger className="h-7 w-[130px] text-xs border-border">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {IDES.map((i) => (
                <SelectItem key={i.value} value={i.value}>
                  {i.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="flex items-center gap-2 p-3">
        <code className="flex-1 text-sm font-mono select-all text-foreground leading-relaxed">
          <span className="text-muted-foreground">$</span> {command}
        </code>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0 hover:bg-accent"
          onClick={handleCopy}
          aria-label="Copy command"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-success" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
        </Button>
      </div>
    </div>
  );
}
