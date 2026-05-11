"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, X } from "lucide-react";
import { useRetentionWarnings } from "@/hooks/use-api";
import { hasMinRole } from "@/hooks/use-role-guard";
import { getUserRole } from "@/lib/api";

export function RetentionWarningBanner() {
  const [dismissed, setDismissed] = useState(() => {
    if (typeof window === "undefined") return false;
    return sessionStorage.getItem("retention-warning-dismissed") === "1";
  });
  const { data } = useRetentionWarnings();

  if (dismissed) return null;
  if (!hasMinRole(getUserRole(), "admin")) return null;
  if (!data?.retention_enabled || !data.warnings?.length) return null;

  const handleDismiss = () => {
    setDismissed(true);
    sessionStorage.setItem("retention-warning-dismissed", "1");
  };

  return (
    <div className="bg-amber-500/10 border border-amber-500/30 text-amber-700 dark:text-amber-400 px-4 py-2.5 text-xs flex items-center gap-2">
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
      <span className="flex-1">
        Data retention is active ({data.retention_days} days).{" "}
        {data.warnings.length} agent{data.warnings.length > 1 ? "s have" : " has"} unanalyzed traces.{" "}
        <Link href="/insights" className="underline font-medium hover:text-amber-900 dark:hover:text-amber-300">
          Generate Insights
        </Link>
      </span>
      <button onClick={handleDismiss} className="p-0.5 hover:bg-amber-500/20 rounded">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
