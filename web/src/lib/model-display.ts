/**
 * Shared display formatting for model catalog rows.
 *
 * Mirrored at:
 *   - observal-server/services/model_display.py (server)
 *   - observal_cli/render.py format_model() (CLI)
 *
 * Behaviour pinned by tests/fixtures/model_display_cases.json.
 */

const DATE_SUFFIX_DASH_COMPACT = /[-_\s](\d{8})$/;
const DATE_SUFFIX_DASH_HYPHEN = /[-_\s](\d{4}-\d{2}-\d{2})$/;
const DATE_SUFFIX_PAREN = /\s*\((\d{4}-\d{2}-\d{2})\)\s*$/;
const LATEST_PAREN = /\s*\(latest\)\s*$/i;
const LATEST_DASH = /[-_]latest$/i;

const MONTH_NAMES = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

export interface FormattedModel {
  primary: string;
  secondary: string | null;
  isRolling: boolean;
}

function stripTrailingDate(text: string): string {
  if (!text) return text;
  let out = text;
  out = out.replace(LATEST_PAREN, "").trim();
  out = out.replace(DATE_SUFFIX_PAREN, "").trim();
  out = out.replace(DATE_SUFFIX_DASH_HYPHEN, "").trim();
  out = out.replace(DATE_SUFFIX_DASH_COMPACT, "").trim();
  out = out.replace(LATEST_DASH, "").trim();
  return out;
}

function parseDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  if (value instanceof Date) return value;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function hasTrailingDate(modelId: string): {
  hasDate: boolean;
  parsed: Date | null;
} {
  const compact = DATE_SUFFIX_DASH_COMPACT.exec(modelId);
  if (compact) {
    const m = compact[1];
    const parsed = parseDate(`${m.slice(0, 4)}-${m.slice(4, 6)}-${m.slice(6, 8)}`);
    return { hasDate: true, parsed };
  }
  const hyphen = DATE_SUFFIX_DASH_HYPHEN.exec(modelId);
  if (hyphen) {
    return { hasDate: true, parsed: parseDate(hyphen[1]) };
  }
  return { hasDate: false, parsed: null };
}

function formatDate(d: Date): string {
  return `${MONTH_NAMES[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
}

export function formatModel(input: {
  display_name?: string | null;
  model_id: string;
  release_date?: string | null;
  disambiguate?: boolean;
}): FormattedModel {
  const raw = (input.display_name ?? input.model_id).trim();
  const primary = stripTrailingDate(raw) || raw;

  const { hasDate, parsed } = hasTrailingDate(input.model_id);
  const isRolling = !hasDate;
  const isExplicitLatest =
    LATEST_PAREN.test(raw) || input.model_id.toLowerCase().endsWith("-latest");
  const disambiguate = !!input.disambiguate;

  if (!disambiguate && !isExplicitLatest) {
    return { primary, secondary: null, isRolling };
  }

  let secondary: string | null = null;
  if (isRolling || isExplicitLatest) {
    secondary = "latest";
  } else {
    const d = parsed ?? parseDate(input.release_date ?? null);
    if (d) {
      secondary = formatDate(d);
    }
  }
  return { primary, secondary, isRolling };
}

/**
 * Annotate a list of catalog rows with collision-aware display fields.
 * Returns a new array; does not mutate inputs.
 */
export function annotateForDisplay<T extends { display_name?: string | null; model_id: string; release_date?: string | null }>(
  rows: T[],
): Array<T & { display: FormattedModel }> {
  const counts = new Map<string, number>();
  const primaries = rows.map((r) => {
    const fm = formatModel({ ...r, disambiguate: false });
    counts.set(fm.primary, (counts.get(fm.primary) ?? 0) + 1);
    return fm.primary;
  });
  return rows.map((r, i) => {
    const primary = primaries[i];
    return {
      ...r,
      display: formatModel({
        ...r,
        disambiguate: (counts.get(primary) ?? 0) > 1,
      }),
    };
  });
}
