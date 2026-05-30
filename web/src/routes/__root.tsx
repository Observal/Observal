// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createRootRoute, Outlet } from "@tanstack/react-router";
import { useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "@/lib/theme";
import { makeQueryClient } from "@/lib/query-client";
import { DynamicTitle } from "@/components/dynamic-title";
import { VersionMismatchBanner } from "@/components/shared/version-mismatch-banner";
import "@/app.css";

const THEMES = [
  "light",
  "dark",
  "midnight",
  "forest",
  "sunset",
  "solarized-dark",
  "solarized-light",
  "dracula",
  "nord",
  "monokai",
  "gruvbox",
  "catppuccin",
  "tokyo-night",
  "one-dark",
  "rose-pine",
];

function RootComponent() {
  const [queryClient] = useState(makeQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="system" themes={THEMES}>
        <Outlet />
        <VersionMismatchBanner />
      </ThemeProvider>
      <DynamicTitle />
    </QueryClientProvider>
  );
}

export const Route = createRootRoute({
  component: RootComponent,
});
