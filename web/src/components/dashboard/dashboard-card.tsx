"use client";

import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface DashboardCardProps {
  title: ReactNode;
  description?: ReactNode;
  isLoading: boolean;
  children: ReactNode;
  headerRight?: ReactNode;
  headerChildren?: ReactNode;
  className?: string;
  contentClassName?: string;
}

export function DashboardCard({
  title,
  description,
  isLoading,
  children,
  headerRight,
  headerChildren,
  className,
  contentClassName,
}: DashboardCardProps) {
  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader className="relative">
        <div className="flex items-start justify-between">
          <div className="flex flex-col gap-1">
            <CardTitle>{title}</CardTitle>
            {description && <CardDescription>{description}</CardDescription>}
          </div>
          {headerRight}
        </div>
        {headerChildren}
        {isLoading && (
          <div className="absolute top-4 right-4">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        )}
      </CardHeader>
      <CardContent className={cn("flex flex-1 flex-col gap-3", contentClassName)}>
        {children}
      </CardContent>
    </Card>
  );
}
