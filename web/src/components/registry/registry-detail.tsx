"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { StatusBadge } from "./status-badge";
import { InstallDialog } from "./install-dialog";
import { registry, type RegistryType } from "@/lib/api";
import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";

interface RegistryDetailProps {
  type: RegistryType;
  data: Record<string, unknown> | undefined;
  isLoading: boolean;
}

const HIDDEN_KEYS = new Set(["id", "name", "description", "status", "created_at", "updated_at"]);

export function RegistryDetail({ type, data, isLoading }: RegistryDetailProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const router = useRouter();
  const qc = useQueryClient();

  if (isLoading) {
    return (
      <Card>
        <CardHeader><Skeleton className="h-6 w-48" /></CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-4 w-full" />)}
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <div className="flex h-48 items-center justify-center rounded-md border text-muted-foreground">
        Item not found.
      </div>
    );
  }

  const id = String(data.id ?? "");
  const name = String(data.name ?? "Unknown");
  const meta = Object.entries(data).filter(([k]) => !HIDDEN_KEYS.has(k));

  async function handleDelete() {
    setDeleting(true);
    try {
      await registry.delete(type, id);
      qc.invalidateQueries({ queryKey: ["registry", type] });
      router.push(`/${type}`);
    } catch {
      setDeleting(false);
      setConfirmOpen(false);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between">
        <div className="space-y-1">
          <CardTitle className="text-xl">{name}</CardTitle>
          {data.description ? (
            <p className="text-sm text-muted-foreground">{String(data.description)}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {data.status ? <StatusBadge status={String(data.status)} /> : null}
          <InstallDialog type={type} id={id} name={name} />
          <Button size="sm" variant="destructive" onClick={() => setConfirmOpen(true)}>
            <Trash2 className="mr-1 h-3 w-3" /> Delete
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          {data.created_at ? (
            <div>
              <dt className="text-sm font-medium text-muted-foreground">Created</dt>
              <dd className="text-sm">{formatDistanceToNow(new Date(String(data.created_at)), { addSuffix: true })}</dd>
            </div>
          ) : null}
          {meta.map(([key, value]) => (
            <div key={key}>
              <dt className="text-sm font-medium text-muted-foreground">
                {key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
              </dt>
              <dd className="text-sm">
                {typeof value === "object" && value !== null ? (
                  <pre className="max-h-40 overflow-auto rounded bg-muted p-2 text-xs">
                    {JSON.stringify(value, null, 2)}
                  </pre>
                ) : (
                  String(value ?? "—")
                )}
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {name}?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">This action cannot be undone.</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
