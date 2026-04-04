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
  { accessorKey: "event_type", header: "Event Type" },
  { accessorKey: "scope", header: "Scope" },
  { accessorKey: "created_at", header: "Created", cell: ({ getValue }) => {
    const v = getValue();
    return v ? formatDistanceToNow(new Date(String(v)), { addSuffix: true }) : "—";
  }},
];

export default function HooksPage() {
  const { data, isLoading } = useRegistryList("hooks");
  const router = useRouter();

  return (
    <DashboardShell>
      <PageHeader title="Hooks" breadcrumbs={[{ label: "Home", href: "/" }, { label: "Hooks" }]} />
      <RegistryTable
        data={(data as Row[]) ?? []}
        columns={columns}
        isLoading={isLoading}
        onRowClick={(row) => router.push(`/hooks/${row.id}`)}
      />
    </DashboardShell>
  );
}
