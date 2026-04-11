"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { ThemeSwitcher } from "@/components/ui/theme-switcher";
import { NavUser } from "@/components/nav/nav-user";
import { Telescope, Home, Bot, Blocks, LayoutDashboard, Activity, FlaskConical, ShieldCheck, Users, Settings } from "lucide-react";
import { getUserRole } from "@/lib/api";

const registryNav = [
  { title: "Home", href: "/", icon: Home },
  { title: "Agents", href: "/agents", icon: Bot },
  { title: "Components", href: "/components", icon: Blocks },
];

const adminNav = [
  { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { title: "Traces", href: "/traces", icon: Activity },
  { title: "Eval", href: "/eval", icon: FlaskConical },
  { title: "Review Queue", href: "/review", icon: ShieldCheck },
  { title: "Users", href: "/users", icon: Users },
  { title: "Settings", href: "/settings", icon: Settings },
];

export const allNavItems = [
  { group: "Registry", items: registryNav },
  { group: "Admin", items: adminNav },
];

export function RegistrySidebar() {
  const pathname = usePathname();
  const role = getUserRole();
  const isAdmin = role === "admin";

  function isActive(href: string) {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-2 py-1">
          <div className="flex h-7 w-7 items-center justify-center rounded-sm bg-primary text-primary-foreground">
            <Telescope className="h-4 w-4" />
          </div>
          <span className="text-sm font-semibold">Observal</span>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Registry</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {registryNav.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton asChild isActive={isActive(item.href)}>
                    <Link href={item.href}>
                      <item.icon className="h-4 w-4" />
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {isAdmin && (
          <SidebarGroup>
            <SidebarGroupLabel>Admin</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {adminNav.map((item) => (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton asChild isActive={isActive(item.href)}>
                      <Link href={item.href}>
                        <item.icon className="h-4 w-4" />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}
      </SidebarContent>
      <SidebarFooter>
        <ThemeSwitcher />
        <NavUser user={{ name: "User", email: "" }} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
