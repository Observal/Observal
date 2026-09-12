// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
// SPDX-License-Identifier: Apache-2.0


import { Link } from "@tanstack/react-router";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import { CommandMenu } from "@/components/nav/command-menu";


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

  // Build breadcrumb text: "Group / Page" with the last entry bolded
  const crumbParts = breadcrumbs ?? [];
  const lastCrumb = crumbParts[crumbParts.length - 1];
  const parentCrumbs = crumbParts.slice(0, -1);

  return (
    <header className="sticky top-0 z-30 flex min-h-[54px] items-center gap-3.5 border-b bg-background px-[30px]">
      {/* Sidebar toggle */}
      <SidebarTrigger className="h-[34px] w-[34px] shrink-0 rounded-[9px] text-foreground/65 hover:bg-surface-raised hover:text-foreground" />

      {/* Breadcrumb */}
      {crumbParts.length > 0 && (
        <nav className="min-w-0 truncate text-xs text-muted-foreground">
          {parentCrumbs.map((crumb, i) => (
            <span key={i}>
              {crumb.href ? (
                <Link to={crumb.href} className="hover:text-foreground">
                  {crumb.label}
                </Link>
              ) : (
                crumb.label
              )}
              <span className="mx-1.5">/</span>
            </span>
          ))}
          {lastCrumb && (
            <strong className="text-[13px] font-medium text-foreground">
              {lastCrumb.label}
            </strong>
          )}
        </nav>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Page-level action buttons placed in the header */}
      {actionButtonsLeft}
      {actionButtonsRight}
      {children}

      {/* Search button trigger */}
      <CommandMenu />


    </header>
  );
}

/**
 * Page intro section — sits inside the page body (below header), matching the
 * mockup's `.page-intro` layout: eyebrow + h1 + subtitle on the left, action
 * buttons on the right.
 */
export function PageIntro({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-5">
      <div>
        {eyebrow && (
          <p className="mb-1.5 text-2xs font-medium uppercase tracking-[0.06em] text-muted-foreground">
            {eyebrow}
          </p>
        )}
        <h1 className="text-2xl font-medium leading-[1.3] tracking-[-0.025em]">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-1.5 text-sm text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {children && (
        <div className="flex items-center gap-2">{children}</div>
      )}
    </div>
  );
}
