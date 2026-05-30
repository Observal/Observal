// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { registry, type RegistryType } from "@/lib/api";
import { Copy, Check, Download, AlertTriangle } from "lucide-react";
import { copyToClipboard } from "@/lib/utils";
import { useIdes } from "@/hooks/use-ides";

interface InstallDialogProps {
  type: RegistryType;
  id: string;
  name: string;
}

export function InstallDialog({ type, id, name }: InstallDialogProps) {
  const { data: ides } = useIdes();
  const [ide, setIde] = useState("");
  const [config, setConfig] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  async function handleInstall(selectedIde: string) {
    setIde(selectedIde);
    setLoading(true);
    setWarnings([]);
    try {
      const result = await registry.install(type, id, { ide: selectedIde });
      if (result && typeof result === "object" && !Array.isArray(result)) {
        const w = (result as Record<string, unknown>).warnings;
        if (Array.isArray(w) && w.length > 0) {
          setWarnings(w as string[]);
        }
      }
      setConfig(typeof result === "string" ? result : JSON.stringify(result, null, 2));
    } catch (e) {
      setConfig(`Error: ${e instanceof Error ? e.message : "Failed to get config"}`);
    } finally {
      setLoading(false);
    }
  }

  function handleCopy() {
    copyToClipboard(config);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <Dialog onOpenChange={() => { setConfig(""); setIde(""); }}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Download className="mr-1 h-3 w-3" /> Install
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Install {name}</DialogTitle>
        </DialogHeader>
        <Select onValueChange={handleInstall} value={ide}>
          <SelectTrigger>
            <SelectValue placeholder="Select IDE" />
          </SelectTrigger>
          <SelectContent>
            {(ides ?? []).map((o) => (
              <SelectItem key={o.name} value={o.name}>{o.display_name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {loading && <p className="text-sm text-muted-foreground">Loading config…</p>}
        {warnings.length > 0 && (
          <div className="rounded-md border border-warning/30 bg-warning/10 p-3 space-y-1">
            {warnings.map((w, i) => (
              <p key={i} className="text-xs text-warning flex items-start gap-1.5">
                <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                {w}
              </p>
            ))}
          </div>
        )}
        {config && (
          <div className="relative">
            <pre className="max-h-80 overflow-auto rounded-md bg-muted p-4 text-xs">{config}</pre>
            <Button size="icon" variant="ghost" className="absolute right-2 top-2 h-7 w-7" onClick={handleCopy}>
              {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
