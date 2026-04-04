"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Telescope,
  Home,
  Search,
  Server,
  Bot,
  Wrench,
  Sparkles,
  Webhook,
  FileText,
  Container,
  Network,
  ListTree,
  Clock,
  BarChart3,
  FlaskConical,
  MessageSquare,
  ClipboardCheck,
  Shield,
  Settings,
  Radio,
  GitCompare,
  Terminal,
  Coins,
  ClipboardPen,
  Bell,
  Monitor,
  Cpu,
  BrainCircuit,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarSeparator,
} from "@/components/ui/sidebar";
import { NavUser } from "./nav-user";
import { ThemeSwitcher } from "@/components/ui/theme-switcher";

const topItems = [
  { title: "Home", href: "/", icon: Home },
  { title: "Go to...", href: "#command", icon: Search, shortcut: "⌘K" },
];

const registryItems = [
  { title: "MCP Servers", href: "/mcps", icon: Server },
  { title: "Agents", href: "/agents", icon: Bot },
  { title: "Tools", href: "/tools", icon: Wrench },
  { title: "Skills", href: "/skills", icon: Sparkles },
  { title: "Hooks", href: "/hooks", icon: Webhook },
  { title: "Prompts", href: "/prompts", icon: FileText },
  { title: "Sandboxes", href: "/sandboxes", icon: Container },
  { title: "GraphRAGs", href: "/graphrags", icon: Network },
];

const observabilityItems = [
  { title: "Traces", href: "/traces", icon: ListTree },
  { title: "Live Stream", href: "/traces?live=1", icon: Radio },
  { title: "Compare", href: "/traces/compare", icon: GitCompare },
  { title: "Sessions", href: "/sessions", icon: Clock },
  { title: "Scores", href: "/scores", icon: BarChart3 },
  { title: "Token Usage", href: "/tokens", icon: Coins },
  { title: "IDE Usage", href: "/ide-usage", icon: Monitor },
];

const evalItems = [
  { title: "Eval Runs", href: "/eval", icon: FlaskConical },
  { title: "Feedback", href: "/feedback", icon: MessageSquare },
  { title: "Annotations", href: "/annotations", icon: ClipboardPen },
  { title: "Sandbox Metrics", href: "/sandbox-metrics", icon: Cpu },
  { title: "GraphRAG Analytics", href: "/graphrag-metrics", icon: BrainCircuit },
  { title: "Prompt Playground", href: "/prompts/playground", icon: Terminal },
  { title: "Alerts", href: "/alerts", icon: Bell },
];

const secondaryItems = [
  { title: "Review Queue", href: "/review", icon: ClipboardCheck, badge: true },
  { title: "Admin", href: "/admin", icon: Shield },
  { title: "Settings", href: "/admin/settings", icon: Settings },
];

export const allNavItems = [
  { group: "Navigation", items: topItems.filter((i) => i.href !== "#command") },
  { group: "Registry", items: registryItems },
  { group: "Observability", items: observabilityItems },
  { group: "Evaluation", items: evalItems },
  { group: "Admin", items: secondaryItems },
];

interface AppSidebarProps {
  user?: { name: string; email: string };
  reviewCount?: number;
}

export function AppSidebar({ user, reviewCount = 0 }: AppSidebarProps) {
  const pathname = usePathname();

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Telescope className="size-4" />
                </div>
                <span className="font-semibold">Observal</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        {/* Top ungrouped */}
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {topItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  {item.href === "#command" ? (
                    <SidebarMenuButton
                      tooltip={item.title}
                      onClick={() =>
                        document.dispatchEvent(
                          new KeyboardEvent("keydown", { key: "k", metaKey: true })
                        )
                      }
                    >
                      <item.icon />
                      <span>{item.title}</span>
                      {item.shortcut && (
                        <kbd className="ml-auto pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground">
                          {item.shortcut}
                        </kbd>
                      )}
                    </SidebarMenuButton>
                  ) : (
                    <SidebarMenuButton
                      asChild
                      isActive={isActive(item.href)}
                      tooltip={item.title}
                    >
                      <Link href={item.href}>
                        <item.icon />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  )}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarSeparator />

        {/* Registry */}
        <SidebarGroup>
          <SidebarGroupLabel>Registry</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {registryItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton
                    asChild
                    isActive={isActive(item.href)}
                    tooltip={item.title}
                  >
                    <Link href={item.href}>
                      <item.icon />
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Observability */}
        <SidebarGroup>
          <SidebarGroupLabel>Observability</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {observabilityItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton
                    asChild
                    isActive={isActive(item.href)}
                    tooltip={item.title}
                  >
                    <Link href={item.href}>
                      <item.icon />
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Evaluation */}
        <SidebarGroup>
          <SidebarGroupLabel>Evaluation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {evalItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton
                    asChild
                    isActive={isActive(item.href)}
                    tooltip={item.title}
                  >
                    <Link href={item.href}>
                      <item.icon />
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarSeparator />

        {/* Secondary */}
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {secondaryItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton
                    asChild
                    isActive={isActive(item.href)}
                    tooltip={item.title}
                  >
                    <Link href={item.href}>
                      <item.icon />
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                  {item.badge && reviewCount > 0 && (
                    <SidebarMenuBadge>{reviewCount}</SidebarMenuBadge>
                  )}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <ThemeSwitcher />
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <NavUser user={user ?? { name: "User", email: "" }} />
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
