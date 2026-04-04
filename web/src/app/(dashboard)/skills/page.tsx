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
  { accessorKey: "task_type", header: "Task Type" },
  { accessorKey: "target_agent", header: "Target Agent" },
  { accessorKey: "created_at", header: "Created", cell: ({ getValue }) => {
    const v = getValue();
    return v ? formatDistanceToNow(new Date(String(v)), { addSuffix: true }) : "—";
  }},
];

export default function SkillsPage() {
  const { data, isLoading } = useRegistryList("skills");
  const router = useRouter();

  return (
    <DashboardShell>
      <PageHeader title="Skills" breadcrumbs={[{ label: "Home", href: "/" }, { label: "Skills" }]} />
      <RegistryTable
        data={(data as Row[]) ?? []}
        columns={columns}
        isLoading={isLoading}
        onRowClick={(row) => router.push(`/skills/${row.id}`)}
      />
    </DashboardShell>
  );
}
