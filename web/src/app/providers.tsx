// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { makeQueryClient } from "@/lib/query-client";
import { DynamicTitle } from "@/components/dynamic-title";

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(makeQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider
        attribute="class"
        defaultTheme="system"
        enableSystem
        disableTransitionOnChange
        themes={["light", "dark", "midnight", "forest", "sunset", "solarized-dark", "solarized-light", "dracula", "nord", "monokai", "gruvbox", "catppuccin", "tokyo-night", "one-dark", "rose-pine"]}
      >
        {children}
      </ThemeProvider>
      <DynamicTitle />
    </QueryClientProvider>
  );
}
