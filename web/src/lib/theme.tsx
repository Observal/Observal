// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

/**
 * Appearance system: two independent dimensions.
 *
 *   preset  monochrome (default) | slate | copper | verdant | indigo | rose
 *   mode    system (default) | light | dark
 *
 * `mode` is persisted as the user's *intent*, so "system" stays "system" and
 * keeps tracking the OS preference instead of being flattened to a literal on
 * first paint.
 *
 * Legacy themes (midnight, forest, dracula, ...) predate this matrix and carry
 * a complete one-dimensional palette. Selecting one applies its class alone and
 * its appearance is left exactly as it was; the light/dark toggle does not
 * apply to them.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export const PRESETS = [
  "monochrome",
  "slate",
  "copper",
  "verdant",
  "indigo",
  "rose",
] as const;

export type Preset = (typeof PRESETS)[number];
export type Mode = "light" | "dark" | "system";

export const DEFAULT_PRESET: Preset = "monochrome";
export const DEFAULT_MODE: Mode = "system";

/** Single-class themes that are not part of the preset x mode matrix. */
export const LEGACY_THEMES = [
  "midnight",
  "forest",
  "sunset",
  "solarized-light",
  "solarized-dark",
  "dracula",
  "nord",
  "monokai",
  "gruvbox",
  "catppuccin",
  "tokyo-night",
  "one-dark",
  "rose-pine",
] as const;

export type LegacyTheme = (typeof LEGACY_THEMES)[number];

type ThemeContextValue = {
  /** Preset when in the matrix, else the active legacy theme name. */
  theme: string;
  /**
   * Backwards-compatible setter. Accepts a preset, a legacy theme name, or
   * "light"/"dark"/"system" (treated as a mode change).
   */
  setTheme: (value: string) => void;
  preset: Preset;
  setPreset: (preset: Preset) => void;
  mode: Mode;
  setMode: (mode: Mode) => void;
  /** Mode with "system" resolved against the OS preference. */
  resolvedMode: "light" | "dark";
  legacyTheme: LegacyTheme | null;
  setLegacyTheme: (theme: LegacyTheme | null) => void;
};

const PRESET_KEY = "observal-preset";
const MODE_KEY = "observal-mode";
const LEGACY_KEY = "observal-legacy-theme";
/** Pre-matrix key. Read once to migrate an existing choice, never written. */
const OLD_KEY = "observal-theme";

const ThemeContext = createContext<ThemeContextValue>({
  theme: DEFAULT_PRESET,
  setTheme: () => {},
  preset: DEFAULT_PRESET,
  setPreset: () => {},
  mode: DEFAULT_MODE,
  setMode: () => {},
  resolvedMode: "dark",
  legacyTheme: null,
  setLegacyTheme: () => {},
});

function isPreset(value: string | null): value is Preset {
  return !!value && (PRESETS as readonly string[]).includes(value);
}

function isLegacy(value: string | null): value is LegacyTheme {
  return !!value && (LEGACY_THEMES as readonly string[]).includes(value);
}

