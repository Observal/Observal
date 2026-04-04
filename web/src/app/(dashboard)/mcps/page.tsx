"use client";

import { useRouter } from "next/navigation";
import { type ColumnDef } from "@tanstack/react-table";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { PageHeader } from "@/components/layouts/page-header";
import { RegistryTable } from "@/components/registry/registry-table";
import { StatusBadge } from "@/components/registry/status-badge";
import { useRegistryList } from "@/hooks/use-api";
import { formatDistanceToNow } from "date-fns";

type Row = Record<string, unknown>;

const columns: ColumnDef<Row, unknown>[] = [
  { accessorKey: "name", header: "Name" },
  { accessorKey: "status", header: "Status", cell: ({ getValue }) => <StatusBadge status={String(getValue() ?? "")} /> },
  { accessorKey: "category", header: "Category" },
  { accessorKey: "transport", header: "Transport" },
  { accessorKey: "created_at", header: "Created", cell: ({ getValue }) => {
    const v = getValue();
    return v ? formatDistanceToNow(new Date(String(v)), { addSuffix: true }) : "—";
  }},
];

export default function McpsPage() {
  const { data, isLoading } = useRegistryList("mcps");
  const router = useRouter();

  return (
    <DashboardShell>
      <PageHeader title="MCP Servers" breadcrumbs={[{ label: "Home", href: "/" }, { label: "MCP Servers" }]} />
      <DashboardContent>
        <RegistryTable
          data={(data as Row[]) ?? []}
          columns={columns}
          isLoading={isLoading}
          onRowClick={(row) => router.push(`/mcps/${row.id}`)}
        />
      </DashboardContent>
    </DashboardShell>
  );
}
