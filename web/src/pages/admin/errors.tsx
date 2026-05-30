// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { AlertTriangle } from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { EmptyState } from "@/components/shared/empty-state";

export default function ErrorsPage() {
  return (
    <>
      <PageHeader
        title="Errors"
        breadcrumbs={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Errors" },
        ]}
      />
      <div className="p-6">
        <EmptyState
          icon={AlertTriangle}
          title="Coming soon"
          description="Error event tracking is being reworked. Check back in a future release."
        />
      </div>
    </>
  );
}
