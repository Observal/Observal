// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute } from "@tanstack/react-router";
import { Suspense, lazy } from "react";
import { Toaster } from "@/components/ui/sonner";

const RegisterPage = lazy(() => import("@/pages/register"));

export type RegisterSearch = {
  next?: string;
};

function RegisterRoute() {
  return (
    <div className="min-h-dvh bg-background">
      <Suspense fallback={<div className="flex h-screen w-full items-center justify-center" />}>
        <RegisterPage />
      </Suspense>
      <Toaster visibleToasts={1} />
    </div>
  );
}

export const Route = createFileRoute("/(auth)/register")({
  component: RegisterRoute,
  validateSearch: (search: Record<string, unknown>): RegisterSearch => ({
    next: (search.next as string) || undefined,
  }),
});
