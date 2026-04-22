"use client";

import { useState, useCallback, useEffect } from "react";
import { Settings, Plus, Pencil, Trash2, Save, X, Loader2, Info, Database, Activity, BookOpen, Shield, HelpCircle, Eye } from "lucide-react";
import { toast } from "sonner";
import { useAdminSettings } from "@/hooks/use-api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { useRoleGuard } from "@/hooks/use-role-guard";
import type { AdminSetting } from "@/lib/types";
import { admin } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

function SettingRow({
  setting,
  onSaved,
  onDeleted,
  tooltip,
}: {
  setting: { key: string; value: string };
  onSaved: () => void;
  onDeleted: () => void;
  tooltip?: string;
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
      <span className="text-xs font-[family-name:var(--font-mono)] text-muted-foreground shrink-0 min-w-[220px] pt-1.5 select-all inline-flex items-center gap-1.5">
        {setting.key}
        {tooltip && (
          <Tooltip>
            <TooltipTrigger asChild>
              <HelpCircle className="h-3 w-3 text-muted-foreground/50 hover:text-muted-foreground transition-colors shrink-0 cursor-help" />
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-[280px] text-xs leading-relaxed">
              {tooltip}
            </TooltipContent>
          </Tooltip>
        )}
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

interface SettingDef {
  key: string;
  description: string;
  tooltip?: string;
}

interface SettingSection {
  title: string;
  icon: React.ReactNode;
  settings: SettingDef[];
}

const SETTING_SECTIONS: SettingSection[] = [
  {
    title: "Telemetry",
    icon: <Activity className="h-3.5 w-3.5" />,
    settings: [
      { key: "telemetry.otlp_endpoint", description: "OpenTelemetry collector endpoint" },
      { key: "telemetry.enabled", description: "Enable/disable telemetry collection" },
    ],
  },
  {
    title: "Registry",
    icon: <BookOpen className="h-3.5 w-3.5" />,
    settings: [
      { key: "registry.auto_approve", description: "Auto-approve new submissions" },
      { key: "registry.max_agents_per_user", description: "Maximum agents per user" },
    ],
  },
  {
    title: "Evaluation",
    icon: <Settings className="h-3.5 w-3.5" />,
    settings: [
      { key: "eval.default_window_size", description: "Default eval window size" },
    ],
  },
  {
    title: "Security",
    icon: <Shield className="h-3.5 w-3.5" />,
    settings: [
      { key: "hooks.auth_required", description: "Require auth for hook endpoints" },
    ],
  },
  {
    title: "Resource Tuning",
    icon: <Database className="h-3.5 w-3.5" />,
    settings: [
      {
        key: "resource.max_query_memory_mb",
        description: "Per-query memory limit in MB (default: 400)",
        tooltip: "Maximum memory a single ClickHouse query can use before it is killed. Set this below your container memory limit to prevent OOM crashes. Applied live via HTTP query parameters — no restart required.",
      },
      {
        key: "resource.group_by_spill_mb",
        description: "GROUP BY spill threshold in MB (default: 200)",
        tooltip: "When a GROUP BY aggregation exceeds this memory threshold, ClickHouse spills intermediate data to disk instead of consuming more RAM. Lower values reduce peak memory usage but may slow down large aggregation queries.",
      },
      {
        key: "resource.sort_spill_mb",
        description: "ORDER BY spill threshold in MB (default: 200)",
        tooltip: "When an ORDER BY sort exceeds this memory threshold, ClickHouse spills to disk. Prevents large result set sorting from consuming all available memory. Lower values trade query speed for memory safety.",
      },
      {
        key: "resource.join_memory_mb",
        description: "JOIN memory limit in MB (default: 100)",
        tooltip: "Maximum memory for hash JOIN operations. When exceeded, ClickHouse falls back to a partial-merge join algorithm which uses less memory but is slower. Critical for queries joining large tables.",
      },
    ],
  },
];

const ALL_DEFAULT_SETTINGS = SETTING_SECTIONS.flatMap((s) => s.settings);

export default function SettingsPage() {
  const { ready } = useRoleGuard("admin");
  const { data: settings, isLoading, isError, error, refetch } = useAdminSettings();
  const { deploymentMode, ssoEnabled, evalConfigured } = useDeploymentConfig();
  const [addingKey, setAddingKey] = useState("");
  const [addingValue, setAddingValue] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [applyingResources, setApplyingResources] = useState(false);
  const [tracePrivacy, setTracePrivacy] = useState(false);
  const [tracePrivacyLoading, setTracePrivacyLoading] = useState(true);
  const [tracePrivacyToggling, setTracePrivacyToggling] = useState(false);

  useEffect(() => {
    admin.getTracePrivacy()
      .then((res) => setTracePrivacy(res.trace_privacy))
      .catch(() => {})
      .finally(() => setTracePrivacyLoading(false));
  }, []);

  const handleTracePrivacyToggle = useCallback(async (checked: boolean) => {
    setTracePrivacyToggling(true);
    try {
      const res = await admin.setTracePrivacy(checked);
      setTracePrivacy(res.trace_privacy);
      toast.success(`Trace privacy ${res.trace_privacy ? "enabled" : "disabled"}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to update trace privacy");
    } finally {
      setTracePrivacyToggling(false);
    }
  }, []);

  const entries: { key: string; value: string }[] = Array.isArray(settings)
    ? settings.map((s: AdminSetting) => ({ key: s.key, value: s.value }))
    : Object.entries(settings ?? {}).map(([k, v]) => ({ key: k, value: String(v) }));

  const existingKeys = new Set(entries.map((e) => e.key));
  const missingSections = SETTING_SECTIONS
    .map((section) => ({
      ...section,
      settings: section.settings.filter((d) => !existingKeys.has(d.key)),
    }))
    .filter((section) => section.settings.length > 0);
  const hasMissingDefaults = missingSections.length > 0;

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

  const handleApplyResources = useCallback(async () => {
    setApplyingResources(true);
    try {
      const res = await admin.applyResources();
      const count = Object.keys(res.applied).length;
      if (count > 0) {
        toast.success(`Applied ${count} resource setting${count > 1 ? "s" : ""} to ClickHouse`);
      } else {
        toast.info("No resource settings configured yet. Add resource.* settings first.");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to apply resource settings");
    } finally {
      setApplyingResources(false);
    }
  }, []);

  const hasResourceSettings = entries.some((e) => e.key.startsWith("resource."));

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
      <div className="p-6 w-full mx-auto space-y-6">
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

        {/* Trace Privacy */}
        <section className="animate-in">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
            <Eye className="h-3.5 w-3.5" />
            Trace Privacy
          </h3>
          <div className="rounded-md border border-border bg-card px-4 py-3">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <p className="text-sm font-medium">Restrict trace visibility</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  When enabled, all users (including admins) can only see their own traces.
                  Super-admins always retain full visibility across all traces.
                </p>
              </div>
              <Switch
                checked={tracePrivacy}
                onCheckedChange={handleTracePrivacyToggle}
                disabled={tracePrivacyLoading || tracePrivacyToggling}
              />
            </div>
          </div>
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
                <TooltipProvider delayDuration={300}>
                  <div className="rounded-md border border-border bg-card px-4">
                    {entries.map((s) => (
                      <SettingRow
                        key={s.key}
                        setting={s}
                        onSaved={() => refetch()}
                        onDeleted={() => refetch()}
                        tooltip={ALL_DEFAULT_SETTINGS.find((d) => d.key === s.key)?.tooltip}
                      />
                    ))}
                  </div>
                </TooltipProvider>
              </section>
            )}

            {/* Resource Tuning */}
            {hasResourceSettings && (
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                  Resource Tuning
                </h3>
                <div className="rounded-md border border-border bg-card px-4 py-3">
                  <div className="flex items-start gap-3">
                    <Database className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                    <div className="flex-1">
                      <p className="text-xs text-muted-foreground">
                        Resource settings control ClickHouse memory limits for queries, aggregations, and joins.
                        After changing any <span className="font-[family-name:var(--font-mono)]">resource.*</span> setting above,
                        click apply to push the changes to ClickHouse without restarting.
                      </p>
                      <Button
                        size="sm"
                        variant="outline"
                        className="mt-3 h-8"
                        onClick={handleApplyResources}
                        disabled={applyingResources}
                      >
                        {applyingResources ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Database className="mr-1.5 h-3.5 w-3.5" />}
                        Apply Resource Settings
                      </Button>
                    </div>
                  </div>
                </div>
              </section>
            )}

            {/* Suggested defaults — grouped by section */}
            {hasMissingDefaults && (
              <TooltipProvider delayDuration={300}>
                {missingSections.map((section) => (
                  <section key={section.title}>
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
                      {section.icon}
                      {section.title}
                    </h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {section.settings.map((d) => (
                        <button
                          key={d.key}
                          type="button"
                          onClick={() => { setAddingKey(d.key); setAddingValue(""); setShowAdd(true); }}
                          className="text-left rounded-md border border-dashed border-border p-3 hover:bg-muted/30 transition-colors group/card"
                        >
                          <span className="flex items-center gap-1.5">
                            <span className="text-xs font-[family-name:var(--font-mono)] text-foreground">{d.key}</span>
                            {d.tooltip && (
                              <Tooltip>
                                <TooltipTrigger asChild onClick={(e) => e.stopPropagation()}>
                                  <HelpCircle className="h-3 w-3 text-muted-foreground/50 hover:text-muted-foreground transition-colors shrink-0" />
                                </TooltipTrigger>
                                <TooltipContent side="top" className="max-w-[280px] text-xs leading-relaxed">
                                  {d.tooltip}
                                </TooltipContent>
                              </Tooltip>
                            )}
                          </span>
                          <span className="block text-[11px] text-muted-foreground mt-0.5">{d.description}</span>
                        </button>
                      ))}
                    </div>
                  </section>
                ))}
              </TooltipProvider>
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
