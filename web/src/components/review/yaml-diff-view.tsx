// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

export interface YamlDiffViewProps {
  diff: string;
  versionA: string;
  versionB: string;
}

type DiffLineKind = "context" | "add" | "remove" | "hunk-header" | "file-header";

interface DiffLine {
  kind: DiffLineKind;
  text: string;
}

interface SplitRow {
  leftNum: number | null;
  rightNum: number | null;
  leftText: string | null;
  rightText: string | null;
  leftKind: "context" | "remove" | "empty" | "hunk-header";
  rightKind: "context" | "add" | "empty" | "hunk-header";
}

function parseDiffLines(raw: string): DiffLine[] {
  return raw.split("\n").map((line): DiffLine => {
    if (line.startsWith("@@")) return { kind: "hunk-header", text: line };
    if (line.startsWith("---") || line.startsWith("+++")) return { kind: "file-header", text: line };
    if (line.startsWith("+")) return { kind: "add", text: line.slice(1) };
    if (line.startsWith("-")) return { kind: "remove", text: line.slice(1) };
    // context lines have a leading space in unified diff; strip it
    return { kind: "context", text: line.startsWith(" ") ? line.slice(1) : line };
  });
}

/**
 * Convert parsed diff lines into aligned split rows.
 * Removes and adds within the same hunk are interleaved: we pair them
 * (remove[0] ↔ add[0], …) then flush the longer side with empty partners.
 */
function buildSplitRows(lines: DiffLine[]): SplitRow[] {
  const rows: SplitRow[] = [];
  let leftNum = 0;
  let rightNum = 0;

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    if (line.kind === "file-header") {
      i++;
      continue;
    }

    if (line.kind === "hunk-header") {
      // Parse @@ -l,s +l,s @@ and reset counters
      const m = line.text.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (m) {
        leftNum = parseInt(m[1], 10) - 1;
        rightNum = parseInt(m[2], 10) - 1;
      }
      rows.push({
        leftNum: null, rightNum: null,
        leftText: line.text, rightText: null,
        leftKind: "hunk-header", rightKind: "empty",
      });
      i++;
      continue;
    }

    if (line.kind === "context") {
      leftNum++;
      rightNum++;
      rows.push({
        leftNum, rightNum,
        leftText: line.text, rightText: line.text,
        leftKind: "context", rightKind: "context",
      });
      i++;
      continue;
    }

    // Collect a contiguous block of removes then adds
    const removes: string[] = [];
    const adds: string[] = [];
    while (i < lines.length && lines[i].kind === "remove") {
      removes.push(lines[i].text);
      i++;
    }
    while (i < lines.length && lines[i].kind === "add") {
      adds.push(lines[i].text);
      i++;
    }

    const pairCount = Math.max(removes.length, adds.length);
    for (let p = 0; p < pairCount; p++) {
      const hasLeft = p < removes.length;
      const hasRight = p < adds.length;
      if (hasLeft) leftNum++;
      if (hasRight) rightNum++;
      rows.push({
        leftNum: hasLeft ? leftNum : null,
        rightNum: hasRight ? rightNum : null,
        leftText: hasLeft ? removes[p] : null,
        rightText: hasRight ? adds[p] : null,
        leftKind: hasLeft ? "remove" : "empty",
        rightKind: hasRight ? "add" : "empty",
      });
    }
  }

  return rows;
}

// Added/removed rows were literal rgba() copies of GitHub's diff palette,
// which ignored the active preset and light/dark mode. They ride the semantic
// tokens now; the gutter marker below carries the same distinction without
// relying on the tint, since a 10% wash is not a reliable signal on its own.
const kindClasses: Record<string, string> = {
  context: "bg-transparent text-foreground",
  remove: "bg-destructive/10 text-foreground",
  add: "bg-success/10 text-foreground",
  empty: "bg-muted/30",
  "hunk-header": "bg-muted/50 text-muted-foreground italic",
};

const lineNumClasses: Record<string, string> = {
  context: "text-muted-foreground/50",
  remove: "text-destructive/70",
  add: "text-success/70",
  empty: "text-transparent",
  "hunk-header": "text-transparent",
};

/**
 * Spoken equivalent of the ± marker. `parseDiffLines` strips the leading +/-
 * from the text, and the marker cell is `aria-hidden`, so without this a
 * screen reader hears added and removed rows as identical plain YAML. In the
 * split view the only other cue is which column a row sits in, which is not
 * conveyed either.
 */
const kindSrLabels: Record<string, string> = {
  context: "",
  remove: "Removed line: ",
  add: "Added line: ",
  empty: "",
  "hunk-header": "",
};

/** The ± column, so add/remove reads without depending on the row tint. */
const kindMarkers: Record<string, string> = {
  context: "",
  remove: "−",
  add: "+",
  empty: "",
  "hunk-header": "",
};

