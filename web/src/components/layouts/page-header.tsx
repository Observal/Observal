"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
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
  const pathname = usePathname();

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
                        <Link href={crumb.href}>{crumb.label}</Link>
                      </BreadcrumbLink>
                    ) : (
                      <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                    )}
                  </BreadcrumbItem>
                ))}
              </BreadcrumbList>
            </Breadcrumb>
          )}
        </div>
      </div>

      {/* Bottom row: title + actions */}
      <div className="bg-header">
        <div className="flex min-h-10 w-full flex-wrap items-center justify-between gap-1 px-3 py-1 md:flex-nowrap">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold leading-7">{title}</h2>
            {actionButtonsLeft}
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
                  href={tab.href}
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
