// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearch } from "@tanstack/react-router";
import { Eye, EyeOff, ArrowRight, Loader2, AlertCircle, RefreshCw, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { auth, config as configApi, setTokens, clearSession, setUserRole, getUserRole, setUserName, setUserEmail, setUserUsername, setUserAvatar } from "@/lib/api";
import type { SsoHealthResult } from "@/lib/api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearch({ from: "/(auth)/login" });
  const { ssoEnabled, ssoOnly, samlEnabled, brandingAppName, brandingLogo, brandingWordmark } = useDeploymentConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [ssoLoading, setSsoLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [ssoHealth, setSsoHealth] = useState<SsoHealthResult | null>(null);
  const [ssoHealthLoading, setSsoHealthLoading] = useState(false);

  useEffect(() => {
    if (!ssoEnabled && !samlEnabled) return;
    setSsoHealthLoading(true);
    configApi.ssoHealth()
      .then(setSsoHealth)
      .catch(() => {})
      .finally(() => setSsoHealthLoading(false));
  }, [ssoEnabled, samlEnabled]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    // Don't redirect to "/" if a SAML token exchange is pending
    const params = new URLSearchParams(window.location.search);
    if (params.get("saml_token") || params.get("code") || params.get("saml_code")) return;
    const hasToken = !!sessionStorage.getItem("observal_access_token");
    if (hasToken && getUserRole()) {
      router.navigate({ to: "/", replace: true });
    }
  }, [router]);

  useEffect(() => {
    const samlTokenId = searchParams.saml_token;
    if (samlTokenId) {
      setLoading(true);
      window.history.replaceState({}, "", "/login");

      (async () => {
        try {
          const res = await fetch(`/api/v1/sso/saml/exchange?token_id=${samlTokenId}`, {
            method: "POST",
          });
          if (!res.ok) throw new Error("Exchange failed");
          const data = await res.json();
          clearSession();
          setTokens(data.access_token, data.refresh_token);
          setUserRole(data.user.role);
          setUserName(data.user.name);
          setUserEmail(data.user.email);
          if (data.user.username) setUserUsername(data.user.username);
          window.dispatchEvent(new Event("storage"));
          const nextPath = searchParams.next;
          const redirectTo = nextPath && nextPath.startsWith("/") ? nextPath : "/";
          window.location.replace(redirectTo);
        } catch {
          setError("SAML sign-in failed. Please try again.");
          toast.error("SAML sign-in failed.");
          setLoading(false);
        }
      })();
      return;
    }

    const ssoCode = searchParams.code || searchParams.saml_code;

    if (ssoCode) {
      setLoading(true);
      window.history.replaceState({}, "", "/login");

      auth.exchangeCode({ code: ssoCode })
        .then((data) => {
          setTokens(data.access_token, data.refresh_token);
          setUserRole(data.user.role);
          setUserName(data.user.name);
          setUserEmail(data.user.email);
          if (data.user.username) setUserUsername(data.user.username);
          if (data.user.avatar_url) setUserAvatar(data.user.avatar_url);
          window.dispatchEvent(new Event("storage"));
          const nextPath = searchParams.next;
          const redirectTo = nextPath && nextPath.startsWith("/") ? nextPath : "/";
          window.location.href = redirectTo;
        })
        .catch((err) => {
          const msg = err instanceof Error ? err.message : "SSO sign-in failed";
          setError(msg);
          toast.error("SSO sign-in failed -- the code may have expired. Please try again.");
          setLoading(false);
        });
    } else if (searchParams.error) {
      setError(searchParams.error || "SSO Authentication Failed");
    }
  }, [searchParams, router]);

  useEffect(() => {
    const reason = searchParams.reason;
    if (reason === "session_expired") {
      toast.info("Your session has expired. Please sign in again.");
      window.history.replaceState({}, "", "/login");
    }
  }, [searchParams]);

  async function handlePasswordLogin() {
    setError("");
    setLoading(true);
    try {
      const res = await auth.login({ email, password });

      if (res.must_change_password) {
        setTokens(res.access_token, res.refresh_token);
        setMustChangePassword(true);
        setLoading(false);
        return;
      }

      setTokens(res.access_token, res.refresh_token);
      setUserRole(res.user.role);
      setUserName(res.user.name);
      setUserEmail(res.user.email);
      if (res.user.username) setUserUsername(res.user.username);
      if (res.user.avatar_url) setUserAvatar(res.user.avatar_url);
      toast.success("Signed in successfully");
      const nextPath = searchParams.next;
      router.navigate({ to: (nextPath && nextPath.startsWith("/") ? nextPath : "/") as "/" });
    } catch (e) {
      const raw = e instanceof Error ? e.message : "Login failed";
      const status = e instanceof Error ? (e as Error & { status?: number }).status : undefined;
      let msg = raw;
      if (status === 429 || raw.toLowerCase().includes("rate limit")) {
        msg = "Too many login attempts. Please wait a minute before trying again.";
      }
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleChangePassword() {
    setError("");
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    setLoading(true);
    try {
      await auth.changePassword({ current_password: password, new_password: newPassword });
      toast.success("Password changed successfully");
      const res = await auth.whoami();
      setUserRole(res.role);
      setUserName(res.name);
      setUserEmail(res.email);
      if (res.username) setUserUsername(res.username);
      if (res.avatar_url) setUserAvatar(res.avatar_url);
      router.navigate({ to: "/" });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to change password";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

  function handleSsoLogin() {
    setSsoLoading(true);
    const nextParam = searchParams.next;
    const url = nextParam && nextParam.startsWith("/")
      ? `/api/v1/auth/oauth/login?next=${encodeURIComponent(nextParam)}`
      : "/api/v1/auth/oauth/login";
    window.location.href = url;
  }

  if (mustChangePassword) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-surface-sunken p-6">
        <div className="w-full max-w-md">
          <div className="rounded-lg border bg-card shadow-sm">
            <div className="flex flex-col items-center gap-2 border-b px-8 pb-6 pt-8 animate-in">
              {brandingLogo ? (
                <img loading="lazy" src={brandingLogo} alt="" width={32} height={32} className="object-contain" />
              ) : (
                <img loading="lazy" src="/observal-logo.svg" alt="" width={32} height={32} className="object-contain" />
              )}
              {brandingWordmark ? (
                <img loading="lazy" src={brandingWordmark} alt={brandingAppName || "Observal"} width={192} height={24} className="h-6 max-w-48 object-contain" />
              ) : (
                <h1 className="text-2xl font-semibold tracking-tight font-[family-name:var(--font-display)]">
                  {brandingAppName || "Observal"}
                </h1>
              )}
              <p className="text-sm text-muted-foreground">
                You must change your password before continuing
              </p>
            </div>
            <div className="px-8 py-6">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleChangePassword();
                }}
                className="space-y-4"
              >
                <div className="space-y-2 animate-in">
                  <Label htmlFor="new-password">New Password</Label>
                  <div className="relative">
                    <Input
                      id="new-password"
                      type={showPassword ? "text" : "password"}
                      placeholder="Enter new password"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      required
                      autoFocus
                      className="pr-10"
                    />
                    <button
                      type="button"
                      tabIndex={-1}
                      className="absolute right-0 top-0 flex h-full w-10 items-center justify-center text-muted-foreground transition-colors hover:text-foreground"
                      onClick={() => setShowPassword(!showPassword)}
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
                <div className="space-y-2 animate-in stagger-1">
                  <Label htmlFor="confirm-password">Confirm Password</Label>
                  <Input
                    id="confirm-password"
                    type={showPassword ? "text" : "password"}
                    placeholder="Confirm new password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                  />
                </div>

                {error && (
                  <div className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2.5 text-sm text-destructive animate-in">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                )}

                <Button type="submit" disabled={loading} className="w-full">
                  {loading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <>
                      Change Password
                      <ArrowRight className="ml-1 h-4 w-4" />
                    </>
                  )}
                </Button>
              </form>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-surface-sunken p-6">
      <div className="w-full max-w-md">
        <div className="rounded-lg border bg-card shadow-sm">
          <div className="flex flex-col items-center gap-2 border-b px-8 pb-6 pt-8 animate-in">
            {brandingLogo ? (
              <img loading="lazy" src={brandingLogo} alt="" width={32} height={32} className="object-contain" />
            ) : (
              <img loading="lazy" src="/observal-logo.svg" alt="" width={32} height={32} className="object-contain" />
            )}
            {brandingWordmark ? (
              <img loading="lazy" src={brandingWordmark} alt={brandingAppName || "Observal"} width={192} height={24} className="h-6 max-w-48 object-contain" />
            ) : (
              <h1 className="text-2xl font-semibold tracking-tight font-[family-name:var(--font-display)]">
                {brandingAppName || "Observal"}
              </h1>
            )}
            <p className="text-sm text-muted-foreground">
              Sign in to your account
            </p>
          </div>

          <div className="px-8 py-6">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handlePasswordLogin();
              }}
              className="space-y-4"
            >
              {!ssoOnly && (
                <>
                  <div className="space-y-2 animate-in">
                    <Label htmlFor="email">Email or username</Label>
                    <Input
                      id="email"
                      type="text"
                      placeholder="you@company.com or username"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      required
                      autoFocus
                    />
                  </div>
                  <div className="space-y-2 animate-in stagger-1">
                    <Label htmlFor="password">Password</Label>
                    <div className="relative">
                      <Input
                        id="password"
                        type={showPassword ? "text" : "password"}
                        placeholder="Enter password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                        className="pr-10"
                      />
                      <button
                        type="button"
                        tabIndex={-1}
                        className="absolute right-0 top-0 flex h-full w-10 items-center justify-center text-muted-foreground transition-colors hover:text-foreground"
                        onClick={() => setShowPassword(!showPassword)}
                      >
                        {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    </div>
                  </div>
                </>
              )}

              {error && (
                <div className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2.5 text-sm text-destructive animate-in">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <div className="animate-in stagger-2 space-y-3">
                {!ssoOnly && (
                  <Button type="submit" disabled={loading || ssoLoading} className="w-full">
                    {loading && !ssoLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <>
                        Sign in
                        <ArrowRight className="ml-1 h-4 w-4" />
                      </>
                    )}
                  </Button>
                )}

                {!ssoOnly && (ssoEnabled || samlEnabled) && (
                  <div className="relative py-2">
                    <div className="absolute inset-0 flex items-center">
                      <span className="w-full border-t" />
                    </div>
                    <div className="relative flex justify-center text-xs uppercase">
                      <span className="bg-card px-2 text-muted-foreground">Or</span>
                    </div>
                  </div>
                )}

                {(ssoOnly || ssoEnabled) && (
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant={ssoOnly ? "default" : "outline"}
                      className="flex-1"
                      onClick={handleSsoLogin}
                      disabled={loading || ssoLoading}
                    >
                      {ssoLoading ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <RefreshCw className="mr-2 h-4 w-4" />
                      )}
                      Sign in with SSO
                    </Button>
                    {ssoHealthLoading ? (
                      <Loader2 className="h-5 w-5 shrink-0 animate-spin text-muted-foreground" />
                    ) : ssoHealth?.oidc && (
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="shrink-0">
                              {ssoHealth.oidc.ok ? (
                                <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                              ) : (
                                <XCircle className="h-5 w-5 text-destructive" />
                              )}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent side="right" className="max-w-xs text-xs">
                            {ssoHealth.oidc.ok
                              ? `OIDC config verified (${ssoHealth.oidc.latency_ms}ms) — does not test a full user login`
                              : ssoHealth.oidc.error}
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    )}
                  </div>
                )}

                {samlEnabled && (
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant={ssoOnly ? "default" : "outline"}
                      className="flex-1"
                      onClick={() => {
                        const nextParam = searchParams.next;
                        const samlUrl = nextParam && nextParam.startsWith("/")
                          ? `/api/v1/sso/saml/login?next=${encodeURIComponent(nextParam)}`
                          : "/api/v1/sso/saml/login";
                        window.location.href = samlUrl;
                      }}
                      disabled={loading || ssoLoading}
                    >
                      Sign in with SAML SSO
                    </Button>
                    {ssoHealthLoading ? (
                      <Loader2 className="h-5 w-5 shrink-0 animate-spin text-muted-foreground" />
                    ) : ssoHealth?.saml && (
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="shrink-0">
                              {ssoHealth.saml.ok ? (
                                <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                              ) : (
                                <XCircle className="h-5 w-5 text-destructive" />
                              )}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent side="right" className="max-w-xs text-xs">
                            {ssoHealth.saml.ok
                              ? `SAML config verified (${ssoHealth.saml.latency_ms}ms) — does not test a full user login`
                              : ssoHealth.saml.error}
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    )}
                  </div>
                )}
              </div>

              {!ssoOnly && (
                <div className="animate-in stagger-3 text-center">
                  <p className="text-sm text-muted-foreground/60">
                    Forgot password? Contact your admin.
                  </p>
                </div>
              )}
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginContent />
    </Suspense>
  );
}
