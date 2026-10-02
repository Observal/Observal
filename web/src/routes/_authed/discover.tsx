// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute } from "@tanstack/react-router";
import { lazy } from "react";
const DiscoverPage = lazy(() => import("@/pages/registry/discover"));

export const Route = createFileRoute("/_authed/discover")({
  component: DiscoverPage,
});
