"use client";

import { useState, useCallback } from "react";
import { Settings, Plus, Pencil, Trash2, Save, X, Loader2, Info } from "lucide-react";
import { toast } from "sonner";
import { useAdminSettings } from "@/hooks/use-api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { useRoleGuard } from "@/hooks/use-role-guard";
import type { AdminSetting } from "@/lib/types";
import { admin } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";

function SettingRow({
  setting,
  onSaved,
  onDeleted,
}: {
  setting: { key: string; value: string };
  onSaved: () => void;
  onDeleted: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(setting.value);
  const [saving, setSaving] = useState(false);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await admin.updateSetting(setting.key, { value });
      toast.success(`Updated ${setting.key}`);
      setEditing(false);
      onSaved();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }, [setting.key, value, onSaved]);

  const handleDelete = useCallback(async () => {
    setSaving(true);
    try {
      await admin.updateSetting(setting.key, { value: "" });
      toast.success(`Deleted ${setting.key}`);
      onDeleted();
    } catch {
      toast.error("Failed to delete");
    } finally {
      setSaving(false);
    }
  }, [setting.key, onDeleted]);

  return (
    <div className="flex items-start gap-4 py-3 border-b border-border last:border-b-0 group">
      <span className="text-xs font-[family-name:var(--font-mono)] text-muted-foreground shrink-0 min-w-[220px] pt-1.5 select-all">
        {setting.key}
      </span>
      {editing ? (
        <div className="flex items-center gap-2 flex-1">
          <Input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="h-8 text-sm flex-1"
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
              if (e.key === "Escape") { setEditing(false); setValue(setting.value); }
            }}
            autoFocus
          />
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={handleSave} disabled={saving}>
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          </Button>
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={() => { setEditing(false); setValue(setting.value); }}>
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-2 flex-1">
          <span className="text-sm text-foreground break-all flex-1">{setting.value || <span className="text-muted-foreground italic">empty</span>}</span>
          <div className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
            <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => setEditing(true)}>
              <Pencil className="h-3 w-3 text-muted-foreground" />
            </Button>
            <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={handleDelete}>
              <Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

const DEFAULT_SETTINGS = [
  { key: "telemetry.otlp_endpoint", description: "OpenTelemetry collector endpoint" },
  { key: "telemetry.enabled", description: "Enable/disable telemetry collection" },
  { key: "registry.auto_approve", description: "Auto-approve new submissions" },
  { key: "registry.max_agents_per_user", description: "Maximum agents per user" },
  { key: "eval.default_window_size", description: "Default eval window size" },
  { key: "hooks.auth_required", description: "Require auth for hook endpoints" },
];