function DiffPane({
  rows,
  side,
}: {
  rows: SplitRow[];
  side: "left" | "right";
}) {
  return (
    <div className="flex-1 min-w-0 overflow-x-auto font-[family-name:var(--font-mono)] text-xs leading-5">
      <table className="w-full border-collapse">
        <tbody>
          {rows.map((row, idx) => {
            const num = side === "left" ? row.leftNum : row.rightNum;
            const text = side === "left" ? row.leftText : row.rightText;
            const kind = side === "left" ? row.leftKind : row.rightKind;

            return (
              <tr key={idx} className={kindClasses[kind]}>
                <td
                  className={`select-none w-10 shrink-0 px-2 text-right tabular-nums ${lineNumClasses[kind]} border-r border-border/40`}
                >
                  {num ?? ""}
                </td>
                <td
                  className={`select-none w-4 text-center tabular-nums ${lineNumClasses[kind]}`}
                  aria-hidden="true"
                >
                  {kindMarkers[kind]}
                </td>
                <td className="px-3 whitespace-pre-wrap break-words leading-relaxed">
                  {kindSrLabels[kind] && (
                    <span className="sr-only">{kindSrLabels[kind]}</span>
                  )}
                  {text ?? ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Single-column diff for narrow viewports. The side-by-side panes each get
 * roughly half of an already-small width, so below `md` we fall back to a
 * unified view rather than two unreadable columns — dropping the left pane
 * instead would hide every removed line, which a reviewer needs to see.
 */
function UnifiedPane({ lines }: { lines: DiffLine[] }) {
  return (
    <div className="overflow-x-auto font-[family-name:var(--font-mono)] text-xs leading-5">
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, idx) => {
            if (line.kind === "file-header") return null;
            const kind = line.kind === "hunk-header" ? "hunk-header" : line.kind;
            return (
              <tr key={idx} className={kindClasses[kind]}>
                <td
                  className={`select-none w-4 pl-2 text-center ${lineNumClasses[kind]}`}
                  aria-hidden="true"
                >
                  {kindMarkers[kind]}
                </td>
                <td className="px-3 whitespace-pre-wrap break-words leading-relaxed">
                  {kindSrLabels[kind] && (
                    <span className="sr-only">{kindSrLabels[kind]}</span>
                  )}
                  {line.text}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A read-only, line-numbered YAML listing — what a first release shows in place
 * of a diff, since there is no previous version to compare against.
 *
 * Lives here so it shares the gutter, wrapping and monospace treatment with the
 * diff panes above; it was previously inlined twice in `review-diff-sheet.tsx`.
 * Deliberately not the `Table` primitive: that is styled for data rows, and
 * this is a code listing.
 */
export function YamlSnapshot({ source }: { source: string }) {
	return (
		<div className="overflow-x-auto font-[family-name:var(--font-mono)] text-xs leading-5">
			<table className="w-full border-collapse">
				<tbody>
					{source.split("\n").map((line, i) => (
						<tr key={i} className="hover:bg-muted/30">
							<td className="select-none w-10 shrink-0 px-2 text-right tabular-nums text-muted-foreground/50 border-r border-border/40">
								{i + 1}
							</td>
							<td className="px-3 whitespace-pre-wrap break-words text-foreground leading-relaxed">
								{line}
							</td>
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
}

export function YamlDiffView({ diff, versionA, versionB }: YamlDiffViewProps) {
  if (!diff || diff.trim() === "") {
    return (
      <div className="flex items-center justify-center h-32 text-sm text-muted-foreground">
        No changes between these versions.
      </div>
    );
  }

  const lines = parseDiffLines(diff);
  // Check if this is an all-additions diff (first version, no prior)
  const isNewFile = lines.every(
    (l) => l.kind === "add" || l.kind === "file-header" || l.kind === "hunk-header",
  );

  const rows = buildSplitRows(lines);

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Column headers — the split pair collapses to one label when unified */}
      <div className="flex shrink-0 border-b border-border text-xs font-medium text-muted-foreground">
        <div className="hidden flex-1 px-4 py-2 border-r border-border md:block">
          {isNewFile ? (
            <span className="italic">No previous version</span>
          ) : (
            <span>v{versionA}</span>
          )}
        </div>
        <div className="flex-1 px-4 py-2">
          <span className="md:hidden">
            {isNewFile ? `v${versionB}` : `v${versionA} → v${versionB}`}
          </span>
          <span className="hidden md:inline">v{versionB}</span>
        </div>
      </div>

      {/* Split panes at md and up, unified below */}
      <div className="hidden flex-1 min-h-0 overflow-y-auto md:flex">
        <div className="flex-1 border-r border-border overflow-x-auto">
          {isNewFile ? (
            <div className="flex items-center justify-center h-full text-sm text-muted-foreground/50 italic select-none">
              (empty)
            </div>
          ) : (
            <DiffPane rows={rows} side="left" />
          )}
        </div>
        <div className="flex-1 overflow-x-auto">
          <DiffPane rows={rows} side="right" />
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto md:hidden">
        <UnifiedPane lines={lines} />
      </div>
    </div>
  );
}
