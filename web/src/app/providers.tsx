"use client";

import { useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { makeQueryClient } from "@/lib/query-client";

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(makeQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange themes={["light", "dark", "midnight", "forest", "sunset"]}>
        {children}
      </ThemeProvider>
    </QueryClientProvider>
  );
}
