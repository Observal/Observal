// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useState, useCallback } from "react";
import {
  Shield,
  Trash2,
  Loader2,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Fingerprint,
  HelpCircle,
  Globe,
} from "lucide-react";
import { toast } from "sonner";
import { useHelp } from "@/components/wiki/help-context";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { admin } from "@/lib/api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { useRoleGuard } from "@/hooks/use-role-guard";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { PageHeader } from "@/components/layouts/page-header";
import { ErrorState } from "@/components/shared/error-state";

type ValidateResult = {
  success: boolean;
  error?: string;
  hint?: string;
  latency_ms?: number;
  issuer?: string;
  idp_entity_id?: string;
};

function OidcConfigSection() {
  const { ssoEnabled } = useDeploymentConfig();
  const [validating, setValidating] = useState(false);
  const [result, setResult] = useState<ValidateResult | null>(null);

  const handleValidate = useCallback(async () => {
    setValidating(true);
    setResult(null);
    try {
      const res = await admin.validateOidc();
      setResult(res);
      if (res.success) {
        toast.success("OIDC configuration is valid");
      } else {
        toast.error(res.error || "OIDC validation failed");
      }
    } catch (e) {
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
          {ssoEnabled ? "Configured via environment variables" : "Set OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, and OAUTH_SERVER_METADATA_URL"}
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
                      <p className="text-muted-foreground">Server-side config verified (discovery, redirect URI, client secret, email scope). Does not test a full user login.</p>
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
    setValidating(true);
    setValidateResult(null);
    try {
      const res = await admin.validateSaml();
      setValidateResult(res);
      if (res.success) {
        toast.success("SAML configuration is valid");
      } else {
        toast.error(res.error || "SAML validation failed");
      }
    } catch (e) {
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
            Source: {source === "env" ? "environment variables" : source === "database" ? "admin API" : String(source)}
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
                          <p className="text-muted-foreground">Server-side config verified (settings build, AuthnRequest, IdP cert match). Does not test a full user login.</p>
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
            {source === "env" && (
              <p className="text-xs text-muted-foreground pt-2">
                Configured via environment variables. Use the admin API to override with database-stored config.
              </p>
            )}
          </div>
        ) : (
          <div className="text-center py-6">
            <Fingerprint className="h-8 w-8 text-muted-foreground/40 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">SAML SSO is not configured.</p>
            <p className="text-xs text-muted-foreground mt-1">
              Set SAML_IDP_ENTITY_ID, SAML_IDP_SSO_URL, and SAML_IDP_X509_CERT environment variables, or use the admin API.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function SsoPage() {
  const { ready } = useRoleGuard("admin");
  const { licensedFeatures } = useDeploymentConfig();
  const helpCtx = useHelp();

  if (!ready) return null;

  if (!licensedFeatures.includes("saml") && !licensedFeatures.includes("all")) {
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
                SAML SSO is available in enterprise deployments.
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
            <Button variant="outline" size="sm" asChild>
              <a href="/api/v1/sso/saml/metadata" target="_blank" rel="noopener noreferrer">
                <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                SP Metadata XML
              </a>
            </Button>
          </div>
        }
      />
      <div className="p-6 w-full mx-auto space-y-6">
        <OidcConfigSection />
        <SamlConfigSection />
      </div>
    </>
  );
}
