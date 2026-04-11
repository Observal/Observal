"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, ArrowRight, Loader2, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import { auth, setApiKey, setUserRole } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const router = useRouter();
  const [apiKey, setKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [initMode, setInitMode] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");

  async function handleLogin() {
    setError("");
    setLoading(true);
    try {
      setApiKey(apiKey);
      const user = await auth.login({ api_key: apiKey });
      setUserRole(user.role);
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

  async function handleInit() {
    setError("");
    setLoading(true);
    try {
      const res = await auth.init({ email, name });
      setApiKey(res.api_key);
      setUserRole(res.user.role);
      toast.success("Admin account created");
      router.push("/");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Initialization failed";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

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
              {initMode
                ? "Create the first admin account"
                : "The agent registry for your team"}
            </p>
          </div>

          {/* Form */}
          <div className="px-8 py-6">
            {initMode ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleInit();
                }}
                className="space-y-4"
              >
                <div className="space-y-2 animate-in">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="admin@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoFocus
                  />
                </div>
                <div className="space-y-2 animate-in stagger-1">
                  <Label htmlFor="name">Name</Label>
                  <Input
                    id="name"
                    placeholder="Admin User"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                  />
                </div>
                {error && (
                  <div className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2.5 text-sm text-destructive animate-in">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                )}
                <div className="animate-in stagger-2">
                  <Button type="submit" disabled={loading} className="w-full">
                    {loading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <>
                        Create Admin Account
                        <ArrowRight className="ml-1 h-4 w-4" />
                      </>
                    )}
                  </Button>
                </div>
                <div className="animate-in stagger-3">
                  <button
                    type="button"
                    className="w-full text-center text-sm text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => {
                      setInitMode(false);
                      setError("");
                    }}
                  >
                    Already have a key? Sign in
                  </button>
                </div>
              </form>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleLogin();
                }}
                className="space-y-4"
              >
                <div className="space-y-2 animate-in">
                  <Label htmlFor="api-key">API Key</Label>
                  <div className="relative">
                    <Input
                      id="api-key"
                      type={showKey ? "text" : "password"}
                      placeholder="obs_..."
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
                      onClick={() => setShowKey(!showKey)}
                    >
                      {showKey ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>
                {error && (
                  <div className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2.5 text-sm text-destructive animate-in">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                )}
                <div className="animate-in stagger-1">
                  <Button type="submit" disabled={loading} className="w-full">
                    {loading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <>
                        Sign in
                        <ArrowRight className="ml-1 h-4 w-4" />
                      </>
                    )}
                  </Button>
                </div>
                <div className="animate-in stagger-2">
                  <button
                    type="button"
                    className="w-full text-center text-sm text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => {
                      setInitMode(true);
                      setError("");
                    }}
                  >
                    First time? Create admin account
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
