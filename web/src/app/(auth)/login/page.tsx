"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Eye, EyeOff, ArrowRight, Loader2, AlertCircle, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { auth, setApiKey, setUserRole, getUserRole, setUserName, setUserEmail } from "@/lib/api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Mode = "login" | "register" | "api-key";

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { deploymentMode, ssoEnabled } = useDeploymentConfig();
  const isEnterprise = deploymentMode === "enterprise";
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [apiKey, setKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [ssoLoading, setSsoLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    // If the user is already authenticated, redirect to the home page
    if (typeof window !== "undefined" && getUserRole()) {
      router.replace("/");
    }
  }, [router]);

  useEffect(() => {
    // Handle one-time auth code from OAuth callback
    const ssoCode = searchParams.get("code");

    if (ssoCode) {
      setLoading(true);
      // Strip the code from the URL immediately to prevent leakage
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
        .then((data: { api_key: string; user: { role: string; name: string; email: string } }) => {
          setApiKey(data.api_key);
          setUserRole(data.user.role);
          setUserName(data.user.name);
          setUserEmail(data.user.email);
          toast.success("Signed in successfully via SSO");
          router.push("/");
        })
        .catch((err) => {
          const msg = err instanceof Error ? err.message : "SSO sign-in failed";
          setError(msg);
          toast.error("SSO sign-in failed — the code may have expired. Please try again.");
          setLoading(false);
        });
    } else if (searchParams.get("error")) {
      setError(searchParams.get("error") || "SSO Authentication Failed");
    }
  }, [searchParams, router]);

  // Show toast when redirected due to session expiry
  useEffect(() => {
    const reason = searchParams.get("reason");
    if (reason === "session_expired") {
      toast.info("Your session has expired. Please sign in again.");
      window.history.replaceState({}, "", "/login");
    }
  }, [searchParams]);

  // In enterprise mode, force login mode (SSO only)
  useEffect(() => {
    if (isEnterprise && mode !== "login") {
      setMode("login");
    }
  }, [isEnterprise, mode]);

  function switchMode(next: Mode) {
    setMode(next);
    setError("");
  }

  async function handlePasswordLogin() {
    setError("");
    setLoading(true);
    try {
      const res = await auth.login({ email, password });
      setApiKey(res.api_key);
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

  async function handleRegister() {
    setError("");
    setLoading(true);
    try {
      const res = await auth.register({ email, name, password });
      setApiKey(res.api_key);
      setUserRole(res.user.role);
      setUserName(res.user.name);
      setUserEmail(res.user.email);
      toast.success("Account created");
      router.push("/");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Registration failed";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleApiKeyLogin() {
    setError("");
    setLoading(true);
    try {
      const res = await auth.login({ api_key: apiKey });
      setApiKey(res.api_key);
      setUserRole(res.user.role);
      setUserName(res.user.name);
      setUserEmail(res.user.email);
      toast.success("Signed in successfully");
      router.push("/");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Invalid API key";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

  function handleSsoLogin() {
    setSsoLoading(true);
    // Redirects to backend SSO endpoint which initializes OAuth flow
    window.location.href = "/api/v1/auth/oauth/login";
  }

  const onSubmit =
    mode === "login" ? handlePasswordLogin
    : mode === "register" ? handleRegister
    : handleApiKeyLogin;

  return (
    <div className="flex min-h-dvh items-center justify-center bg-surface-sunken p-6">
      <div className="w-full max-w-md">
        <div className="rounded-lg border bg-card shadow-sm">
          {/* Brand header */}
          <div className="flex flex-col items-center gap-2 border-b px-8 pb-6 pt-8 animate-in">
            <h1 className="text-2xl font-semibold tracking-tight font-[family-name:var(--font
-display)]">
              Observal
            </h1>
            <p className="text-sm text-muted-foreground">
              {mode === "register"
                ? "Create your account"
                : mode === "api-key"
                  ? "Sign in with API key"
                  : "Sign in to your account"}
            </p>
          </div>

          {/* Form */}
          <div className="px-8 py-6">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                onSubmit();
              }}
              className="space-y-4"
            >
              {/* Email + Password mode (login & register) — hidden in enterprise mode */}
              {(mode === "login" || mode === "register") && !isEnterprise && (
                <>
                  <div className="space-y-2 animate-in">
                    <Label htmlFor="email">Email</Label>
                    <Input
                      id="email"
                      type="email"
                      placeholder="you@company.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      required
                      autoFocus
                    />
                  </div>
                  {mode === "register" && (
                    <div className="space-y-2 animate-in stagger-1">
                      <Label htmlFor="name">Name</Label>
                      <Input
                        id="name"
                        placeholder="Your Name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        required
                      />
                    </div>
                  )}
                  <div className="space-y-2 animate-in stagger-1">
                    <Label htmlFor="password">Password</Label>
                    <div className="relative">
                      <Input
                        id="password"
                        type={showPassword ? "text" : "password"}
                        placeholder={mode === "register" ? "Create a password" : "Enter password"}
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

              {/* API Key mode — hidden in enterprise mode */}
              {mode === "api-key" && !isEnterprise && (
                <div className="space-y-2 animate-in">
                  <Label htmlFor="api-key">API Key</Label>
                  <div className="relative">
                    <Input
                      id="api-key"
                      type={showPassword ? "text" : "password"}
                      placeholder="Paste your API key"
                      value={apiKey}
                      onChange={(e) => setKey(e.target.value)}
                      required
                      autoFocus
                      className="pr-10 font-[family-name:var(--font-mono)]"
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
              )}

              {/* Error */}
              {error && (
                <div className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2.5 text-sm text-destructive animate-in">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* Submit */}
              <div className="animate-in stagger-2 space-y-3">
                {/* In enterprise mode, hide all non-SSO submit buttons */}
                {!isEnterprise && (
                  <Button type="submit" disabled={loading || ssoLoading} className="w-full">
                    {loading && !ssoLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <>
                        {mode === "register" ? "Create Account" : "Sign in"}
                        <ArrowRight className="ml-1 h-4 w-4" />
                      </>
                    )}
                  </Button>
                )}

                {mode === "login" && !isEnterprise && (
                  <div className="relative py-2">
                    <div className="absolute inset-0 flex items-center">
                      <span className="w-full border-t" />
                    </div>
                    <div className="relative flex justify-center text-xs uppercase">
                      <span className="bg-card px-2 text-muted-foreground">Or</span>
                    </div>
                  </div>
                )}

                {mode === "login" && (isEnterprise || ssoEnabled) && (
                  <Button
                    type="button"
                    variant={isEnterprise ? "default" : "outline"}
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
              </div>

              {/* Mode switches */}
              <div className="animate-in stagger-3 space-y-2 text-center">
                {mode === "login" && !isEnterprise && (
                  <>
                    <p className="text-sm text-muted-foreground/60">
                      Forgot password? Contact your admin.
                    </p>
                    <button
                      type="button"
                      className="block w-full text-sm text-muted-foreground transition-colors hover:text-foreground"
                      onClick={() => switchMode("register")}
                    >
                      Don&apos;t have an account? Register
                    </button>
                    <button
                      type="button"
                      className="block w-full text-sm text-muted-foreground/60 transition-colors hover:text-foreground"
                      onClick={() => switchMode("api-key")}
                    >
                      Sign in with API key instead
                    </button>
                  </>
                )}
                {mode === "register" && !isEnterprise && (
                  <button
                    type="button"
                    className="block w-full text-sm text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => switchMode("login")}
                  >
                    Already have an account? Sign in
                  </button>
                )}
                {mode === "api-key" && !isEnterprise && (
                  <button
                    type="button"
                    className="block w-full text-sm text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => switchMode("login")}
                  >
                    Sign in with email instead
                  </button>
                )}
              </div>
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
