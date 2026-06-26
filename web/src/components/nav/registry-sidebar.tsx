// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { Link, useLocation } from "@tanstack/react-router";
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
	ShieldCheck,
	Users,
	Settings,
	ScrollText,
	ShieldAlert,
	Stethoscope,
	KeyRound,
	BookOpen,
} from "lucide-react";
import { useSyncExternalStore } from "react";
import {
	getUserRole,
	getUserName,
	getUserEmail,
	getUserUsername,
} from "@/lib/api";
import { hasMinRole, type Role } from "@/hooks/use-role-guard";
import {
	useDeploymentConfig,
	useServerVersion,
} from "@/hooks/use-deployment-config";

type NavItem = {
	title: string;
	href: string;
	icon: typeof Home;
	requiresAuth?: boolean;
	minRole?: Role;
	requiresFeature?: string;
};

const registryNav: NavItem[] = [
	{ title: "Home", href: "/", icon: Home },
	{ title: "Agents", href: "/agents", icon: Bot },
	{ title: "Leaderboard", href: "/leaderboard", icon: Trophy },
	{ title: "Components", href: "/components", icon: Blocks },
	{
		title: "Builder",
		href: "/agents/builder",
		icon: Hammer,
		requiresAuth: true,
	},
	{ title: "Wiki", href: "/wiki", icon: BookOpen },
];

const reviewNav: NavItem[] = [
	{ title: "Review", href: "/review", icon: ShieldCheck, minRole: "reviewer" },
];

const userNav: NavItem[] = [
	{ title: "My Traces", href: "/traces", icon: Activity, minRole: "user" },
];

const adminNav: NavItem[] = [
	{
		title: "Dashboard",
		href: "/dashboard",
		icon: LayoutDashboard,
		minRole: "admin",
		requiresFeature: "exec_dashboard",
	},
	{ title: "Users", href: "/users", icon: Users, minRole: "admin" },
	{
		title: "Audit Log",
		href: "/audit-log",
		icon: ScrollText,
		minRole: "admin",
		requiresFeature: "audit",
	},
	{
		title: "Security",
		href: "/security-events",
		icon: ShieldAlert,
		minRole: "admin",
		requiresFeature: "security_events",
	},
	{
		title: "SSO",
		href: "/sso",
		icon: KeyRound,
		minRole: "admin",
	},
	{
		title: "Diagnostics",
		href: "/diagnostics",
		icon: Stethoscope,
		minRole: "admin",
	},
	{ title: "Settings", href: "/settings", icon: Settings, minRole: "super_admin" },
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
	`${sessionStorage.getItem("observal_access_token") ?? ""}|${getUserRole() ?? ""}|${getUserName() ?? ""}|${getUserEmail() ?? ""}|${getUserUsername() ?? ""}`;
const getServerSnap = () => "||||";

function ServerVersionBadge() {
	const { serverVersion, loading } = useServerVersion();

	if (loading || !serverVersion || serverVersion === "dev") return null;

	return (
		<div className="group-data-[collapsible=icon]:hidden rounded-md px-2 py-1.5 text-[11px] leading-none text-sidebar-foreground/55">
			Server v{serverVersion}
		</div>
	);
}

export function RegistrySidebar() {
	const { pathname } = useLocation();
	const snap = useSyncExternalStore(storeSub, getAuthSnap, getServerSnap);
	const [token, role, userName, userEmail, userUsername] = snap.split("|");
	const isAuthenticated = !!token;
	const {
		licensedFeatures,
		brandingLogo,
		brandingAppName,
		brandingWordmark,
	} = useDeploymentConfig();

	function isActive(href: string) {
		if (href === "/") return pathname === "/";
		if (pathname === href) return true;
		// Only treat as active if no *more-specific* sibling nav item matches.
		// e.g. /agents should NOT be active when /agents/builder matches.
		const allHrefs = [
			...registryNav,
			...reviewNav,
			...userNav,
			...adminNav,
		].map((n) => n.href);
		const moreSpecific = allHrefs.some(
			(h) => h !== href && h.startsWith(href + "/") && pathname.startsWith(h),
		);
		if (moreSpecific) return false;
		return pathname.startsWith(href);
	}

	const visibleRegistryNav = registryNav.filter(
		(item) => !item.requiresAuth || isAuthenticated,
	);

	const visibleReviewNav = isAuthenticated
		? reviewNav.filter(
				(item) => !item.minRole || hasMinRole(role, item.minRole),
			)
		: [];

	const visibleUserNav = isAuthenticated
		? userNav.filter((item) => !item.minRole || hasMinRole(role, item.minRole))
		: [];

	const visibleAdminNav = isAuthenticated
		? adminNav.filter(
				(item) =>
					(!item.minRole || hasMinRole(role, item.minRole)) &&
					(!item.requiresFeature || licensedFeatures.includes(item.requiresFeature) || licensedFeatures.includes("all")),
			)
		: [];

	return (
		<Sidebar collapsible="icon">
			<SidebarHeader>
				<SidebarMenu>
					<SidebarMenuItem>
						<SidebarMenuButton size="lg" asChild>
							<Link to="/">
								<div className="flex size-8 shrink-0 items-center justify-center">
									{brandingLogo ? (
										<img
											src={brandingLogo}
											alt=""
											width={26}
											height={26}
											className="object-contain"
										/>
									) : (
										<img
											src="/observal-logo.svg"
											alt=""
											width={26}
											height={26}
											className="object-contain"
										/>
									)}
								</div>
								<div className="flex flex-col gap-0.5 leading-none">
									{brandingWordmark ? (
										<img
											src={brandingWordmark}
											alt={brandingAppName || "Observal"}
											width={140}
											height={20}
											className="h-5 max-w-35 object-contain object-left"
										/>
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
										<Link to={item.href}>
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
											<Link to={item.href}>
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
											<Link to={item.href}>
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
											<Link to={item.href}>
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
				<ServerVersionBadge />
				<NavUser
					user={{
						name: userName || "User",
						email: userEmail || "",
						username: userUsername || undefined,
					}}
				/>
			</SidebarFooter>
			<SidebarRail />
		</Sidebar>
	);
}
