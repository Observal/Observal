// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
// SPDX-License-Identifier: AGPL-3.0-only


import { Badge } from "@/components/ui/badge";

interface ScoreOverviewProps {
  displayScore: number;
  grade: string;
  dimensionScores: Record<string, number>;
  penaltyCount?: number;
  compact?: boolean;
}

export const DIMENSION_META: Record<string, { label: string; color: string; hidden?: boolean }> = {
  goal_completion: { label: "Goal Completion", color: "bg-emerald-500" },
  tool_efficiency: { label: "Tool Efficiency", color: "bg-blue-500" },
  tool_failures: { label: "Tool Failures", color: "bg-amber-500" },
  factual_grounding: { label: "Factual Grounding", color: "bg-violet-500" },
  thought_process: { label: "Thought Process", color: "bg-cyan-500" },
  adversarial_robustness: { label: "Adversarial", color: "bg-rose-500", hidden: true },
};

function gradeColor(grade: string): string {
  const g = grade.toUpperCase();
  if (g.startsWith("A")) return "text-success";
  if (g.startsWith("B")) return "text-info";
  if (g.startsWith("C")) return "text-warning";
  return "text-destructive";
}

function gradeBg(grade: string): string {
  const g = grade.toUpperCase();
  if (g.startsWith("A")) return "bg-success/10 border-success/20";
  if (g.startsWith("B")) return "bg-info/10 border-info/20";
  if (g.startsWith("C")) return "bg-warning/10 border-warning/20";
  return "bg-destructive/10 border-destructive/20";
}

function scoreBarColor(score: number): string {
  if (score >= 85) return "bg-emerald-500";
  if (score >= 70) return "bg-blue-500";
  if (score >= 55) return "bg-amber-500";
  return "bg-red-500";
}

export function ScoreOverview({
  displayScore,
  grade,
  dimensionScores,
  penaltyCount,
  compact = false,
}: ScoreOverviewProps) {
  const dims = Object.entries(dimensionScores).filter(
    ([key, value]) => value !== null && !DIMENSION_META[key]?.hidden
  );

  if (compact) {
    return (
      <div className="space-y-3">
        {/* Compact: score + grade inline */}
        <div className="flex items-center gap-3">
          <div className={`flex items-center justify-center w-10 h-10 rounded-md border ${gradeBg(grade)}`}>
            <span className={`text-lg font-bold font-[family-name:var(--font-display)] ${gradeColor(grade)}`}>
              {grade}
            </span>
          </div>
          <div>
            <p className="text-base font-semibold font-[family-name:var(--font-mono)] tabular-nums">
              {displayScore.toFixed(1)}<span className="text-xs text-muted-foreground">/10</span>
            </p>
            {penaltyCount != null && (
              <p className="text-[10px] text-muted-foreground">{penaltyCount} penalties</p>
            )}
          </div>
        </div>
        {/* Compact dimension bars */}
        <div className="space-y-1.5">
          {dims.map(([key, score]) => {
            const meta = DIMENSION_META[key];
            const clampedScore = Math.max(0, Math.min(100, score));
            return (
              <div key={key} className="flex items-center gap-2">
                <span className="text-[10px] text-muted-foreground w-20 truncate">
                  {meta?.label ?? key}
                </span>
                <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${scoreBarColor(clampedScore)}`}
                    style={{ width: `${clampedScore}%` }}
                  />
                </div>
                <span className="text-[10px] font-[family-name:var(--font-mono)] text-muted-foreground w-7 text-right tabular-nums">
                  {Math.round(clampedScore)}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Hero score */}
      <div className="flex items-center gap-5">
        <div className={`flex items-center justify-center w-16 h-16 rounded-lg border ${gradeBg(grade)}`}>
          <span className={`text-3xl font-bold font-[family-name:var(--font-display)] ${gradeColor(grade)}`}>
            {grade}
          </span>
        </div>
        <div>
          <p className="text-2xl font-bold font-[family-name:var(--font-mono)] tabular-nums">
            {displayScore.toFixed(1)}<span className="text-sm text-muted-foreground font-normal">/10</span>
          </p>
          <p className="text-xs text-muted-foreground">
            Display Score
            {penaltyCount != null && (
              <span className="ml-2">
                <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                  {penaltyCount} penalties
                </Badge>
              </span>
            )}
          </p>
        </div>
      </div>

      {/* Dimension breakdown */}
      <div className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Dimension Scores
        </h4>
        <div className="space-y-2.5">
          {dims.map(([key, score]) => {
            const meta = DIMENSION_META[key];
            const clampedScore = Math.max(0, Math.min(100, score));
            return (
              <div key={key} className="space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">
                    {meta?.label ?? key}
                  </span>
                  <span className="text-xs font-[family-name:var(--font-mono)] tabular-nums">
                    {Math.round(clampedScore)}<span className="text-muted-foreground">/100</span>
                  </span>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${meta?.color ?? scoreBarColor(clampedScore)}`}
                    style={{ width: `${clampedScore}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
