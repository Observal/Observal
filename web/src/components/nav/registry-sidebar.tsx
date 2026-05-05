"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
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
  ScrollText,
  ShieldAlert,
  Stethoscope,
  KeyRound,
  Lightbulb,
} from "lucide-react";
import { useSyncExternalStore } from "react";
import { getUserRole, getUserName, getUserEmail, getUserUsername } from "@/lib/api";
import { hasMinRole, type Role } from "@/hooks/use-role-guard";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";

type NavItem = { title: string; href: string; icon: typeof Home; requiresAuth?: boolean; minRole?: Role; enterpriseOnly?: boolean; requiresInsights?: boolean };

const registryNav: NavItem[] = [
  { title: "Home", href: "/", icon: Home },
  { title: "Agents", href: "/agents", icon: Bot },
  { title: "Leaderboard", href: "/leaderboard", icon: Trophy },
  { title: "Components", href: "/components", icon: Blocks },
  { title: "Builder", href: "/agents/builder", icon: Hammer, requiresAuth: true },
];

const reviewNav: NavItem[] = [
  { title: "Review", href: "/review", icon: ShieldCheck, minRole: "reviewer" },
];

const userNav: NavItem[] = [
  { title: "My Traces", href: "/traces", icon: Activity, minRole: "user" },
];

const adminNav: NavItem[] = [
  { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard, minRole: "admin" },
  { title: "Errors", href: "/errors", icon: AlertTriangle, minRole: "admin" },
  { title: "Evals", href: "/eval", icon: FlaskConical, minRole: "admin" },
  { title: "Insights", href: "/insights", icon: Lightbulb, minRole: "admin", requiresInsights: true },
  { title: "Users", href: "/users", icon: Users, minRole: "admin" },
  { title: "Audit Log", href: "/audit-log", icon: ScrollText, minRole: "admin", enterpriseOnly: true },
  { title: "Security", href: "/security-events", icon: ShieldAlert, minRole: "admin", enterpriseOnly: true },
  { title: "SSO & SCIM", href: "/sso", icon: KeyRound, minRole: "admin", enterpriseOnly: true },
  { title: "Diagnostics", href: "/diagnostics", icon: Stethoscope, minRole: "admin" },
  { title: "Settings", href: "/settings", icon: Settings, minRole: "admin" },
];

export const allNavItems = [
  { group: "Registry", items: registryNav },
  { group: "Review", items: reviewNav },
  { group: "Traces", items: userNav },
  { group: "Admin", items: adminNav },
];

const storeSub = (cb: () => void) => {
  window.addEventListener("storage", cb);
  return () => window.removeEventListener("storage", cb);
};
const getAuthSnap = () =>
  `${localStorage.getItem("observal_access_token") ?? ""}|${getUserRole() ?? ""}|${getUserName() ?? ""}|${getUserEmail() ?? ""}|${getUserUsername() ?? ""}`;
const getServerSnap = () => "||||";

export function RegistrySidebar() {
  const pathname = usePathname();
  const snap = useSyncExternalStore(storeSub, getAuthSnap, getServerSnap);
  const [token, role, userName, userEmail, userUsername] = snap.split("|");
  const isAuthenticated = !!token;
  const { deploymentMode, insightsAvailable, brandingLogo, brandingAppName, brandingWordmark } = useDeploymentConfig();

  function isActive(href: string) {
    if (href === "/") return pathname === "/";
    if (pathname === href) return true;
    // Only treat as active if no *more-specific* sibling nav item matches.
    // e.g. /agents should NOT be active when /agents/builder matches.
    const allHrefs = [...registryNav, ...reviewNav, ...userNav, ...adminNav].map((n) => n.href);
    const moreSpecific = allHrefs.some((h) => h !== href && h.startsWith(href + "/") && pathname.startsWith(h));
    if (moreSpecific) return false;
    return pathname.startsWith(href);
  }

  const visibleRegistryNav = registryNav.filter(
    (item) => !item.requiresAuth || isAuthenticated,
  );

  const visibleReviewNav = isAuthenticated
    ? reviewNav.filter((item) => !item.minRole || hasMinRole(role, item.minRole))
    : [];

  const visibleUserNav = isAuthenticated
    ? userNav.filter((item) => !item.minRole || hasMinRole(role, item.minRole))
    : [];

  const visibleAdminNav = isAuthenticated
    ? adminNav.filter(
        (item) =>
          (!item.minRole || hasMinRole(role, item.minRole)) &&
          (!item.enterpriseOnly || deploymentMode === "enterprise") &&
          (!item.requiresInsights || insightsAvailable),
      )
    : [];

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/">
                <div className="flex size-8 shrink-0 items-center justify-center">
                  {brandingLogo ? (
                    <img src={brandingLogo} alt="" width={20} height={20} className="object-contain" />
                  ) : (
                    <Image src="/favicon.ico" alt="" width={20} height={20} />
                  )}
                </div>
                <div className="flex flex-col gap-0.5 leading-none">
                  {brandingWordmark ? (
                    <img src={brandingWordmark} alt={brandingAppName || "Observal"} className="h-5 max-w-35 object-contain object-left" />
                  ) : (
                    <span className="text-base font-semibold tracking-tight font-display truncate max-w-35">
                      {brandingAppName || "Observal"}
                    </span>
                  )}
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
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

        {visibleUserNav.length > 0 && (
          <SidebarGroup>
            <SidebarGroupLabel className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
              Traces
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {visibleUserNav.map((item) => (
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
        <NavUser user={{ name: userName || "User", email: userEmail || "", username: userUsername || undefined }} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
