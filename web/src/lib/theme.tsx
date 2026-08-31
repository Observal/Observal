// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

type ThemeContextValue = {
  theme: string;
  setTheme: (theme: string) => void;
};

const ThemeContext = createContext<ThemeContextValue>({
  theme: "dark",
  setTheme: () => {},
});

const STORAGE_KEY = "observal-theme";

function getInitialTheme(themes: string[], defaultTheme: string): string {
  if (typeof window === "undefined") return defaultTheme;
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored && themes.includes(stored)) return stored;
  if (stored) localStorage.setItem(STORAGE_KEY, defaultTheme);
  return defaultTheme;
}

type ThemeProviderProps = {
  children: ReactNode;
  defaultTheme?: string;
  themes?: string[];
};

export function ThemeProvider({
  children,
  defaultTheme = "dark",
  themes = ["dark", "light"],
}: ThemeProviderProps) {
  const [theme, setThemeState] = useState(() =>
    getInitialTheme(themes, defaultTheme),
  );

  const setTheme = (next: string) => {
    const resolved = themes.includes(next) ? next : defaultTheme;
    setThemeState(resolved);
    localStorage.setItem(STORAGE_KEY, resolved);
  };

  useEffect(() => {
    document.documentElement.className = theme;
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