function prefersDark(): boolean {
  if (typeof window === "undefined") return true;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function readInitial(): { preset: Preset; mode: Mode; legacy: LegacyTheme | null } {
  if (typeof window === "undefined") {
    return { preset: DEFAULT_PRESET, mode: DEFAULT_MODE, legacy: null };
  }

  const storedPreset = localStorage.getItem(PRESET_KEY);
  const storedMode = localStorage.getItem(MODE_KEY);
  const storedLegacy = localStorage.getItem(LEGACY_KEY);

  // Migrate a pre-matrix selection on first run. "light"/"dark" become a mode;
  // a legacy theme name is preserved as a legacy selection.
  if (!storedPreset && !storedMode && !storedLegacy) {
    const old = localStorage.getItem(OLD_KEY);
    if (isLegacy(old)) {
      return { preset: DEFAULT_PRESET, mode: DEFAULT_MODE, legacy: old };
    }
    if (old === "light" || old === "dark") {
      return { preset: DEFAULT_PRESET, mode: old, legacy: null };
    }
  }

  return {
    preset: isPreset(storedPreset) ? storedPreset : DEFAULT_PRESET,
    mode:
      storedMode === "light" || storedMode === "dark" || storedMode === "system"
        ? storedMode
        : DEFAULT_MODE,
    legacy: isLegacy(storedLegacy) ? storedLegacy : null,
  };
}

/**
 * Apply the appearance to <html>. A legacy theme wins and is applied alone;
 * otherwise the preset and (for dark) the `dark` class are applied together so
 * Tailwind's `dark:` variant keeps working.
 */
function applyToDocument(
  preset: Preset,
  resolved: "light" | "dark",
  legacy: LegacyTheme | null,
) {
  const classes = legacy
    ? [legacy]
    : resolved === "dark"
      ? [`preset-${preset}`, "dark"]
      : [`preset-${preset}`];
  document.documentElement.className = classes.join(" ");
  document.documentElement.style.colorScheme = legacy ? "" : resolved;
}

type ThemeProviderProps = {
  children: ReactNode;
  /** Mode used when nothing is stored. Accepts the legacy "system" value. */
  defaultTheme?: string;
  /** Retained for API compatibility; the preset list is fixed. */
  themes?: string[];
};

export function ThemeProvider({ children, defaultTheme }: ThemeProviderProps) {
  const initial = useMemo(readInitial, []);
  const [preset, setPresetState] = useState<Preset>(initial.preset);
  const [mode, setModeState] = useState<Mode>(() => {
    if (initial.mode !== DEFAULT_MODE) return initial.mode;
    return defaultTheme === "light" || defaultTheme === "dark"
      ? defaultTheme
      : DEFAULT_MODE;
  });
  const [legacyTheme, setLegacyState] = useState<LegacyTheme | null>(initial.legacy);
  const [systemDark, setSystemDark] = useState(prefersDark);

  const resolvedMode: "light" | "dark" =
    mode === "system" ? (systemDark ? "dark" : "light") : mode;

  // Keep the document in sync with state, including the initial paint.
  useEffect(() => {
    applyToDocument(preset, resolvedMode, legacyTheme);
  }, [preset, resolvedMode, legacyTheme]);

  // Track the OS preference so "system" stays live rather than being frozen.
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const setPreset = useCallback((next: Preset) => {
    setPresetState(next);
    setLegacyState(null);
    localStorage.setItem(PRESET_KEY, next);
    localStorage.removeItem(LEGACY_KEY);
  }, []);

  const setMode = useCallback((next: Mode) => {
    setModeState(next);
    setLegacyState(null);
    localStorage.setItem(MODE_KEY, next);
    localStorage.removeItem(LEGACY_KEY);
  }, []);

  const setLegacyTheme = useCallback((next: LegacyTheme | null) => {
    setLegacyState(next);
    if (next) localStorage.setItem(LEGACY_KEY, next);
    else localStorage.removeItem(LEGACY_KEY);
  }, []);

  // Backwards-compatible entry point for existing callers.
  const setTheme = useCallback(
    (value: string) => {
      if (value === "light" || value === "dark" || value === "system") {
        setMode(value);
      } else if (isPreset(value)) {
        setPreset(value);
      } else if (isLegacy(value)) {
        setLegacyTheme(value);
      }
    },
    [setMode, setPreset, setLegacyTheme],
  );

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: legacyTheme ?? preset,
      setTheme,
      preset,
      setPreset,
      mode,
      setMode,
      resolvedMode,
      legacyTheme,
      setLegacyTheme,
    }),
    [
      legacyTheme,
      preset,
      setTheme,
      setPreset,
      mode,
      setMode,
      resolvedMode,
      setLegacyTheme,
    ],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
