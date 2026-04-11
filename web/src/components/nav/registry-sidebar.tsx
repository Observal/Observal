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
import {
  Home,
  Bot,
  Blocks,
  Hammer,
  Trophy,
  LayoutDashboard,
  Activity,
  FlaskConical,
  ShieldCheck,
  Users,
  Settings,
} from "lucide-react";
import { getUserRole } from "@/lib/api";

const registryNav: { title: string; href: string; icon: typeof Home; requiresAuth?: boolean }[] = [
  { title: "Home", href: "/", icon: Home },
  { title: "Agents", href: "/agents", icon: Bot },
  { title: "Leaderboard", href: "/agents/leaderboard", icon: Trophy },
  { title: "Components", href: "/components", icon: Blocks },
  { title: "Builder", href: "/agents/builder", icon: Hammer, requiresAuth: true },
];

const adminNav = [
  { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { title: "Traces", href: "/traces", icon: Activity },
  { title: "Evals", href: "/eval", icon: FlaskConical },
  { title: "Review", href: "/review", icon: ShieldCheck },
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
  const isAuthenticated = typeof window !== "undefined" && !!localStorage.getItem("observal_api_key");

  function isActive(href: string) {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  }

  const visibleRegistryNav = registryNav.filter(
    (item) => !item.requiresAuth || isAuthenticated,
  );

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2.5 px-2 py-1.5">
          <span className="text-base font-semibold tracking-tight font-[family-name:var(--font-display)]">
            Observal
          </span>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            Registry
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {visibleRegistryNav.map((item) => (
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

        {isAuthenticated && isAdmin && (
          <SidebarGroup>
            <SidebarGroupLabel className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
              Admin
            </SidebarGroupLabel>
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
