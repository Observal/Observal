// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute, Outlet } from "@tanstack/react-router";
import { Suspense } from "react";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { RegistrySidebar } from "@/components/nav/registry-sidebar";
import { CommandMenu } from "@/components/nav/command-menu";
import { Toaster } from "@/components/ui/sonner";
import { AuthGuard } from "@/components/layouts/auth-guard";
import { HelpProvider } from "@/components/wiki/help-context";

function AuthedLayout() {
  return (
    <AuthGuard>
      <HelpProvider>
        <SidebarProvider className="bg-surface-sunken">
          <RegistrySidebar />
          <SidebarInset className="md:m-2 md:ml-0 md:max-h-[calc(100dvh-1rem)] md:rounded-lg md:border md:border-border md:bg-background md:shadow-sm">
            <Suspense fallback={<div className="flex h-screen w-full items-center justify-center" />}>
              <Outlet />
            </Suspense>
          </SidebarInset>
          <CommandMenu />
          <Toaster visibleToasts={1} />
        </SidebarProvider>
      </HelpProvider>
    </AuthGuard>
  );
}

export const Route = createFileRoute("/_authed")({
  component: AuthedLayout,
});
