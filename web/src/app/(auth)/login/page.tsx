"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Telescope, Eye, EyeOff, ArrowRight, Loader2 } from "lucide-react";
import { auth, setApiKey } from "@/lib/api";
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
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  async function handleLogin() {
    setError("");
    setLoading(true);
    try {
      setApiKey(apiKey);
      await auth.login({ api_key: apiKey });
      router.push("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Invalid API key");
    } finally {
      setLoading(false);
    }
  }

  async function handleInit() {
    setError("");
    setLoading(true);
    try {
      const res = await auth.init({ username, password });
      setApiKey(res.api_key);
      router.push("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Initialization failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-dvh">
      {/* Left panel - branding */}
      <div className="hidden w-1/2 flex-col justify-between bg-primary p-10 text-primary-foreground lg:flex">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary-foreground/10">
            <Telescope className="h-4 w-4" />
          </div>
          <span className="text-lg font-semibold">Observal</span>
        </div>
        <div>
          <blockquote className="space-y-2">
            <p className="text-lg leading-relaxed opacity-90">
              Eval &amp; observability for agentic coding workflows. Trace every
              tool call, skill activation, and sandbox run across your team.
            </p>
            <footer className="text-sm opacity-60">Admin Console</footer>
          </blockquote>
        </div>
        <p className="text-xs opacity-40">
          © {new Date().getFullYear()} Observal
        </p>
      </div>

      {/* Right panel - form */}
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-sm">
          {/* Mobile logo */}
          <div className="mb-8 flex flex-col items-center gap-3 lg:items-start">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground lg:hidden">
              <Telescope className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-center text-xl font-semibold tracking-tight lg:text-left">
                {initMode ? "Initialize Observal" : "Sign in"}
              </h1>
              <p className="mt-1 text-center text-sm text-muted-foreground lg:text-left">
                {initMode
                  ? "Create the first admin account"
                  : "Enter your API key to access the admin console"}
              </p>
            </div>
          </div>

          {initMode ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleInit();
              }}
              className="space-y-4"
            >
              <div className="space-y-2">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  placeholder="admin"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  autoFocus
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
              {error && (
                <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {error}
                </div>
              )}
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
              <button
                type="button"
                className="w-full text-center text-sm text-muted-foreground hover:text-foreground"
                onClick={() => {
                  setInitMode(false);
                  setError("");
                }}
              >
                ← Already initialized? Sign in
              </button>
            </form>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleLogin();
              }}
              className="space-y-4"
            >
              <div className="space-y-2">
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
                    className="pr-10"
                  />
                  <button
                    type="button"
                    tabIndex={-1}
                    className="absolute right-0 top-0 flex h-full w-10 items-center justify-center text-muted-foreground hover:text-foreground"
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
                <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {error}
                </div>
              )}
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
              <button
                type="button"
                className="w-full text-center text-sm text-muted-foreground hover:text-foreground"
                onClick={() => {
                  setInitMode(true);
                  setError("");
                }}
              >
                First time? Initialize admin account
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
