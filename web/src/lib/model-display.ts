// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

/**
 * Model display helpers.
 *
 * Reads pre-computed display fields from the server API response
 * (computed by services/model_display.py). Falls back to raw model_id
 * when display data isn't available.
 */

const DATE_SHORT = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

interface FormattedModel {
  primary: string;
  secondary: string | null;
  isRolling: boolean;
}

function formatDateShort(d: Date): string {
  return DATE_SHORT.format(d);
}

function forceSecondary(
  releaseDate: string | null | undefined,
  isRolling: boolean,
): string | null {
  if (isRolling) return "latest";
  if (releaseDate) {
    const d = new Date(releaseDate);
    if (!Number.isNaN(d.getTime())) return formatDateShort(d);
  }
  return null;
}

/**
 * Format a model catalog row for display.
 *
 * Reads the server-computed `display` field when available.
 * When `disambiguate` is true and the server didn't set a secondary label,
 * one is derived from the release date or rolling status.
 */
export function formatModel(input: {
  display_name?: string | null;
  model_id: string;
  release_date?: string | null;
  display?: { primary: string; secondary: string | null; is_rolling: boolean } | null;
  disambiguate?: boolean;
}): FormattedModel {
  const disambiguate = !!input.disambiguate;

  // Read pre-computed display from server response
  if (input.display) {
    const { primary, secondary, is_rolling } = input.display;
    return {
      primary,
      secondary:
        secondary ?? (disambiguate ? forceSecondary(input.release_date, is_rolling) : null),
      isRolling: is_rolling,
    };
  }

  // Fallback: no pre-computed display (shouldn't happen in normal flow)
  const primary = (input.display_name ?? input.model_id).trim();
  const isRolling = !(/\d{8}$/.test(input.model_id) || /\d{4}-\d{2}-\d{2}$/.test(input.model_id));
  return {
    primary,
    secondary: disambiguate ? forceSecondary(input.release_date, isRolling) : null,
    isRolling,
  };
}

/**
 * Annotate a list of catalog rows with display fields.
 * The server already provides `display` on each model; this just maps to
 * the component-friendly `FormattedModel` shape with collision-aware disambiguation.
 */
export function annotateForDisplay<
  T extends {
    display_name?: string | null;
    model_id: string;
    release_date?: string | null;
    display?: { primary: string; secondary: string | null; is_rolling: boolean } | null;
  },
>(rows: T[]): Array<T & { display: FormattedModel }> {
  // Server already computes collision-aware disambiguation; just map
  return rows.map((r) => ({
    ...r,
    display: formatModel({ ...r, disambiguate: false }),
  }));
}
