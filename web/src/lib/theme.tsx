// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type ThemeContextValue = {
  theme: string;
  setTheme: (theme: string) => void;
};

const ThemeContext = createContext<ThemeContextValue>({ theme: "dark", setTheme: () => {} });

const STORAGE_KEY = "observal-theme";

function getInitialTheme(themes: string[], defaultTheme: string): string {
  if (typeof window === "undefined") return defaultTheme;
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored && themes.includes(stored)) return stored;
  if (defaultTheme === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return defaultTheme;
}

type ThemeProviderProps = {
  children: ReactNode;
  defaultTheme?: string;
  themes?: string[];
};

export function ThemeProvider({
  children,
  defaultTheme = "system",
  themes = ["light", "dark"],
}: ThemeProviderProps) {
  const [theme, setThemeState] = useState(() => getInitialTheme(themes, defaultTheme));

  const setTheme = (next: string) => {
    let resolved = next;
    if (next === "system") {
      resolved = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    setThemeState(resolved);
    localStorage.setItem(STORAGE_KEY, next);
    document.documentElement.className = resolved;
  };

  useEffect(() => {
    document.documentElement.className = theme;
  }, [theme]);

  useEffect(() => {
    if (defaultTheme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (!stored || stored === "system") {
        const resolved = mq.matches ? "dark" : "light";
        setThemeState(resolved);
        document.documentElement.className = resolved;
      }
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [defaultTheme]);

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
