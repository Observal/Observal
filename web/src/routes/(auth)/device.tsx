// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute } from "@tanstack/react-router";
import { Suspense, lazy } from "react";
import { Toaster } from "@/components/ui/sonner";

const DevicePage = lazy(() => import("@/pages/device"));

export type DeviceSearch = {
  code?: string;
};

function DeviceRoute() {
  return (
    <div className="min-h-dvh bg-background">
      <Suspense fallback={<div className="flex h-screen w-full items-center justify-center" />}>
        <DevicePage />
      </Suspense>
      <Toaster visibleToasts={1} />
    </div>
  );
}

export const Route = createFileRoute("/(auth)/device")({
  component: DeviceRoute,
  validateSearch: (search: Record<string, unknown>): DeviceSearch => ({
    code: (search.code as string) || undefined,
  }),
});
