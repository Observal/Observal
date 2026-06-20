// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useState, useEffect } from "react";
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

interface PullCommandProps {
  agentName: string;
  currentVersion?: string | null;
  latestVersion?: string | null;
}

export function PullCommand({ agentName, currentVersion, latestVersion }: PullCommandProps) {
  const { data: ides, defaultIde } = useIdes();
  const [ide, setIde] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!ides || ides.length === 0) return;
    const defaultAllowed = defaultIde && ides.some((i) => i.name === defaultIde) ? defaultIde : ides[0].name;
    if (!ide || !ides.some((i) => i.name === ide)) {
      setIde(defaultAllowed);
    }
  }, [ides, defaultIde, ide]);

  const effectiveIde = ide || (defaultIde && ides?.some((i) => i.name === defaultIde) ? defaultIde : ides?.[0]?.name) || "cursor";
  const versionFlag = currentVersion && latestVersion && currentVersion !== latestVersion ? ` --version ${currentVersion}` : "";
  const command = `observal agent pull ${agentName} --ide ${effectiveIde}${versionFlag}`;

  function handleCopy() {
    copyToClipboard(command);
    setCopied(true);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="border border-border rounded-md bg-surface-sunken">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
        <Terminal className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-medium text-muted-foreground">Install</span>
        <div className="ml-auto flex items-center gap-2">
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
