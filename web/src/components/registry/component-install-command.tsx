// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useState, useCallback, useEffect } from "react";
import { Check, Copy, Terminal } from "lucide-react";
import { toast } from "sonner";
import { copyToClipboard } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useIdes } from "@/hooks/use-ides";

interface ComponentInstallCommandProps {
  componentType: string;
  componentName: string;
}

export function ComponentInstallCommand({ componentType, componentName }: ComponentInstallCommandProps) {
  const { data: ides } = useIdes();
  const [ide, setIde] = useState("");
  useEffect(() => {
    if (!ides || ides.length === 0) return;
    const hasCurrent = ides.some((i) => i.name === ide);
    if (!ide || !hasCurrent) {
      setIde(ides[0].name);
    }
  }, [ides, ide]);
  const [copied, setCopied] = useState(false);

  const effectiveIde = ide || ides?.[0]?.name || "cursor";
  const command = `observal registry ${componentType} install ${componentName} --ide ${effectiveIde}`;

  const handleCopy = useCallback(async () => {
    try {
      await copyToClipboard(command);
      setCopied(true);
      toast.success("Copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy");
    }
  }, [command]);

  return (
    <div className="border border-border rounded-md bg-surface-sunken">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
        <Terminal className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-medium text-muted-foreground">Install</span>
        <div className="ml-auto">
          <Select value={effectiveIde} onValueChange={setIde}>
            <SelectTrigger className="h-7 w-[130px] text-xs border-border">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(ides ?? []).map((i) => (
                <SelectItem key={i.name} value={i.name}>
                  {i.display_name}
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
