// SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute, useParams } from "@tanstack/react-router";
import { lazy } from "react";

const ReviewPolicyPage = lazy(() => import("@/pages/review/policy"));

function TeamPolicyRoute() {
  const { teamId } = useParams({ from: "/_authed/review-policy/team/$teamId" });
  return <ReviewPolicyPage teamId={teamId} />;
}

export const Route = createFileRoute("/_authed/review-policy/team/$teamId")({ component: TeamPolicyRoute });
