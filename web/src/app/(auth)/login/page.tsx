"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, ArrowRight, Loader2, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import { auth, setApiKey, setUserRole } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Mode = "login" | "register" | "api-key" | "reset-request" | "reset-confirm";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [apiKey, setKey] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

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

  async function handleRequestReset() {
    setError("");
    setLoading(true);
    try {
      await auth.requestReset({ email });
      toast.success("Check your server logs for the reset code");
      switchMode("reset-confirm");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Request failed";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleResetPassword() {
    setError("");
    setLoading(true);
    try {
      const res = await auth.resetPassword({ email, token: resetToken, new_password: newPassword });
      setApiKey(res.api_key);
      setUserRole(res.user.role);
      toast.success("Password reset successfully");
      router.push("/");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Reset failed";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

  const onSubmit =
    mode === "login" ? handlePasswordLogin
    : mode === "register" ? handleRegister
    : mode === "reset-request" ? handleRequestReset
    : mode === "reset-confirm" ? handleResetPassword
    : handleApiKeyLogin;

  return (
    <div className="flex min-h-dvh items-center justify-center bg-surface-sunken p-6">
      <div className="w-full max-w-md">
        <div className="rounded-lg border bg-card shadow-sm">
          {/* Brand header */}
          <div className="flex flex-col items-center gap-2 border-b px-8 pb-6 pt-8 animate-in">
            <h1 className="text-2xl font-semibold tracking-tight font-[family-name:var(--font-display)]">
              Observal
            </h1>
            <p className="text-sm text-muted-foreground">
              {mode === "register"
                ? "Create your account"
                : mode === "api-key"
                  ? "Sign in with API key"
                  : mode === "reset-request"
                    ? "Reset your password"
                    : mode === "reset-confirm"
                      ? "Enter your reset code"
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
              {/* Email + Password mode (login & register) */}
              {(mode === "login" || mode === "register") && (
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

              {/* API Key mode */}
              {mode === "api-key" && (
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

              {/* Reset request mode — enter email */}
              {mode === "reset-request" && (
                <div className="space-y-2 animate-in">
                  <Label htmlFor="reset-email">Email</Label>
                  <Input
                    id="reset-email"
                    type="email"
                    placeholder="you@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoFocus
                  />
                  <p className="text-xs text-muted-foreground">
                    A reset code will be logged to the server console.
                  </p>
                </div>
              )}

              {/* Reset confirm mode — enter code + new password */}
              {mode === "reset-confirm" && (
                <>
                  <div className="space-y-2 animate-in">
                    <Label htmlFor="reset-token">Reset Code</Label>
                    <Input
                      id="reset-token"
                      placeholder="e.g. A7X9B2"
                      value={resetToken}
                      onChange={(e) => setResetToken(e.target.value)}
                      required
                      autoFocus
                      className="font-[family-name:var(--font-mono)] tracking-widest uppercase"
                    />
                    <p className="text-xs text-muted-foreground">
                      Check your server logs for the 6-character code.
                    </p>
                  </div>
                  <div className="space-y-2 animate-in stagger-1">
                    <Label htmlFor="new-password">New Password</Label>
                    <div className="relative">
                      <Input
                        id="new-password"
                        type={showPassword ? "text" : "password"}
                        placeholder="Enter new password"
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
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

              {/* Error */}
              {error && (
                <div className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2.5 text-sm text-destructive animate-in">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* Submit */}
              <div className="animate-in stagger-2">
                <Button type="submit" disabled={loading} className="w-full">
                  {loading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <>
                      {mode === "register" ? "Create Account"
                        : mode === "reset-request" ? "Send Reset Code"
                        : mode === "reset-confirm" ? "Reset Password"
                        : "Sign in"}
                      <ArrowRight className="ml-1 h-4 w-4" />
                    </>
                  )}
                </Button>
              </div>

              {/* Mode switches */}
              <div className="animate-in stagger-3 space-y-2 text-center">
                {mode === "login" && (
                  <>
                    <button
                      type="button"
                      className="block w-full text-sm text-muted-foreground transition-colors hover:text-foreground"
                      onClick={() => switchMode("reset-request")}
                    >
                      Forgot password?
                    </button>
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
                {mode === "register" && (
                  <button
                    type="button"
                    className="block w-full text-sm text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => switchMode("login")}
                  >
                    Already have an account? Sign in
                  </button>
                )}
                {mode === "api-key" && (
                  <button
                    type="button"
                    className="block w-full text-sm text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => switchMode("login")}
                  >
                    Sign in with email instead
                  </button>
                )}
                {(mode === "reset-request" || mode === "reset-confirm") && (
                  <button
                    type="button"
                    className="block w-full text-sm text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => switchMode("login")}
                  >
                    Back to sign in
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
