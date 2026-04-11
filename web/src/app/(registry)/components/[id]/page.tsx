"use client";

import { use } from "react";
import { useSearchParams } from "next/navigation";
import { useRegistryItem } from "@/hooks/use-api";
import type { RegistryType } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";

export default function ComponentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const searchParams = useSearchParams();
  const type = (searchParams.get("type") ?? "mcps") as RegistryType;
  const { data: item, isLoading } = useRegistryItem(type, id);

  if (isLoading) return <div className="p-6 text-muted-foreground">Loading...</div>;
  if (!item) return <div className="p-6 text-muted-foreground">Component not found</div>;

  const c = item as any;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">{c.name}</h1>
          <Badge variant="outline">{type.replace(/s$/, "")}</Badge>
          {c.status && <Badge variant={c.status === "approved" ? "default" : "secondary"}>{c.status}</Badge>}
        </div>
      </div>

      {c.description && <p className="text-sm">{c.description}</p>}

      <div className="grid grid-cols-2 gap-4 text-sm">
        {c.version && <div><span className="text-muted-foreground">Version:</span> {c.version}</div>}
        {c.git_url && <div><span className="text-muted-foreground">Source:</span> <a href={c.git_url} className="underline" target="_blank" rel="noopener noreferrer">{c.git_url}</a></div>}
        {c.transport && <div><span className="text-muted-foreground">Transport:</span> {c.transport}</div>}
        {c.created_at && <div><span className="text-muted-foreground">Created:</span> {new Date(c.created_at).toLocaleDateString()}</div>}
      </div>

      <div>
        <Link href="/components" className="text-sm text-muted-foreground hover:text-foreground">
          Back to components
        </Link>
      </div>
    </div>
  );
}
