// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createFileRoute, useNavigate, useParams } from "@tanstack/react-router";
import React from "react";
import { Loader2 } from "lucide-react";
import { ErrorState } from "@/components/shared/error-state";
import { useLegacyInsightReport } from "@/hooks/use-insights-api";

function LegacyInsightRedirect() {
  const { reportId } = useParams({ from: "/_authed/insights/$reportId" });
  const navigate = useNavigate();
  const { data: report, isLoading, isError } = useLegacyInsightReport(reportId);

  React.useEffect(() => {
    if (!report) return;
    void navigate({
      to: "/agents/$agentId/insights/$reportId",
      params: { agentId: report.agent_id, reportId: report.id },
      replace: true,
    });
  }, [navigate, report]);

  if (isError) return <ErrorState message="Failed to load report" />;

  return (
    <div className="flex items-center justify-center py-20">
      {isLoading ? <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /> : null}
    </div>
  );
}

export const Route = createFileRoute("/_authed/insights/$reportId")({
  component: LegacyInsightRedirect,
});
