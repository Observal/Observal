// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { Link, useLocation } from "@tanstack/react-router";
import { SidebarTrigger } from "@/components/ui/sidebar";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { cn } from "@/lib/utils";
import { GitHubStarBanner } from "@/components/nav/github-star-banner";

export interface BreadcrumbEntry {
  label: string;
  href?: string;
}

interface TabDef {
  value: string;
  label: string;
  href: string;
}

interface PageHeaderProps {
  title: string;
  breadcrumbs?: BreadcrumbEntry[];
  children?: React.ReactNode;
  actionButtonsLeft?: React.ReactNode;
  actionButtonsRight?: React.ReactNode;
  tabs?: TabDef[];
  activeTab?: string;
}

export function PageHeader({
  title,
  breadcrumbs,
  children,
  actionButtonsLeft,
  actionButtonsRight,
  tabs,
  activeTab,
}: PageHeaderProps) {
  const { pathname } = useLocation();

  return (
    <div className="sticky top-0 z-30 w-full border-b bg-background">
      {/* Top row: sidebar trigger + breadcrumbs */}
      <div className="border-b">
        <div className="flex min-h-10 items-center gap-3 px-3 py-1.5">
          <SidebarTrigger />
          {breadcrumbs && breadcrumbs.length > 0 && (
            <Breadcrumb>
              <BreadcrumbList>
                {breadcrumbs.map((crumb, i) => (
                  <BreadcrumbItem key={i}>
                    {i > 0 && <BreadcrumbSeparator />}
                    {crumb.href ? (
                      <BreadcrumbLink asChild>
                        <Link to={crumb.href}>{crumb.label}</Link>
                      </BreadcrumbLink>
                    ) : (
                      <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                    )}
                  </BreadcrumbItem>
                ))}
              </BreadcrumbList>
            </Breadcrumb>
          )}
          <div className="ml-auto">
            <GitHubStarBanner />
          </div>
        </div>
      </div>

      {/* Bottom row: title + actions */}
      <div className="bg-header">
        <div className="flex min-h-10 w-full flex-wrap items-center justify-between gap-1 px-3 py-1 md:flex-nowrap">
          <div className="flex items-center gap-2">
            {actionButtonsLeft}
            <h2 className="text-lg font-semibold leading-7">{title}</h2>
          </div>
          <div className="ml-auto flex items-center gap-1">
            {actionButtonsRight}
            {children}
          </div>
        </div>

        {/* Tabs */}
        {tabs && (
          <div className="ml-2">
            <div className="inline-flex h-8 items-center">
              {tabs.map((tab) => (
                <Link
                  key={tab.value}
                  to={tab.href}
                  className={cn(
                    "inline-flex h-full items-center border-b-2 border-transparent px-2 py-0.5 text-sm font-medium whitespace-nowrap transition-colors hover:bg-muted/50",
                    (activeTab === tab.value || pathname === tab.href) &&
                      "border-primary-accent",
                  )}
                >
                  {tab.label}
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
