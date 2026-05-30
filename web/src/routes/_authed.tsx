// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute, Outlet } from "@tanstack/react-router";
import { Suspense } from "react";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { RegistrySidebar } from "@/components/nav/registry-sidebar";
import { CommandMenu } from "@/components/nav/command-menu";
import { Toaster } from "@/components/ui/sonner";
import { AuthGuard } from "@/components/layouts/auth-guard";

function AuthedLayout() {
  return (
    <AuthGuard>
      <SidebarProvider>
        <RegistrySidebar />
        <SidebarInset>
          <Suspense fallback={<div className="flex h-screen w-full items-center justify-center" />}>
            <Outlet />
          </Suspense>
        </SidebarInset>
        <CommandMenu />
        <Toaster visibleToasts={1} />
      </SidebarProvider>
    </AuthGuard>
  );
}

export const Route = createFileRoute("/_authed")({
  component: AuthedLayout,
});
