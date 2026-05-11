// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { Settings, Plus, Pencil, Trash2, Save, X, Loader2, Info, Database, Activity, BookOpen, Shield, HelpCircle, Eye, Upload, RotateCcw, Palette } from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { useAdminSettings } from "@/hooks/use-api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { useRoleGuard, hasMinRole } from "@/hooks/use-role-guard";
import type { AdminSetting } from "@/lib/types";
import { admin, getUserRole } from "@/lib/api";
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

const ALLOWED_LOGO_TYPES = ["image/png", "image/svg+xml", "image/x-icon", "image/vnd.microsoft.icon", "image/jpeg", "image/webp"];
const MAX_LOGO_SIZE = 2 * 1024 * 1024;

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
  const queryClient = useQueryClient();
  const { data: settings, isLoading, isError, error, refetch } = useAdminSettings();
  const { deploymentMode, ssoEnabled, samlEnabled, evalConfigured, brandingLogo, brandingAppName, brandingWordmark } = useDeploymentConfig();
  const [addingKey, setAddingKey] = useState("");
  const [addingValue, setAddingValue] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [applyingResources, setApplyingResources] = useState(false);
  const [tracePrivacy, setTracePrivacy] = useState(false);
  const [tracePrivacyLoading, setTracePrivacyLoading] = useState(true);
  const [tracePrivacyToggling, setTracePrivacyToggling] = useState(false);
  const [registeredAgentsOnly, setRegisteredAgentsOnly] = useState(false);
  const [registeredAgentsOnlyLoading, setRegisteredAgentsOnlyLoading] = useState(true);
  const [registeredAgentsOnlyToggling, setRegisteredAgentsOnlyToggling] = useState(false);
  const [logoOverride, setLogoOverride] = useState<string | null | undefined>(undefined);
  const [wordmarkOverride, setWordmarkOverride] = useState<string | null | undefined>(undefined);
  const [appNameOverride, setAppNameOverride] = useState<string | undefined>(undefined);
  const [brandingSaving, setBrandingSaving] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const wordmarkInputRef = useRef<HTMLInputElement>(null);

  const logoPreview = logoOverride !== undefined ? logoOverride : brandingLogo;
  const wordmarkPreview = wordmarkOverride !== undefined ? wordmarkOverride : brandingWordmark;
  const appNameDraft = appNameOverride !== undefined ? appNameOverride : (brandingAppName || "");

  useEffect(() => {
    admin.getTracePrivacy()
      .then((res) => setTracePrivacy(res.trace_privacy))
      .catch(() => {})
      .finally(() => setTracePrivacyLoading(false));
    if (hasMinRole(getUserRole(), "super_admin")) {
      admin.getRegisteredAgentsOnly()
        .then((res) => setRegisteredAgentsOnly(res.registered_agents_only))
        .catch(() => {})
        .finally(() => setRegisteredAgentsOnlyLoading(false));
    } else {
      setRegisteredAgentsOnlyLoading(false);
    }
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

  const handleRegisteredAgentsOnlyToggle = useCallback(async (checked: boolean) => {
    setRegisteredAgentsOnlyToggling(true);
    try {
      const res = await admin.setRegisteredAgentsOnly(checked);
      setRegisteredAgentsOnly(res.registered_agents_only);
      toast.success(`Registered agents only ${res.registered_agents_only ? "enabled" : "disabled"}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to update setting");
    } finally {
      setRegisteredAgentsOnlyToggling(false);
    }
  }, []);

  const handleImageFile = useCallback((file: File, setter: (v: string) => void) => {
    if (!ALLOWED_LOGO_TYPES.includes(file.type)) {
      toast.error("Unsupported file type. Use PNG, SVG, ICO, JPEG, or WEBP.");
      return;
    }
    if (file.size > MAX_LOGO_SIZE) {
      toast.error(`File too large (${Math.round(file.size / 1024)}KB). Maximum: 2MB.`);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setter(reader.result as string);
    reader.readAsDataURL(file);
  }, []);

  const handleSaveBranding = useCallback(async () => {
    setBrandingSaving(true);
    try {
      if (logoPreview !== brandingLogo) {
        await admin.updateSetting("branding.logo", { value: logoPreview || "" });
      }
      if (wordmarkPreview !== brandingWordmark) {
        await admin.updateSetting("branding.wordmark", { value: wordmarkPreview || "" });
      }
      const trimmedName = appNameDraft.trim();
      if (trimmedName !== (brandingAppName || "")) {
        await admin.updateSetting("branding.app_name", { value: trimmedName });
      }
      setLogoOverride(undefined);
      setWordmarkOverride(undefined);
      setAppNameOverride(undefined);
      queryClient.invalidateQueries({ queryKey: ["config", "public"] });
      toast.success("Branding updated");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save branding");
    } finally {
      setBrandingSaving(false);
    }
  }, [logoPreview, brandingLogo, wordmarkPreview, brandingWordmark, appNameDraft, brandingAppName, queryClient]);

  const handleResetBranding = useCallback(async () => {
    setBrandingSaving(true);
    try {
      await admin.updateSetting("branding.logo", { value: "" });
      await admin.updateSetting("branding.wordmark", { value: "" });
      await admin.updateSetting("branding.app_name", { value: "" });
      setLogoOverride(undefined);
      setWordmarkOverride(undefined);
      setAppNameOverride(undefined);
      queryClient.invalidateQueries({ queryKey: ["config", "public"] });
      toast.success("Branding reset to defaults");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to reset branding");
    } finally {
      setBrandingSaving(false);
    }
  }, [queryClient]);

  const hasBrandingChanges = logoPreview !== brandingLogo || wordmarkPreview !== brandingWordmark || appNameDraft.trim() !== (brandingAppName || "");

  const entries: { key: string; value: string }[] = (Array.isArray(settings)
    ? settings.map((s: AdminSetting) => ({ key: s.key, value: s.value }))
    : Object.entries(settings ?? {}).map(([k, v]) => ({ key: k, value: String(v) }))
  ).filter((e) => !e.key.startsWith("branding."));

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
              <span className="text-xs text-muted-foreground">SSO (OAuth/OIDC)</span>
              <span className={`text-xs font-medium ${ssoEnabled ? "text-success" : "text-muted-foreground"}`}>
                {ssoEnabled ? "Enabled" : "Disabled"}
              </span>
            </div>
            <div className="flex items-center justify-between py-1 border-t border-border">
              <span className="text-xs text-muted-foreground">SAML SSO</span>
              <span className={`text-xs font-medium ${samlEnabled ? "text-success" : "text-muted-foreground"}`}>
                {samlEnabled ? "Configured" : "Not configured"}
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

        {/* Branding */}
        <section className="animate-in">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
            <Palette className="h-3.5 w-3.5" />
            Branding
          </h3>
          <div className="rounded-md border border-border bg-card px-4 py-3 space-y-3">
            <p className="text-xs text-muted-foreground">
              PNG, SVG, ICO, JPEG, or WEBP. Max 2MB. Transparent images recommended for theme compatibility.
            </p>
            <div className="flex flex-wrap gap-4">
              {/* Logo icon */}
              <div className="space-y-1.5">
                <p className="text-xs font-medium">Icon</p>
                <div
                  className="w-12 h-12 rounded border-2 border-dashed border-border flex items-center justify-center cursor-pointer hover:border-primary/50 transition-colors bg-muted/30"
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleImageFile(f, setLogoOverride); }}
                >
                  {logoPreview ? (
                    <img src={logoPreview} alt="Icon" className="w-8 h-8 object-contain" />
                  ) : (
                    <Upload className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>
                <input ref={fileInputRef} type="file" accept="image/png,image/svg+xml,image/x-icon,image/jpeg,image/webp" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) handleImageFile(f, setLogoOverride); e.target.value = ""; }} />
                <div className="flex gap-1">
                  <Button variant="ghost" size="sm" className="h-6 text-[11px] px-1.5" onClick={() => fileInputRef.current?.click()}>Upload</Button>
                  {logoPreview && <Button variant="ghost" size="sm" className="h-6 text-[11px] px-1.5 text-muted-foreground" onClick={() => setLogoOverride(null)}>Remove</Button>}
                </div>
              </div>
              {/* Wordmark */}
              <div className="space-y-1.5">
                <p className="text-xs font-medium">Wordmark <span className="text-muted-foreground font-normal">(optional, replaces text)</span></p>
                <div
                  className="w-28 h-12 rounded border-2 border-dashed border-border flex items-center justify-center cursor-pointer hover:border-primary/50 transition-colors bg-muted/30"
                  onClick={() => wordmarkInputRef.current?.click()}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleImageFile(f, setWordmarkOverride); }}
                >
                  {wordmarkPreview ? (
                    <img src={wordmarkPreview} alt="Wordmark" className="h-6 max-w-24 object-contain" />
                  ) : (
                    <Upload className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>
                <input ref={wordmarkInputRef} type="file" accept="image/png,image/svg+xml,image/x-icon,image/jpeg,image/webp" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) handleImageFile(f, setWordmarkOverride); e.target.value = ""; }} />
                <div className="flex gap-1">
                  <Button variant="ghost" size="sm" className="h-6 text-[11px] px-1.5" onClick={() => wordmarkInputRef.current?.click()}>Upload</Button>
                  {wordmarkPreview && <Button variant="ghost" size="sm" className="h-6 text-[11px] px-1.5 text-muted-foreground" onClick={() => setWordmarkOverride(null)}>Remove</Button>}
                </div>
              </div>
              {/* App name (text fallback) */}
              <div className="space-y-1.5">
                <p className="text-xs font-medium">App Name <span className="text-muted-foreground font-normal">(used when no wordmark)</span></p>
                <Input
                  value={appNameDraft}
                  onChange={(e) => setAppNameOverride(e.target.value)}
                  placeholder="Observal"
                  maxLength={30}
                  className="h-8 text-sm w-48"
                />
                <p className="text-[11px] text-muted-foreground">{appNameDraft.length}/30</p>
              </div>
            </div>
            {/* Preview + actions */}
            <div className="flex items-center gap-4 pt-1 border-t border-border">
              <div className="rounded bg-sidebar px-3 py-2 inline-flex items-center gap-2">
                <div className="flex size-8 shrink-0 items-center justify-center">
                  {logoPreview ? (
                    <img src={logoPreview} alt="" className="w-5 h-5 object-contain" />
                  ) : (
                    <img src="/favicon.ico" alt="" className="w-5 h-5" />
                  )}
                </div>
                {wordmarkPreview ? (
                  <img src={wordmarkPreview} alt="" className="h-4 max-w-35 object-contain object-left" />
                ) : (
                  <span className="text-sm font-semibold tracking-tight font-display text-sidebar-foreground truncate max-w-35">
                    {appNameDraft.trim() || "Observal"}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" className="h-7 text-xs" onClick={handleSaveBranding} disabled={brandingSaving || !hasBrandingChanges}>
                  {brandingSaving ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Save className="mr-1 h-3 w-3" />}
                  Save
                </Button>
                {(brandingLogo || brandingAppName || brandingWordmark) && (
                  <Button size="sm" variant="outline" className="h-7 text-xs" onClick={handleResetBranding} disabled={brandingSaving}>
                    <RotateCcw className="mr-1 h-3 w-3" />
                    Reset
                  </Button>
                )}
              </div>
            </div>
          </div>
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

        {/* Registered Agents Only — super_admin only */}
        {hasMinRole(getUserRole(), "super_admin") && (
        <section className="animate-in">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
            <Shield className="h-3.5 w-3.5" />
            Registered Agents Only
          </h3>
          <div className="rounded-md border border-border bg-card px-4 py-3">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <p className="text-sm font-medium">Only trace registered agents</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  When enabled, only registered agents are traced. Unregistered agent
                  telemetry is stored as metadata-only (no content payloads).
                </p>
              </div>
              <Switch
                checked={registeredAgentsOnly}
                onCheckedChange={handleRegisteredAgentsOnlyToggle}
                disabled={registeredAgentsOnlyLoading || registeredAgentsOnlyToggling}
              />
            </div>
          </div>
        </section>
        )}

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
