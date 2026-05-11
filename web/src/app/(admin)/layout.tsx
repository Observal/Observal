// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { RegistrySidebar } from "@/components/nav/registry-sidebar";
import { CommandMenu } from "@/components/nav/command-menu";
import { Toaster } from "@/components/ui/sonner";
import { AuthGuard } from "@/components/layouts/auth-guard";
import { RoleGuard } from "@/components/layouts/role-guard";
import { RetentionWarningBanner } from "@/components/shared/retention-warning-banner";

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthGuard>
      <RoleGuard minRole="reviewer">
        <SidebarProvider>
          <RegistrySidebar />
          <SidebarInset>
            <RetentionWarningBanner />
            {children}
          </SidebarInset>
          <CommandMenu />
          <Toaster visibleToasts={1} />
        </SidebarProvider>
      </RoleGuard>
    </AuthGuard>
  );
}
