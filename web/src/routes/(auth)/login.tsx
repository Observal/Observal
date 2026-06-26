// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute } from "@tanstack/react-router";
import { Suspense, lazy } from "react";
import { Toaster } from "@/components/ui/sonner";

const LoginPage = lazy(() => import("@/pages/login"));

export type LoginSearch = {
  next?: string;
  saml_token?: string;
  code?: string;
  saml_code?: string;
  error?: string;
  reason?: string;
  sso_error?: string;
  sso?: string;
};

function LoginRoute() {
  return (
    <div className="min-h-dvh bg-background">
      <Suspense fallback={<div className="flex h-screen w-full items-center justify-center" />}>
        <LoginPage />
      </Suspense>
      <Toaster visibleToasts={1} />
    </div>
  );
}

export const Route = createFileRoute("/(auth)/login")({
  component: LoginRoute,
  validateSearch: (search: Record<string, unknown>): LoginSearch => ({
    next: (search.next as string) || undefined,
    saml_token: (search.saml_token as string) || undefined,
    code: (search.code as string) || undefined,
    saml_code: (search.saml_code as string) || undefined,
    error: (search.error as string) || undefined,
    reason: (search.reason as string) || undefined,
    sso_error: (search.sso_error as string) || undefined,
    sso: (search.sso as string) || undefined,
  }),
});
