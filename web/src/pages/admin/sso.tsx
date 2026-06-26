// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import type { MouseEvent } from "react";
import {
  Shield,
  Trash2,
  Loader2,
  CheckCircle2,
  XCircle,
  MinusCircle,
  RefreshCw,
  Fingerprint,
  HelpCircle,
  Globe,
  ChevronDown,
  ChevronRight,
  PlayCircle,
} from "lucide-react";
import { toast } from "sonner";
import { useHelp } from "@/components/wiki/help-context";
import { SETTING_DOCS } from "@/lib/docs-map";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  admin,
  type HealthCheck,
  type ValidateResult,
  type E2eStatusResult,
} from "@/lib/api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { useAdminSettings, useAdminSettingsSchema } from "@/hooks/use-api";
import { useRoleGuard } from "@/hooks/use-role-guard";
import type { AdminSetting, AdminSettingDef } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/layouts/page-header";
import { ErrorState } from "@/components/shared/error-state";

function CheckIcon({ status }: { status: HealthCheck["status"] }) {
  if (status === "pass") return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />;
  if (status === "fail") return <XCircle className="h-3.5 w-3.5 text-destructive shrink-0" />;
  return <MinusCircle className="h-3.5 w-3.5 text-muted-foreground shrink-0" />;
}

// ── End-to-end test runner ─────────────────────────────────────────────
//
// Drives an interactive SSO test:
//   1. POST /admin/sso/e2e/<provider>/start -> returns {session_id, login_url}
//   2. window.open(login_url) so the admin authenticates at the real IdP
//   3. Poll /admin/sso/e2e/status/{session_id} every 2s until ok != null
//   4. Render checks via ChecksList
//
// Polling stops automatically when the session finishes, when the user clicks
// "Reset", or when the component unmounts. We also stop after 10 minutes (TTL
// of the server-side record) so a closed tab doesn't poll forever.

type E2eState =
  | { phase: "idle" }
  | { phase: "starting" }
  | {
      phase: "waiting";
      sessionId: string;
      loginUrl: string;
      elapsedSec: number;
    }
  | { phase: "done"; result: E2eStatusResult }
  | {
      phase: "error";
      message: string;
      hint?: string;
      checks?: HealthCheck[];
    };

// How long to wait before nudging the operator to check the IdP tab. Most
// real logins complete in <60s; if we're still waiting at 90s it's almost
// always because Okta showed an error and never redirected back.
const E2E_NUDGE_AFTER_SEC = 90;
const E2E_HARD_TIMEOUT_SEC = 5 * 60;

