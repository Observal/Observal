"use client";

import { useState } from "react";
import { useFeedback } from "@/hooks/use-api";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Star } from "lucide-react";

const TYPES = ["mcp", "agent", "tool", "skill", "hook", "prompt", "sandbox", "graphrag"];

interface FeedbackItem {
  id: string;
  listing_id?: string;
  listing_name?: string;
  listing_type?: string;
  stars: number;
  comment?: string;
  user?: string;
  username?: string;
  created_at?: string;
}

function Stars({ count }: { count: number }) {
  return (
    <span className="inline-flex gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star key={i} className={`h-3.5 w-3.5 ${i < count ? "fill-yellow-400 text-yellow-400" : "text-muted-foreground/30"}`} />
      ))}
    </span>
  );
}

export default function FeedbackPage() {
  const [type, setType] = useState("mcp");
  const [itemId, setItemId] = useState("");

  const { data: items, isLoading } = useFeedback(type, itemId || undefined);

  return (
    <DashboardShell>
      <PageHeader title="Feedback" breadcrumbs={[{ label: "Dashboard", href: "/" }, { label: "Feedback" }]} />

      <div className="flex gap-3">
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="w-[160px]"><SelectValue /></SelectTrigger>
          <SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
        </Select>
        <Input placeholder="Item ID…" value={itemId} onChange={(e) => setItemId(e.target.value)} className="max-w-xs" />
      </div>

      {isLoading ? (
        <div className="space-y-2">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Rating</TableHead>
              <TableHead>Comment</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Date</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(items as FeedbackItem[] | undefined)?.length ? (items as FeedbackItem[]).map((fb) => (
              <TableRow key={fb.id}>
                <TableCell className="font-medium">{fb.listing_name ?? fb.listing_id ?? "—"}</TableCell>
                <TableCell><Badge variant="outline">{fb.listing_type ?? type}</Badge></TableCell>
                <TableCell><Stars count={fb.stars} /></TableCell>
                <TableCell className="max-w-xs truncate">{fb.comment ?? "—"}</TableCell>
                <TableCell>{fb.user ?? fb.username ?? "—"}</TableCell>
                <TableCell className="text-xs">{fb.created_at ? new Date(fb.created_at).toLocaleString() : "—"}</TableCell>
              </TableRow>
            )) : (
              <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground">{itemId ? "No feedback found" : "Enter an item ID to view feedback"}</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      )}
    </DashboardShell>
  );
}
