"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Eye, EyeOff, ArrowRight, Loader2, AlertCircle, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { auth, setTokens, setUserRole, getUserRole, setUserName, setUserEmail } from "@/lib/api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { ssoEnabled, ssoOnly, samlEnabled } = useDeploymentConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [ssoLoading, setSsoLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const hasToken = !!localStorage.getItem("observal_access_token");
    if (hasToken && getUserRole()) {
      router.replace("/");
    }
  }, [router]);

  useEffect(() => {
    const ssoCode = searchParams.get("code");

    if (ssoCode) {
      setLoading(true);
      window.history.replaceState({}, "", "/login");

      fetch("/api/v1/auth/exchange", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: ssoCode }),
      })
        .then(async (res) => {
          if (!res.ok) {
            const text = await res.text().catch(() => res.statusText);
            throw new Error(text);
          }
          return res.json();
        })
        .then((data: { access_token: string; refresh_token: string; user: { role: string; name: string; email: string } }) => {
          setTokens(data.access_token, data.refresh_token);
          setUserRole(data.user.role);
          setUserName(data.user.name);
          setUserEmail(data.user.email);
          toast.success("Signed in successfully via SSO");
          const nextPath = searchParams.get("next");
          const redirectTo = nextPath && nextPath.startsWith("/") ? nextPath : "/";
          router.push(redirectTo);
        })
        .catch((err) => {
          const msg = err instanceof Error ? err.message : "SSO sign-in failed";
          setError(msg);
          toast.error("SSO sign-in failed -- the code may have expired. Please try again.");
          setLoading(false);
        });
    } else if (searchParams.get("error")) {
      setError(searchParams.get("error") || "SSO Authentication Failed");
    }
  }, [searchParams, router]);

  useEffect(() => {
    const reason = searchParams.get("reason");
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
      toast.success("Signed in successfully");
      router.push("/");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Login failed";
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
      router.push("/");
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
    window.location.href = "/api/v1/auth/oauth/login";
  }

  if (mustChangePassword) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-surface-sunken p-6">
        <div className="w-full max-w-md">
          <div className="rounded-lg border bg-card shadow-sm">
            <div className="flex flex-col items-center gap-2 border-b px-8 pb-6 pt-8 animate-in">
              <h1 className="text-2xl font-semibold tracking-tight font-[family-name:var(--font-display)]">
                Observal
              </h1>
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
            <h1 className="text-2xl font-semibold tracking-tight font-[family-name:var(--font-display)]">
              Observal
            </h1>
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
                  <Button
                    type="button"
                    variant={ssoOnly ? "default" : "outline"}
                    className="w-full"
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
                )}

                {samlEnabled && (
                  <Button
                    type="button"
                    variant={ssoOnly ? "default" : "outline"}
                    className="w-full"
                    onClick={() => {
                      const nextParam = searchParams.get("next");
                      const samlUrl = nextParam && nextParam.startsWith("/")
                        ? `/api/v1/sso/saml/login?next=${encodeURIComponent(nextParam)}`
                        : "/api/v1/sso/saml/login";
                      window.location.href = samlUrl;
                    }}
                    disabled={loading || ssoLoading}
                  >
                    Sign in with SAML SSO
                  </Button>
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
