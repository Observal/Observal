"use client";

import { Users } from "lucide-react";
import { useAdminUsers } from "@/hooks/use-api";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

function roleBadge(role: string) {
  switch (role) {
    case "admin":
      return <Badge variant="default" className="text-[10px] px-1.5 py-0">{role}</Badge>;
    case "developer":
      return <Badge variant="secondary" className="text-[10px] px-1.5 py-0">{role}</Badge>;
    default:
      return <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-muted-foreground">{role}</Badge>;
  }
}

export default function UsersPage() {
  const { data: users, isLoading, isError, error, refetch } = useAdminUsers();

  return (
    <>
      <PageHeader
        title="Users"
        breadcrumbs={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Users" },
        ]}
      />
      <div className="p-6 max-w-6xl mx-auto space-y-4">
        {isLoading ? (
          <TableSkeleton rows={5} cols={4} />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : (users ?? []).length === 0 ? (
          <EmptyState
            icon={Users}
            title="No users yet"
            description="Users will appear here once they sign up or are added by an admin."
          />
        ) : (
          <div className="animate-in overflow-x-auto rounded-md border border-border">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="h-8 text-xs">Name</TableHead>
                  <TableHead className="h-8 text-xs">Email</TableHead>
                  <TableHead className="h-8 text-xs">Role</TableHead>
                  <TableHead className="h-8 text-xs text-right">Joined</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(users ?? []).map((u: any) => (
                  <TableRow key={u.id}>
                    <TableCell className="py-1.5">
                      <span className="text-sm font-medium">{u.name ?? u.username ?? "-"}</span>
                    </TableCell>
                    <TableCell className="py-1.5 text-sm text-muted-foreground">
                      {u.email ?? "-"}
                    </TableCell>
                    <TableCell className="py-1.5">
                      {roleBadge(u.role)}
                    </TableCell>
                    <TableCell className="py-1.5 text-xs text-muted-foreground text-right tabular-nums">
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : "-"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </>
  );
}
