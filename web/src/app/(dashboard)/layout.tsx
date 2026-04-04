import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/nav/app-sidebar";
import { CommandMenu } from "@/components/nav/command-menu";
import { Toaster } from "@/components/ui/sonner";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        {children}
      </SidebarInset>
      <CommandMenu />
      <Toaster visibleToasts={1} />
    </SidebarProvider>
  );
}