function useE2eRunner(
  provider: "oidc" | "saml",
  startFn: () => Promise<{
    success: boolean;
    session_id?: string;
    login_url?: string;
    error?: string;
    hint?: string;
    checks?: HealthCheck[];
  }>,
) {
  const [state, setState] = useState<E2eState>({ phase: "idle" });
  const pollTimer = useRef<number | null>(null);
  const idpWindow = useRef<Window | null>(null);
  const stopPolling = useCallback(() => {
    if (pollTimer.current != null) {
      window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const start = useCallback(async () => {
    console.debug(`[sso] e2e-${provider} start`);
    setState({ phase: "starting" });
    try {
      const res = await startFn();
      if (!res.success || !res.session_id || !res.login_url) {
        // Pre-flight failure: the backend ran all validators and one (or
        // more) failed BEFORE we ever sent the operator to the IdP. Show
        // them every check so they can fix all the misconfig at once.
        const msg = res.error || `Failed to start ${provider.toUpperCase()} test`;
        console.warn(`[sso] e2e-${provider} preflight failed`, res);
        toast.error(msg);
        setState({
          phase: "error",
          message: msg,
          hint: res.hint,
          checks: res.checks,
        });
        return;
      }
      const sessionId = res.session_id;
      const loginUrl = res.login_url;
      // Drop `noopener` so we can watch `win.closed`, if the operator
      // closes the IdP tab without us seeing a callback, that's almost
      // always because the IdP showed an error page.
      const win = window.open(loginUrl, "_blank");
      idpWindow.current = win;
      if (!win) {
        toast.warning(
          "Popup blocked. Allow popups for this site, then click 'Open Login Tab' below.",
        );
      }
      setState({ phase: "waiting", sessionId, loginUrl, elapsedSec: 0 });

      const startedAt = Date.now();
      pollTimer.current = window.setInterval(async () => {
        const elapsedSec = Math.floor((Date.now() - startedAt) / 1000);

        // Tab close detection: if the IdP tab was closed (e.g. the operator
        // saw an error page and gave up), bail immediately rather than
        // pretending the test is still in flight.
        const closed = idpWindow.current ? idpWindow.current.closed : false;
        if (closed && elapsedSec > 3) {
          stopPolling();
          // The callback may still be in flight; do one last status check
          // before declaring an error.
          try {
            const status = await admin.e2eStatus(sessionId);
            if (status.finished_at != null && status.ok != null) {
              setState({ phase: "done", result: status });
              return;
            }
          } catch {
            /* fall through */
          }
          setState({
            phase: "error",
            message: "IdP login tab was closed before the test completed.",
            hint: "The IdP probably showed an error page. Re-open the tab or start a new test to see what it said.",
          });
          return;
        }

        // Hard timeout: bail with a clear message instead of polling forever
        // when the IdP showed an error and the user left that tab open.
        if (elapsedSec > E2E_HARD_TIMEOUT_SEC) {
          stopPolling();
          setState({
            phase: "error",
            message: `Test session timed out after ${E2E_HARD_TIMEOUT_SEC / 60} minutes with no IdP redirect back.`,
            hint: "Check the IdP login tab, the most common cause is the IdP rejecting the test user (no client access, MFA loop, or invalid scopes).",
          });
          return;
        }

        // Keep elapsed counter live so the nudge UI updates.
        setState((prev) =>
          prev.phase === "waiting" ? { ...prev, elapsedSec } : prev,
        );

        try {
          const status = await admin.e2eStatus(sessionId);
          if (status.finished_at != null && status.ok != null) {
            stopPolling();
            console.info(`[sso] e2e-${provider} done`, {
              ok: status.ok,
              actor_email: status.actor_email,
            });
            setState({ phase: "done", result: status });
            if (status.ok) toast.success(`${provider.toUpperCase()} end-to-end test passed`);
            else {
              const firstFail = status.checks?.find((c) => c.status === "fail");
              toast.error(
                firstFail
                  ? `${provider.toUpperCase()} test failed at: ${firstFail.label}`
                  : `${provider.toUpperCase()} end-to-end test failed`,
              );
            }
          }
        } catch (e) {
          // 404 → server-side record is gone (TTL expired or never created).
          // Anything else → likely transient; keep polling and the hard
          // timeout above will eventually catch a real outage.
          const status = (e as { status?: number })?.status;
          if (status === 404) {
            stopPolling();
            setState({
              phase: "error",
              message: "Test session expired before completing.",
              hint: "The IdP probably showed an error and never redirected back. Check the IdP tab.",
            });
          } else {
            console.debug(`[sso] e2e-${provider} poll error`, e);
          }
        }
      }, 2000);
    } catch (e) {
      console.error(`[sso] e2e-${provider} start crashed`, e);
      const msg = e instanceof Error ? e.message : "Failed to start test";
      toast.error(msg);
      setState({ phase: "error", message: msg });
    }
  }, [provider, startFn, stopPolling]);

  const reset = useCallback(() => {
    stopPolling();
    setState({ phase: "idle" });
  }, [stopPolling]);

  return { state, start, reset };
}

function E2eTestRow({
  provider,
  start,
  disabled,
}: {
  provider: "oidc" | "saml";
  start: () => Promise<{
    success: boolean;
    session_id?: string;
    login_url?: string;
    error?: string;
    hint?: string;
  }>;
  disabled?: boolean;
}) {
  const { state, start: run, reset } = useE2eRunner(provider, start);
  const running = state.phase === "starting" || state.phase === "waiting";

  return (
    <div className="mt-3 border-t border-border pt-3 space-y-2">
      <div className="flex items-center gap-3">
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs"
          onClick={run}
          disabled={running || disabled}
        >
          {running ? (
            <Loader2 className="h-3 w-3 mr-1 animate-spin" />
          ) : (
            <PlayCircle className="h-3 w-3 mr-1" />
          )}
          End to End Test
        </Button>
        {state.phase === "waiting" && (
          <>
            <span className="text-xs text-muted-foreground inline-flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              Waiting for IdP login… <span className="font-mono">{state.elapsedSec}s</span>
            </span>
            <a
              href={state.loginUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-primary underline"
            >
              Open Login Tab
            </a>
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={reset}>
              Cancel
            </Button>
          </>
        )}
        {state.phase === "waiting" && state.elapsedSec >= E2E_NUDGE_AFTER_SEC && (
          <div className="w-full mt-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
            Still waiting after {state.elapsedSec}s. Check the IdP tab — if it shows an
            error (invalid client, redirect_uri, scope), click Cancel and try again
            after fixing the IdP config. The test page should redirect back
            automatically once login completes.
          </div>
        )}
        {state.phase === "done" && (
          <>
            <span className="inline-flex items-center gap-1 text-xs">
              {state.result.ok ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              ) : (
                <XCircle className="h-4 w-4 text-destructive" />
              )}
              {state.result.ok ? "End-to-end passed" : "End-to-end failed"}
              {state.result.actor_email && (
                <span className="text-muted-foreground ml-1">
                  · as {state.result.actor_email}
                </span>
              )}
            </span>
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={reset}>
              Run Again
            </Button>
          </>
        )}
        {state.phase === "error" && (
          <div className="w-full rounded-md border border-destructive/30 bg-destructive/10 p-3 text-xs space-y-2">
            <div className="flex items-start gap-2">
              <XCircle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <div className="font-medium text-destructive">{state.message}</div>
                {state.hint && (
                  <div className="mt-1 text-muted-foreground italic">{state.hint}</div>
                )}
              </div>
              <Button variant="ghost" size="sm" className="h-6 text-xs shrink-0" onClick={reset}>
                Reset
              </Button>
            </div>
            {state.checks && state.checks.length > 0 && (
              <ChecksList checks={state.checks} />
            )}
          </div>
        )}
      </div>
      <p className="text-[11px] text-muted-foreground leading-snug">
        Runs the real login flow against your IdP using a real test user. We
        validate every step (token exchange, signature, claims) but never issue
        a session, safe to run repeatedly.
      </p>
      {state.phase === "done" && state.result.checks?.length > 0 && (
        <ChecksList checks={state.result.checks} />
      )}
    </div>
  );
}

function ChecksList({ checks }: { checks: HealthCheck[] }) {
  const [expanded, setExpanded] = useState(false);
  if (!checks?.length) return null;
  const passes = checks.filter((c) => c.status === "pass").length;
  const fails = checks.filter((c) => c.status === "fail").length;
  const skips = checks.filter((c) => c.status === "skip").length;
  return (
    <div className="mt-2 border border-border rounded-md text-xs">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-muted/40"
      >
        <span className="inline-flex items-center gap-1">
          {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          {passes}/{checks.length} passed
          {fails > 0 && <span className="text-destructive ml-1">· {fails} failed</span>}
          {skips > 0 && <span className="text-muted-foreground ml-1">· {skips} skipped</span>}
        </span>
        <span className="text-muted-foreground">{expanded ? "Hide" : "Show"} details</span>
      </button>
      {expanded && (
        <ul className="divide-y divide-border">
          {checks.map((c) => (
            <li key={c.name} className="px-3 py-2">
              <div className="flex items-start gap-2">
                <CheckIcon status={c.status} />
                <div className="flex-1 min-w-0">
                  <div className="font-medium">{c.label}</div>
                  {c.message && <div className="text-muted-foreground mt-0.5">{c.message}</div>}
                  {c.hint && <div className="text-muted-foreground italic mt-0.5">Hint: {c.hint}</div>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const SSO_SETTING_GROUPS = [
  {
    id: "access",
    title: "Access policy",
    description: "Decide whether local password login stays available.",
    keys: ["deployment.sso_only"],
  },
  {
    id: "oidc",
    title: "OIDC / OAuth 2.0",
    description: "Client settings for providers like Okta, Entra ID, Google Workspace, Keycloak, and Auth0.",
    keys: ["oauth.client_id", "oauth.client_secret", "oauth.server_metadata_url"],
  },
  {
    id: "saml",
    title: "SAML 2.0",
    description: "Identity provider, service provider, and JIT provisioning settings for SAML login.",
    keys: [
      "saml.idp_entity_id",
      "saml.idp_sso_url",
      "saml.idp_slo_url",
      "saml.idp_x509_cert",
      "saml.idp_metadata_url",
      "saml.sp_entity_id",
      "saml.sp_acs_url",
      "saml.jit_provisioning",
      "saml.default_role",
      "saml.sp_key_encryption_password",
    ],
  },
];

const RESTART_REQUIRED_KEYS = new Set(["oauth.client_id", "oauth.client_secret", "oauth.server_metadata_url"]);
const SENSITIVE_SETTING_KEYS = new Set(["oauth.client_secret", "saml.idp_x509_cert", "saml.sp_key_encryption_password"]);
const MULTILINE_SETTING_KEYS = new Set(["saml.idp_x509_cert"]);
const REDACTED_VALUE = "**REDACTED**";
const DEFAULT_ROLE_OPTIONS = [
  { value: "user", label: "User" },
  { value: "reviewer", label: "Reviewer" },
  { value: "admin", label: "Admin" },
];

function normalizeSettings(settings: AdminSetting[] | Record<string, string> | undefined): AdminSetting[] {
  if (Array.isArray(settings)) return settings;
  return Object.entries(settings ?? {}).map(([key, value]) => ({ key, value: String(value) }));
}

function valueForDraft(def: AdminSettingDef, existing?: AdminSetting) {
  if (SENSITIVE_SETTING_KEYS.has(def.key) && (existing?.is_set || existing?.value === REDACTED_VALUE)) return "";
  return existing?.value || def.default || "";
}

function openHelpFromModifiedClick(event: MouseEvent, open: () => void) {
  if (!event.ctrlKey && !event.metaKey) return;
  event.preventDefault();
  event.stopPropagation();
  open();
}

function SsoSettingInput({
  def,
  existing,
  value,
  onChange,
  openHelp,
  helpActive,
}: {
  def: AdminSettingDef;
  existing?: AdminSetting;
  value: string;
  onChange: (value: string) => void;
  openHelp: (key: string) => void;
  helpActive: boolean;
}) {
  const isSensitive = existing?.is_sensitive || SENSITIVE_SETTING_KEYS.has(def.key);
  const isBool = def.default === "true" || def.default === "false";
  const isSecretSaved = isSensitive && (existing?.is_set || existing?.value === REDACTED_VALUE);
  const helpClass = helpActive && SETTING_DOCS[def.key] ? "rounded-md ring-2 ring-primary/60 ring-offset-2 ring-offset-background cursor-help" : "";

  return (
    <div
      className={`space-y-1.5 ${helpClass}`}
      onClickCapture={(event) => openHelpFromModifiedClick(event, () => openHelp(def.key))}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <label className="text-sm font-medium text-foreground" htmlFor={def.key}>{def.label}</label>
          <div className="text-[11px] font-mono text-muted-foreground">{def.key}</div>
        </div>
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            openHelp(def.key);
          }}
          aria-label={`Open help for ${def.label}`}
        >
          <HelpCircle className="h-3.5 w-3.5" />
        </button>
      </div>

      {isBool ? (
        <div className="flex h-9 items-center gap-2">
          <Switch checked={value.toLowerCase() === "true"} onCheckedChange={(checked) => onChange(String(checked))} />
          <span className="text-xs text-muted-foreground">{value.toLowerCase() === "true" ? "Enabled" : "Disabled"}</span>
        </div>
      ) : def.key === "saml.default_role" ? (
        <Select value={value || "user"} onValueChange={onChange}>
          <SelectTrigger id={def.key} className="h-9">
            <SelectValue placeholder="Choose default role" />
          </SelectTrigger>
          <SelectContent>
            {DEFAULT_ROLE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : MULTILINE_SETTING_KEYS.has(def.key) ? (
        <Textarea
          id={def.key}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={isSecretSaved ? "Saved. Enter replacement certificate" : "Paste PEM certificate"}
          className="min-h-28 font-mono text-xs"
        />
      ) : (
        <Input
          id={def.key}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={isSecretSaved ? "Saved. Enter replacement secret" : def.default || "Enter value"}
          type={isSensitive ? "password" : "text"}
          className="font-mono text-xs"
        />
      )}
    </div>
  );
}

function SsoSettingsSection() {
  const queryClient = useQueryClient();
  const helpCtx = useHelp();
  const { helpActive } = helpCtx;
  const { ssoEnabled } = useDeploymentConfig();
  const { data: settings } = useAdminSettings();
  const { data: schema = [] } = useAdminSettingsSchema();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [restartPending, setRestartPending] = useState(false);

  const settingsByKey = useMemo(() => {
    const map = new Map<string, AdminSetting>();
    for (const setting of normalizeSettings(settings)) map.set(setting.key, setting);
    return map;
  }, [settings]);

  const defsByKey = useMemo(() => {
    const map = new Map<string, AdminSettingDef>();
    for (const section of schema) {
      for (const setting of section.settings) map.set(setting.key, setting);
    }
    return map;
  }, [schema]);

  const initialValues = useMemo(() => {
    const values: Record<string, string> = {};
    for (const group of SSO_SETTING_GROUPS) {
      for (const key of group.keys) {
        const def = defsByKey.get(key);
        if (def) values[key] = valueForDraft(def, settingsByKey.get(key));
      }
    }
    return values;
  }, [defsByKey, settingsByKey]);

  useEffect(() => {
    setDrafts(initialValues);
  }, [initialValues]);

  const changedKeys = useMemo(
    () => Object.keys(drafts).filter((key) => drafts[key] !== (initialValues[key] ?? "")),
    [drafts, initialValues],
  );
  const hasUnsavedChanges = changedKeys.length > 0;
  const oidcSavedComplete = Boolean(
    (settingsByKey.get("oauth.client_id")?.value || "").trim() &&
    (settingsByKey.get("oauth.client_secret")?.is_set || settingsByKey.get("oauth.client_secret")?.value) &&
    (settingsByKey.get("oauth.server_metadata_url")?.value || "").trim(),
  );
  const savedNeedsRestart = restartPending || (oidcSavedComplete && !ssoEnabled);
  const status = hasUnsavedChanges
    ? { label: "Unsaved changes", className: "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400" }
    : savedNeedsRestart
      ? { label: "Saved, API restart required", className: "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400" }
      : ssoEnabled
        ? { label: "Live", className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" }
        : { label: "Saved", className: "border-border bg-muted/40 text-muted-foreground" };

  const setDraft = useCallback((key: string, value: string) => {
    setDrafts((current) => ({ ...current, [key]: value }));
  }, []);

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["admin", "settings"] });
    queryClient.invalidateQueries({ queryKey: ["admin", "saml-config"] });
    queryClient.invalidateQueries({ queryKey: ["config", "public"] });
  }, [queryClient]);

  const saveChanges = useCallback(async () => {
    if (!changedKeys.length) return;
    setSaving(true);
    try {
      await Promise.all(changedKeys.map((key) => admin.updateSetting(key, { value: drafts[key] ?? "" })));
      if (changedKeys.some((key) => RESTART_REQUIRED_KEYS.has(key))) setRestartPending(true);
      toast.success("SSO settings saved");
      refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save SSO settings");
    } finally {
      setSaving(false);
    }
  }, [changedKeys, drafts, refresh]);

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="text-sm">SSO settings</CardTitle>
            <CardDescription className="text-xs">
              Folded settings for SSO-only mode, OIDC, and SAML. Save once after editing.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${status.className}`}>{status.label}</span>
            <Button size="sm" onClick={saveChanges} disabled={!hasUnsavedChanges || saving}>
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save changes"}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {SSO_SETTING_GROUPS.map((group) => {
          const defs = group.keys.map((key) => defsByKey.get(key)).filter((def): def is AdminSettingDef => Boolean(def));
          if (!defs.length) return null;
          const dirtyCount = group.keys.filter((key) => changedKeys.includes(key)).length;
          const sectionHelpClass = helpActive ? "ring-2 ring-primary/60 ring-offset-2 ring-offset-background" : "";
          return (
            <details key={group.id} className={`group rounded-md border border-border bg-card ${sectionHelpClass}`}>
              <summary
                className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 hover:bg-muted/30"
                onClickCapture={(event) => openHelpFromModifiedClick(event, () => helpCtx.openHelp({ pageKey: "sso" }))}
              >
                <div>
                  <div className="text-sm font-medium">{group.title}</div>
                  <div className="text-xs text-muted-foreground">{group.description}</div>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  {dirtyCount > 0 && <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-amber-600 dark:text-amber-400">{dirtyCount} changed</span>}
                  <ChevronRight className="h-4 w-4 transition-transform group-open:rotate-90" />
                </div>
              </summary>
              <div className="grid grid-cols-1 gap-4 border-t border-border px-4 py-4 md:grid-cols-2">
                {defs.map((def) => (
                  <SsoSettingInput
                    key={def.key}
                    def={def}
                    existing={settingsByKey.get(def.key)}
                    value={drafts[def.key] ?? ""}
                    onChange={(value) => setDraft(def.key, value)}
                    openHelp={(key) => helpCtx.openHelp({ settingKey: key })}
                    helpActive={helpActive}
                  />
                ))}
              </div>
            </details>
          );
        })}
      </CardContent>
    </Card>
  );
}

function OidcConfigSection() {
  const { ssoEnabled } = useDeploymentConfig();
  const [validating, setValidating] = useState(false);
  const [result, setResult] = useState<ValidateResult | null>(null);

  const handleValidate = useCallback(async () => {
    console.debug("[sso] validate-oidc start");
    setValidating(true);
    setResult(null);
    try {
      const res = await admin.validateOidc();
      setResult(res);
      if (res.success) {
        console.info("[sso] validate-oidc ok", { latency_ms: res.latency_ms, issuer: res.issuer });
        toast.success("OIDC configuration is valid");
      } else {
        console.warn("[sso] validate-oidc fail", { error: res.error, hint: res.hint });
        toast.error(res.error || "OIDC validation failed");
      }
    } catch (e) {
      console.error("[sso] validate-oidc request failed", e);
      setResult({ success: false, error: e instanceof Error ? e.message : "Validation request failed" });
      toast.error("Failed to validate OIDC");
    } finally {
      setValidating(false);
    }
  }, []);

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-sm">OIDC / OAuth 2.0</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {ssoEnabled ? (
              <Badge className="bg-emerald-500/15 text-emerald-600 border-emerald-500/20">Active</Badge>
            ) : (
              <Badge variant="secondary">Not configured</Badge>
            )}
          </div>
        </div>
        <CardDescription className="text-xs">
          {ssoEnabled ? "Active after API startup" : "Save OIDC settings below, then restart the API"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={handleValidate}
            disabled={validating || !ssoEnabled}
          >
            {validating ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <RefreshCw className="h-3 w-3 mr-1" />}
            Validate
          </Button>
          {result && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex items-center gap-1 text-xs">
                    {result.success ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                    ) : (
                      <XCircle className="h-4 w-4 text-destructive" />
                    )}
                    {result.success ? "Connected" : "Failed"}
                    {result.latency_ms != null && (
                      <span className="text-muted-foreground">({result.latency_ms}ms)</span>
                    )}
                  </span>
                </TooltipTrigger>
                <TooltipContent side="right" className="max-w-xs">
                  {result.success ? (
                    <div className="space-y-1">
                      <p>Issuer: {result.issuer}</p>
                      <p className="text-muted-foreground">Server-side config verified. 100% validation is not possible — the final assertion exchange and per-user authorization are not visible server-side.</p>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      <p className="font-medium text-destructive">{result.error}</p>
                      {result.hint && <p className="text-muted-foreground">{result.hint}</p>}
                    </div>
                  )}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
        </div>
        {result?.checks && <ChecksList checks={result.checks} />}
        {ssoEnabled && (
          <E2eTestRow provider="oidc" start={() => admin.e2eOidcStart()} />
        )}
      </CardContent>
    </Card>
  );
}

function SamlConfigSection() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin", "saml-config"],
    queryFn: admin.samlConfig,
  });

  const [deleting, setDeleting] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validateResult, setValidateResult] = useState<ValidateResult | null>(null);

  const handleDelete = useCallback(async () => {
    if (!confirm("Delete SAML configuration? This will disable SAML SSO immediately.")) return;
    setDeleting(true);
    try {
      await admin.deleteSamlConfig();
      toast.success("SAML configuration deleted");
      queryClient.invalidateQueries({ queryKey: ["admin", "saml-config"] });
      queryClient.invalidateQueries({ queryKey: ["config", "public"] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete SAML config");
    } finally {
      setDeleting(false);
    }
  }, [queryClient]);

  const handleValidateSaml = useCallback(async () => {
    console.debug("[sso] validate-saml start");
    setValidating(true);
    setValidateResult(null);
    try {
      const res = await admin.validateSaml();
      setValidateResult(res);
      if (res.success) {
        console.info("[sso] validate-saml ok", { latency_ms: res.latency_ms, idp_entity_id: res.idp_entity_id });
        toast.success("SAML configuration is valid");
      } else {
        console.warn("[sso] validate-saml fail", { error: res.error, hint: res.hint });
        toast.error(res.error || "SAML validation failed");
      }
    } catch (e) {
      console.error("[sso] validate-saml request failed", e);
      setValidateResult({ success: false, error: e instanceof Error ? e.message : "Validation request failed" });
      toast.error("Failed to validate SAML");
    } finally {
      setValidating(false);
    }
  }, []);

  if (isLoading) {
    return (
      <Card className="animate-pulse">
        <CardHeader className="pb-3">
          <div className="h-5 w-40 bg-muted rounded" />
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="h-4 w-64 bg-muted rounded" />
            <div className="h-4 w-48 bg-muted rounded" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return <ErrorState message={(error as Error)?.message} onRetry={() => refetch()} />;
  }

  const configured = !!data?.configured;
  const source = data?.source as string;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Fingerprint className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-sm">SAML 2.0 Configuration</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {configured ? (
              <Badge className="bg-emerald-500/15 text-emerald-600 border-emerald-500/20">Active</Badge>
            ) : (
              <Badge variant="secondary">Not configured</Badge>
            )}
          </div>
        </div>
        {configured && (
          <CardDescription className="text-xs">
            Source: {source === "dynamic" ? "dynamic settings" : source === "database" ? "admin API" : String(source)}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        {configured ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-x-4 gap-y-2">
              <div className="text-xs text-muted-foreground">IdP Entity ID</div>
              <div className="text-xs font-mono break-all">{String(data?.idp_entity_id || "")}</div>
              <div className="text-xs text-muted-foreground">IdP SSO URL</div>
              <div className="text-xs font-mono break-all">{String(data?.idp_sso_url || "")}</div>
              {typeof data?.idp_slo_url === "string" && data.idp_slo_url && (
                <>
                  <div className="text-xs text-muted-foreground">IdP SLO URL</div>
                  <div className="text-xs font-mono break-all">{data.idp_slo_url}</div>
                </>
              )}
              <div className="text-xs text-muted-foreground">SP Entity ID</div>
              <div className="text-xs font-mono break-all">{String(data?.sp_entity_id || "")}</div>
              <div className="text-xs text-muted-foreground">SP ACS URL</div>
              <div className="text-xs font-mono break-all">{String(data?.sp_acs_url || "")}</div>
              <div className="text-xs text-muted-foreground">IdP Certificate</div>
              <div className="text-xs">
                {data?.has_idp_cert ? (
                  <span className="inline-flex items-center gap-1 text-emerald-600"><CheckCircle2 className="h-3 w-3" /> Present</span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-amber-500"><XCircle className="h-3 w-3" /> Missing</span>
                )}
              </div>
              <div className="text-xs text-muted-foreground">SP Key Pair</div>
              <div className="text-xs">
                {data?.has_sp_key ? (
                  <span className="inline-flex items-center gap-1 text-emerald-600"><CheckCircle2 className="h-3 w-3" /> Generated</span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-muted-foreground">Not generated</span>
                )}
              </div>
              <div className="text-xs text-muted-foreground">JIT Provisioning</div>
              <div className="text-xs">{data?.jit_provisioning ? "Enabled" : "Disabled"}</div>
              <div className="text-xs text-muted-foreground">Default Role</div>
              <div className="text-xs">{String(data?.default_role || "user")}</div>
            </div>

            <div className="pt-2 border-t border-border flex items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                onClick={handleValidateSaml}
                disabled={validating}
              >
                {validating ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <RefreshCw className="h-3 w-3 mr-1" />}
                Validate
              </Button>
              {validateResult && (
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="inline-flex items-center gap-1 text-xs">
                        {validateResult.success ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                        ) : (
                          <XCircle className="h-4 w-4 text-destructive" />
                        )}
                        {validateResult.success ? "Valid" : "Failed"}
                        {validateResult.latency_ms != null && (
                          <span className="text-muted-foreground">({validateResult.latency_ms}ms)</span>
                        )}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-xs">
                      {validateResult.success ? (
                        <div className="space-y-1">
                          <p>IdP: {validateResult.idp_entity_id}</p>
                          <p className="text-muted-foreground">Server-side config verified. 100% validation is not possible — a signed assertion cannot be replayed and per-user policies are not visible here.</p>
                        </div>
                      ) : (
                        <div className="space-y-1">
                          <p className="font-medium text-destructive">{validateResult.error}</p>
                          {validateResult.hint && <p className="text-muted-foreground">{validateResult.hint}</p>}
                        </div>
                      )}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              )}
              {source === "database" && (
                <Button
                  variant="destructive"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={handleDelete}
                  disabled={deleting}
                >
                  {deleting ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Trash2 className="h-3 w-3 mr-1" />}
                  Delete SAML Config
                </Button>
              )}
            </div>
            {validateResult?.checks && <ChecksList checks={validateResult.checks} />}
            <E2eTestRow
              provider="saml"
              start={() => admin.e2eSamlStart()}
              disabled={!configured}
            />
            {source === "dynamic" && (
              <p className="text-xs text-muted-foreground pt-2">
                Configured via dynamic settings below.
              </p>
            )}
          </div>
        ) : (
          <div className="text-center py-6">
            <Fingerprint className="h-8 w-8 text-muted-foreground/40 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">SAML SSO is not configured.</p>
            <p className="text-xs text-muted-foreground mt-1">
              Fill the SAML fields in SSO settings above.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function SsoPage() {
  const { ready } = useRoleGuard("admin");
  const { licensed, licensedFeatures } = useDeploymentConfig();
  const helpCtx = useHelp();

  if (!ready) return null;

  if (!licensed) {
    return (
      <>
        <PageHeader
          title="SSO"
          breadcrumbs={[{ label: "Admin" }, { label: "SSO" }]}
        />
        <div className="p-6">
          <Card>
            <CardContent className="py-12 text-center">
              <Shield className="h-10 w-10 text-muted-foreground/40 mx-auto mb-3" />
              <h3 className="text-sm font-medium">Enterprise Feature</h3>
              <p className="text-xs text-muted-foreground mt-1">
                SSO is available in enterprise deployments.
              </p>
            </CardContent>
          </Card>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="SSO"
        breadcrumbs={[{ label: "Admin" }, { label: "SSO" }]}
        actionButtonsRight={
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="text-muted-foreground hover:text-primary transition-colors"
              onClick={() => helpCtx.openHelp({ pageKey: "sso" })}
              title="SSO documentation"
            >
              <HelpCircle className="h-4 w-4" />
            </button>
            {(licensedFeatures.includes("saml") || licensedFeatures.includes("all")) && (
              <Button variant="outline" size="sm" asChild>
                <a href="/api/v1/sso/saml/metadata" target="_blank" rel="noopener noreferrer">
                  <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                  SP Metadata XML
                </a>
              </Button>
            )}
          </div>
        }
      />
      <div className="p-6 w-full mx-auto space-y-6">
        <SsoSettingsSection />
        <OidcConfigSection />
        {(licensedFeatures.includes("saml") || licensedFeatures.includes("all")) && <SamlConfigSection />}
      </div>
    </>
  );
}
