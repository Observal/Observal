// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useState, useCallback } from "react";
import {
  Shield,
  Plus,
  Trash2,
  Loader2,
  CheckCircle2,
  XCircle,
  Copy,
  RefreshCw,
  KeyRound,
  Fingerprint,
} from "lucide-react";
import { toast } from "sonner";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { admin } from "@/lib/api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { useRoleGuard } from "@/hooks/use-role-guard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { PageHeader } from "@/components/layouts/page-header";
import { ErrorState } from "@/components/shared/error-state";

function SamlConfigSection() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin", "saml-config"],
    queryFn: admin.samlConfig,
  });

  const [deleting, setDeleting] = useState(false);

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

            {source === "database" && (
              <div className="pt-2 border-t border-border">
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
              </div>
            )}
            {source === "env" && (
              <p className="text-xs text-muted-foreground pt-2 border-t border-border">
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

function ScimTokensSection() {
  const queryClient = useQueryClient();
  const { data: tokens, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin", "scim-tokens"],
    queryFn: admin.scimTokens,
  });

  const [creating, setCreating] = useState(false);
  const [description, setDescription] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newToken, setNewToken] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const handleCreate = useCallback(async () => {
    setCreating(true);
    try {
      const result = await admin.createScimToken({ description: description || undefined });
      setNewToken(result.token);
      setDescription("");
      setShowCreate(false);
      toast.success("SCIM token created");
      queryClient.invalidateQueries({ queryKey: ["admin", "scim-tokens"] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create token");
    } finally {
      setCreating(false);
    }
  }, [description, queryClient]);

  const handleRevoke = useCallback(async (id: string) => {
    if (!confirm("Revoke this SCIM token? Any IdP using it will lose access immediately.")) return;
    setRevokingId(id);
    try {
      await admin.revokeScimToken(id);
      toast.success("SCIM token revoked");
      queryClient.invalidateQueries({ queryKey: ["admin", "scim-tokens"] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to revoke token");
    } finally {
      setRevokingId(null);
    }
  }, [queryClient]);

  const copyToken = useCallback(() => {
    if (newToken) {
      navigator.clipboard.writeText(newToken);
      toast.success("Token copied to clipboard");
    }
  }, [newToken]);

  if (isLoading) {
    return (
      <Card className="animate-pulse">
        <CardHeader className="pb-3">
          <div className="h-5 w-40 bg-muted rounded" />
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="h-4 w-64 bg-muted rounded" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return <ErrorState message={(error as Error)?.message} onRetry={() => refetch()} />;
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-sm">SCIM Provisioning Tokens</CardTitle>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => { setShowCreate(true); setNewToken(null); }}
          >
            <Plus className="h-3 w-3 mr-1" /> New Token
          </Button>
        </div>
        <CardDescription className="text-xs">
          Bearer tokens for SCIM 2.0 user provisioning from your identity provider.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {newToken && (
          <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3">
            <p className="text-xs font-medium text-emerald-600 mb-2">
              Save this token now. It will not be shown again.
            </p>
            <div className="flex items-center gap-2">
              <code className="text-xs font-mono bg-background px-2 py-1 rounded border flex-1 break-all select-all">
                {newToken}
              </code>
              <Button variant="outline" size="sm" className="h-7 shrink-0" onClick={copyToken}>
                <Copy className="h-3 w-3" />
              </Button>
            </div>
          </div>
        )}

        {showCreate && (
          <div className="rounded-md border border-border p-3 space-y-2">
            <Input
              placeholder="Token description (e.g., Okta SCIM)"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="h-8 text-sm"
              onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); }}
              autoFocus
            />
            <div className="flex gap-2">
              <Button size="sm" className="h-7 text-xs" onClick={handleCreate} disabled={creating}>
                {creating ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : null}
                Generate Token
              </Button>
              <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setShowCreate(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {tokens && tokens.length > 0 ? (
          <div className="divide-y divide-border">
            {tokens.map((token) => (
              <div key={token.id} className="flex items-center justify-between py-2.5 group">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium truncate">
                      {token.description || "Unnamed token"}
                    </span>
                    {token.active ? (
                      <Badge className="bg-emerald-500/15 text-emerald-600 border-emerald-500/20 text-[10px] px-1.5 py-0">
                        Active
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="text-[10px] px-1.5 py-0">Revoked</Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-[10px] text-muted-foreground font-mono">
                      {token.token_prefix}
                    </span>
                    {token.created_at && (
                      <span className="text-[10px] text-muted-foreground">
                        Created {new Date(token.created_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                </div>
                {token.active && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={() => handleRevoke(token.id)}
                    disabled={revokingId === token.id}
                  >
                    {revokingId === token.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive" />
                    )}
                  </Button>
                )}
              </div>
            ))}
          </div>
        ) : !showCreate ? (
          <div className="text-center py-4">
            <KeyRound className="h-6 w-6 text-muted-foreground/40 mx-auto mb-2" />
            <p className="text-xs text-muted-foreground">No SCIM tokens yet.</p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default function SsoPage() {
  const { ready } = useRoleGuard("admin");
  const { licensedFeatures } = useDeploymentConfig();

  if (!ready) return null;

  if (!licensedFeatures.includes("saml") && !licensedFeatures.includes("all")) {
    return (
      <>
        <PageHeader
          title="SSO & Provisioning"
          breadcrumbs={[{ label: "Admin" }, { label: "SSO" }]}
        />
        <div className="p-6">
          <Card>
            <CardContent className="py-12 text-center">
              <Shield className="h-10 w-10 text-muted-foreground/40 mx-auto mb-3" />
              <h3 className="text-sm font-medium">Enterprise Feature</h3>
              <p className="text-xs text-muted-foreground mt-1">
                SAML SSO and SCIM provisioning are available in enterprise deployments.
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
        title="SSO & Provisioning"
        breadcrumbs={[{ label: "Admin" }, { label: "SSO" }]}
        actionButtonsRight={
          <Button variant="outline" size="sm" asChild>
            <a href="/api/v1/sso/saml/metadata" target="_blank" rel="noopener noreferrer">
              <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
              SP Metadata XML
            </a>
          </Button>
        }
      />
      <div className="p-6 w-full mx-auto space-y-6">
        <SamlConfigSection />
        <ScimTokensSection />
      </div>
    </>
  );
}
