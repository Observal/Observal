"use client";

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

const kindClasses: Record<string, string> = {
  context: "bg-transparent text-foreground",
  remove: "bg-[rgba(248,81,73,0.10)] text-foreground",
  add: "bg-[rgba(63,185,80,0.10)] text-foreground",
  empty: "bg-muted/30",
  "hunk-header": "bg-muted/50 text-muted-foreground italic",
};

const lineNumClasses: Record<string, string> = {
  context: "text-muted-foreground/50",
  remove: "text-[rgba(248,81,73,0.5)]",
  add: "text-[rgba(63,185,80,0.5)]",
  empty: "text-transparent",
  "hunk-header": "text-transparent",
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
                <td className="px-3 whitespace-pre-wrap break-all">
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
      {/* Column headers */}
      <div className="flex shrink-0 border-b border-border text-xs font-medium text-muted-foreground">
        <div className="flex-1 px-4 py-2 border-r border-border">
          {isNewFile ? (
            <span className="italic">No previous version</span>
          ) : (
            <span>v{versionA}</span>
          )}
        </div>
        <div className="flex-1 px-4 py-2">
          <span>v{versionB}</span>
        </div>
      </div>

      {/* Split panes */}
      <div className="flex flex-1 min-h-0 overflow-y-auto">
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
    </div>
  );
}
