// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { useState, useCallback, useEffect } from "react";
import { Check, Copy, Terminal } from "lucide-react";
import { toast } from "sonner";
import { copyToClipboard } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { PickerSelect } from "@/components/ui/picker-select";
import { useHarnesses } from "@/hooks/use-harnesses";

interface ComponentInstallCommandProps {
  componentType: string;
  componentName: string;
}

export function ComponentInstallCommand({ componentType, componentName }: ComponentInstallCommandProps) {
  const { data: harnesses } = useHarnesses();
  const [harness, setHarness] = useState("");
  useEffect(() => {
    if (!harnesses || harnesses.length === 0) return;
    const hasCurrent = harnesses.some((i) => i.name === harness);
    if (!harness || !hasCurrent) {
      setHarness(harnesses[0].name);
    }
  }, [harnesses, harness]);
  const [copied, setCopied] = useState(false);

  const effectiveHarness = harness || harnesses?.[0]?.name || "cursor";
  const command = `observal registry ${componentType} install ${componentName} --harness ${effectiveHarness}`;

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
          <PickerSelect
            value={effectiveHarness}
            onValueChange={setHarness}
            className="w-[130px]"
            inputClassName="h-7 border-border text-xs"
            options={(harnesses ?? []).map((i) => ({ value: i.name, label: i.display_name }))}
          />
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
