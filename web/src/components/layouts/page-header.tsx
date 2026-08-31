// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { Link, useLocation } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

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
  const context = (breadcrumbs ?? []).filter(
    (entry, index, entries) =>
      entry.label !== title || index !== entries.length - 1,
  );

  return (
    <header className="sticky top-0 z-30 w-full border-b border-border bg-background/95 backdrop-blur-sm supports-[backdrop-filter]:bg-background/90">
      <div className="flex min-h-13 items-center gap-2 px-3 sm:px-4">
        <SidebarTrigger className="mr-0.5" />
        {actionButtonsLeft}

        <nav aria-label="Breadcrumb" className="min-w-0 text-xs text-muted-foreground">
          <ol className="flex min-w-0 items-center gap-1.5">
            {context.map((crumb, index) => (
              <li
                key={`${crumb.label}-${index}`}
                className={cn(
                  "min-w-0 items-center gap-1.5",
                  index === context.length - 1 ? "inline-flex" : "hidden sm:inline-flex",
                )}
              >
                {index > 0 && (
                  <ChevronRight
                    aria-hidden="true"
                    className="h-3 w-3 shrink-0 text-muted-foreground/60"
                  />
                )}
                {crumb.href ? (
                  <Link
                    to={crumb.href}
                    className="truncate underline-offset-4 hover:text-foreground hover:underline"
                  >
                    {crumb.label}
                  </Link>
                ) : (
                  <span className="truncate">{crumb.label}</span>
                )}
              </li>
            ))}
            {context.length > 0 && (
              <ChevronRight
                aria-hidden="true"
                className="h-3 w-3 shrink-0 text-muted-foreground/60"
              />
            )}
          </ol>
        </nav>

        <h2 className="truncate text-sm font-semibold tracking-tight text-foreground">{title}</h2>

        <div className="ml-auto flex items-center gap-2">
          {actionButtonsRight}
          {children}
        </div>
      </div>

      {tabs && (
        <nav aria-label={`${title} sections`} className="overflow-x-auto border-t border-border/70 px-3 sm:px-4">
          <div className="flex h-9 w-max min-w-full items-end gap-5">
            {tabs.map((tab) => {
              const isActive = activeTab === tab.value || pathname === tab.href;
              return (
                <Link
                  key={tab.value}
                  to={tab.href}
                  aria-current={isActive ? "page" : undefined}
                  className={cn(
                    "inline-flex h-full items-center border-b-2 border-transparent px-0.5 text-xs font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground",
                    isActive && "border-primary-accent text-foreground",
                  )}
                >
                  {tab.label}
                </Link>
              );
            })}
          </div>
        </nav>
      )}
    </header>
  );
}