export default function SettingsPage() {
  const { ready } = useRoleGuard("super_admin");
  const { data: settings, isLoading, isError, error, refetch } = useAdminSettings();
  const { deploymentMode, ssoEnabled, evalConfigured } = useDeploymentConfig();
  const [addingKey, setAddingKey] = useState("");
  const [addingValue, setAddingValue] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);

  const entries: { key: string; value: string }[] = Array.isArray(settings)
    ? settings.map((s: AdminSetting) => ({ key: s.key, value: s.value }))
    : Object.entries(settings ?? {}).map(([k, v]) => ({ key: k, value: String(v) }));

  const existingKeys = new Set(entries.map((e) => e.key));
  const missingDefaults = DEFAULT_SETTINGS.filter((d) => !existingKeys.has(d.key));

  const handleAdd = useCallback(async () => {
    if (!addingKey.trim()) return;
    setSaving(true);
    try {
      await admin.updateSetting(addingKey.trim(), { value: addingValue });
      toast.success(`Added ${addingKey.trim()}`);
      setAddingKey("");
      setAddingValue("");
      setShowAdd(false);
      refetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to add setting");
    } finally {
      setSaving(false);
    }
  }, [addingKey, addingValue, refetch]);

  if (!ready) return null;

  return (
    <>
      <PageHeader
        title="Settings"
        breadcrumbs={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Settings" },
        ]}
        actionButtonsRight={
          <Button size="sm" variant="outline" onClick={() => setShowAdd(true)} className="h-8">
            <Plus className="mr-1 h-3.5 w-3.5" /> Add Setting
          </Button>
        }
      />
      <div className="p-6 w-full max-w-4xl mx-auto space-y-6">
        {/* System Overview */}
        <section className="animate-in">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            System Overview
          </h3>
          <div className="rounded-md border border-border bg-card px-4 py-3 space-y-2">
            <div className="flex items-center justify-between py-1">
              <span className="text-xs text-muted-foreground">Deployment Mode</span>
              <span className="text-xs font-medium font-[family-name:var(--font-mono)]">
                {deploymentMode}
              </span>
            </div>
            <div className="flex items-center justify-between py-1 border-t border-border">
              <span className="text-xs text-muted-foreground">SSO</span>
              <span className={`text-xs font-medium ${ssoEnabled ? "text-success" : "text-muted-foreground"}`}>
                {ssoEnabled ? "Enabled" : "Disabled"}
              </span>
            </div>
            <div className="flex items-center justify-between py-1 border-t border-border">
              <span className="text-xs text-muted-foreground">Eval Model</span>
              <span className={`text-xs font-medium ${evalConfigured ? "text-success" : "text-amber-500"}`}>
                {evalConfigured ? "Configured" : "Not configured"}
              </span>
            </div>
          </div>
          {deploymentMode === "enterprise" && (
            <div className="flex items-start gap-2 mt-2 text-xs text-muted-foreground">
              <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>Enterprise mode is active. Self-registration and password login are disabled.</span>
            </div>
          )}
        </section>

        {isLoading ? (
          <TableSkeleton rows={5} cols={2} />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : (
          <div className="animate-in space-y-6">
            {/* Add new setting form */}
            {showAdd && (
              <div className="rounded-md border border-primary/30 bg-primary/5 p-4 space-y-3">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">New Setting</h4>
                <div className="flex gap-3">
                  <Input
                    placeholder="setting.key"
                    value={addingKey}
                    onChange={(e) => setAddingKey(e.target.value)}
                    className="h-8 text-sm max-w-[260px] font-[family-name:var(--font-mono)]"
                    autoFocus
                  />
                  <Input
                    placeholder="value"
                    value={addingValue}
                    onChange={(e) => setAddingValue(e.target.value)}
                    className="h-8 text-sm flex-1"
                    onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                  />
                  <Button size="sm" className="h-8" onClick={handleAdd} disabled={saving || !addingKey.trim()}>
                    {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save"}
                  </Button>
                  <Button size="sm" variant="ghost" className="h-8" onClick={() => setShowAdd(false)}>
                    Cancel
                  </Button>
                </div>
              </div>
            )}

            {/* Current settings */}
            {entries.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                  Active Settings
                </h3>
                <div className="rounded-md border border-border bg-card px-4">
                  {entries.map((s) => (
                    <SettingRow key={s.key} setting={s} onSaved={() => refetch()} onDeleted={() => refetch()} />
                  ))}
                </div>
              </section>
            )}

            {/* Suggested defaults */}
            {missingDefaults.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                  Suggested Settings
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {missingDefaults.map((d) => (
                    <button
                      key={d.key}
                      type="button"
                      onClick={() => { setAddingKey(d.key); setAddingValue(""); setShowAdd(true); }}
                      className="text-left rounded-md border border-dashed border-border p-3 hover:bg-muted/30 transition-colors"
                    >
                      <span className="block text-xs font-[family-name:var(--font-mono)] text-foreground">{d.key}</span>
                      <span className="block text-[11px] text-muted-foreground mt-0.5">{d.description}</span>
                    </button>
                  ))}
                </div>
              </section>
            )}

            {entries.length === 0 && !showAdd && (
              <div className="text-center py-12">
                <Settings className="h-8 w-8 text-muted-foreground/40 mx-auto mb-3" />
                <h3 className="text-sm font-medium">No settings configured</h3>
                <p className="text-xs text-muted-foreground mt-1">Click suggested settings below or add your own.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
