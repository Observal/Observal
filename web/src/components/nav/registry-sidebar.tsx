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
  AlertTriangle,
} from "lucide-react";
import { getUserRole, getUserName, getUserEmail } from "@/lib/api";
import { hasMinRole, type Role } from "@/hooks/use-role-guard";

type NavItem = { title: string; href: string; icon: typeof Home; requiresAuth?: boolean; minRole?: Role };

const registryNav: NavItem[] = [
  { title: "Home", href: "/", icon: Home },
  { title: "Agents", href: "/agents", icon: Bot },
  { title: "Leaderboard", href: "/agents/leaderboard", icon: Trophy },
  { title: "Components", href: "/components", icon: Blocks },
  { title: "Builder", href: "/agents/builder", icon: Hammer, requiresAuth: true },
];

const reviewNav: NavItem[] = [
  { title: "Review", href: "/review", icon: ShieldCheck, minRole: "reviewer" },
];

const adminNav: NavItem[] = [
  { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard, minRole: "admin" },
  { title: "Traces", href: "/traces", icon: Activity, minRole: "admin" },
  { title: "Errors", href: "/errors", icon: AlertTriangle, minRole: "admin" },
  { title: "Evals", href: "/eval", icon: FlaskConical, minRole: "admin" },
  { title: "Users", href: "/users", icon: Users, minRole: "admin" },
  { title: "Settings", href: "/settings", icon: Settings, minRole: "super_admin" },
];

export const allNavItems = [
  { group: "Registry", items: registryNav },
  { group: "Review", items: reviewNav },
  { group: "Admin", items: adminNav },
];

export function RegistrySidebar() {
  const pathname = usePathname();
  const role = getUserRole();
  const userName = getUserName();
  const userEmail = getUserEmail();
  const isAuthenticated = typeof window !== "undefined" && !!localStorage.getItem("observal_access_token");

  function isActive(href: string) {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  }

  const visibleRegistryNav = registryNav.filter(
    (item) => !item.requiresAuth || isAuthenticated,
  );

  const visibleReviewNav = isAuthenticated
    ? reviewNav.filter((item) => !item.minRole || hasMinRole(role, item.minRole))
    : [];

  const visibleAdminNav = isAuthenticated
    ? adminNav.filter((item) => !item.minRole || hasMinRole(role, item.minRole))
    : [];

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

        {visibleReviewNav.length > 0 && (
          <SidebarGroup>
            <SidebarGroupLabel className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
              Review
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {visibleReviewNav.map((item) => (
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

        {visibleAdminNav.length > 0 && (
          <SidebarGroup>
            <SidebarGroupLabel className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
              Admin
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {visibleAdminNav.map((item) => (
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
        <NavUser user={{ name: userName || "User", email: userEmail || "" }} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
