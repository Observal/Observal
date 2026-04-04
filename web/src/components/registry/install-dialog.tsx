"use client";

import { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { registry, type RegistryType } from "@/lib/api";
import { Copy, Check, Download } from "lucide-react";

const IDE_OPTIONS = [
  "Cursor",
  "Kiro IDE",
  "Kiro CLI",
  "Claude Code",
  "VS Code",
  "Windsurf",
  "Gemini CLI",
];

interface InstallDialogProps {
  type: RegistryType;
  id: string;
  name: string;
}

export function InstallDialog({ type, id, name }: InstallDialogProps) {
  const [ide, setIde] = useState("");
  const [config, setConfig] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  async function handleInstall(selectedIde: string) {
    setIde(selectedIde);
    setLoading(true);
    try {
      const result = await registry.install(type, id, { ide: selectedIde });
      setConfig(typeof result === "string" ? result : JSON.stringify(result, null, 2));
    } catch (e) {
      setConfig(`Error: ${e instanceof Error ? e.message : "Failed to get config"}`);
    } finally {
      setLoading(false);
    }
  }

  function handleCopy() {
    navigator.clipboard.writeText(config);
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
            {IDE_OPTIONS.map((o) => (
              <SelectItem key={o} value={o}>{o}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {loading && <p className="text-sm text-muted-foreground">Loading config…</p>}
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
