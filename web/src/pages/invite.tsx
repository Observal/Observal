// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

/**
 * Public invite acceptance page (/invite/$token).
 *
 * Previews the invite via the public lookup endpoint, then collects the
 * acceptor's details and creates their account in the inviting org with
 * the preassigned role. On success the user is logged in and redirected.
 */

import { Suspense, useState } from "react";
import { useRouter, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Eye, EyeOff, ArrowRight, Loader2, AlertCircle, MailX } from "lucide-react";
import { toast } from "sonner";
import {
  invites,
  setTokens,
  setUserRole,
  setUserName,
  setUserEmail,
  setUserUsername,
} from "@/lib/api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const INVALID_REASONS: Record<string, string> = {
  expired: "This invite has expired. Ask your admin to send a new one.",
  revoked: "This invite has been revoked. Ask your admin to send a new one.",
  accepted: "This invite has already been used.",
  not_found: "This invite link is invalid. Check the URL or ask your admin for a new one.",
};

function InviteContent() {
  const router = useRouter();
  const { token } = useParams({ from: "/(auth)/invite/$token" });
  const { brandingAppName, brandingLogo, brandingWordmark } = useDeploymentConfig();

  const lookup = useQuery({
    queryKey: ["invite-lookup", token],
    queryFn: () => invites.lookup(token),
    retry: false,
  });

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const pinnedEmail = lookup.data?.valid ? lookup.data.email : null;

  async function handleAccept() {
    setError("");
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    setLoading(true);
    try {
      const res = await invites.accept({
        token,
        email: pinnedEmail ?? email.trim(),
        name: name.trim(),
        username: username.trim() || undefined,
        password,
      });
      setTokens(res.access_token, res.refresh_token);
      setUserRole(res.user.role);
      setUserName(res.user.name);
      setUserEmail(res.user.email);
      if (res.user.username) setUserUsername(res.user.username);
      window.dispatchEvent(new Event("storage"));
      toast.success("Welcome aboard!");
      router.navigate({ to: "/", replace: true });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to accept invite";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

  const header = (
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
      {lookup.data?.valid && (
        <p className="text-sm text-muted-foreground text-center">
          You&apos;ve been invited to join{" "}
          <span className="font-medium text-foreground">{lookup.data.org_name || "the team"}</span>
          {lookup.data.role ? ` as ${lookup.data.role.replace("_", " ")}` : ""}
        </p>
      )}
    </div>
  );

  let body;
  if (lookup.isLoading) {
    body = (
      <div className="flex items-center justify-center px-8 py-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  } else if (lookup.isError || !lookup.data || !lookup.data.valid) {
    const reason = lookup.data?.reason ?? "not_found";
    body = (
      <div className="flex flex-col items-center gap-3 px-8 py-10 text-center animate-in">
        <MailX className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          {INVALID_REASONS[reason] ?? INVALID_REASONS.not_found}
        </p>
        <Button variant="outline" size="sm" onClick={() => router.navigate({ to: "/login" })}>
          Go to sign in
        </Button>
      </div>
    );
  } else {
    body = (
      <div className="px-8 py-6">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleAccept();
          }}
          className="space-y-4"
        >
          <div className="space-y-2 animate-in">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              placeholder="Jane Smith"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div className="space-y-2 animate-in stagger-1">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              placeholder="you@company.com"
              value={pinnedEmail ?? email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={!!pinnedEmail}
            />
            {pinnedEmail && (
              <p className="text-xs text-muted-foreground">This invite is pinned to this email address.</p>
            )}
          </div>
          <div className="space-y-2 animate-in stagger-1">
            <Label htmlFor="username">Username (optional)</Label>
            <Input
              id="username"
              placeholder="jane_smith"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="space-y-2 animate-in stagger-2">
            <Label htmlFor="password">Password</Label>
            <div className="relative">
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                placeholder="Choose a password"
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
          <div className="space-y-2 animate-in stagger-2">
            <Label htmlFor="confirm-password">Confirm Password</Label>
            <Input
              id="confirm-password"
              type={showPassword ? "text" : "password"}
              placeholder="Confirm password"
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

          <Button type="submit" disabled={loading} className="w-full animate-in stagger-3">
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                Join team
                <ArrowRight className="ml-1 h-4 w-4" />
              </>
            )}
          </Button>
        </form>
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-surface-sunken p-6">
      <div className="w-full max-w-md">
        <div className="rounded-lg border bg-card shadow-sm">
          {header}
          {body}
        </div>
      </div>
    </div>
  );
}

export default function InvitePage() {
  return (
    <Suspense>
      <InviteContent />
    </Suspense>
  );
}
