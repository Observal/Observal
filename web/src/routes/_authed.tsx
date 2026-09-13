// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute, Outlet } from "@tanstack/react-router";
import { Suspense } from "react";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { RegistrySidebar } from "@/components/nav/registry-sidebar";
import { Toaster } from "@/components/ui/sonner";
import { AuthGuard } from "@/components/layouts/auth-guard";
import { HelpProvider } from "@/components/wiki/help-context";
import { MockRegistryData } from "@/components/dev/mock-registry-data";

function AuthedLayout() {
  return (
    <AuthGuard>
      <HelpProvider>
        <SidebarProvider>
          <RegistrySidebar />
          <SidebarInset>
            <Suspense fallback={<div className="flex h-screen w-full items-center justify-center" />}>
              <Outlet />
            </Suspense>
          </SidebarInset>
          <Toaster visibleToasts={1} />
          <MockRegistryData />
        </SidebarProvider>
      </HelpProvider>
    </AuthGuard>
  );
}

export const Route = createFileRoute("/_authed")({
  component: AuthedLayout,
});
