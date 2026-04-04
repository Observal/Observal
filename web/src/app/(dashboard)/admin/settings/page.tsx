"use client";

import { useState, useEffect } from "react";
import { useAdminSettings } from "@/hooks/use-api";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { admin } from "@/lib/api";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Check } from "lucide-react";

interface Setting {
  key: string;
  value: string;
}

export default function AdminSettingsPage() {
  const qc = useQueryClient();
  const { data: rawSettings, isLoading } = useAdminSettings();
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<Set<string>>(new Set());

  // Normalize settings: could be array of {key,value} or object
  const settings: Setting[] = Array.isArray(rawSettings)
    ? (rawSettings as Setting[])
    : rawSettings
      ? Object.entries(rawSettings as Record<string, string>).map(([key, value]) => ({ key, value: String(value) }))
      : [];

  useEffect(() => {
    const map: Record<string, string> = {};
    for (const s of settings) map[s.key] = s.value;
    setEdits(map);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawSettings]);

  const { mutate: save, isPending } = useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) => admin.updateSetting(key, { value }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["admin", "settings"] });
      setSaved((p) => new Set(p).add(vars.key));
      setTimeout(() => setSaved((p) => { const n = new Set(p); n.delete(vars.key); return n; }), 2000);
    },
  });

  return (
    <DashboardShell>
      <PageHeader title="Settings" breadcrumbs={[{ label: "Dashboard", href: "/" }, { label: "Admin" }, { label: "Settings" }]} />

      {isLoading ? (
        <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16 w-full" />)}</div>
      ) : settings.length > 0 ? (
        <div className="space-y-3">
          {settings.map((s) => (
            <Card key={s.key}>
              <CardContent className="flex items-center gap-4 pt-4">
                <span className="text-sm font-medium min-w-[200px]">{s.key}</span>
                <Input
                  value={edits[s.key] ?? ""}
                  onChange={(e) => setEdits((p) => ({ ...p, [s.key]: e.target.value }))}
                  className="flex-1"
                />
                <Button
                  size="sm"
                  disabled={isPending || edits[s.key] === s.value}
                  onClick={() => save({ key: s.key, value: edits[s.key] })}
                >
                  {saved.has(s.key) ? <Check className="h-4 w-4" /> : "Save"}
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No settings configured.</p>
      )}
    </DashboardShell>
  );
}
