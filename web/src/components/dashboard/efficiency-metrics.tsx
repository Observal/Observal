// SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { useRef, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import gsap from "gsap";
import type { SessionEfficiencyData } from "@/hooks/use-api";

type EfficiencyData = SessionEfficiencyData;

function ratingColor(r: number): string {
  if (r >= 0.85) return "#10b981";
  if (r >= 0.7) return "#3b82f6";
  if (r >= 0.5) return "#f59e0b";
  return "#ef4444";
}

function interpretStyle(label: string): { color: string; bg: string; border: string } {
  if (label.startsWith("Excellent")) return { color: "#10b981", bg: "rgba(16,185,129,0.08)", border: "rgba(16,185,129,0.2)" };
  if (label.startsWith("Good"))      return { color: "#3b82f6", bg: "rgba(59,130,246,0.08)", border: "rgba(59,130,246,0.2)" };
  if (label.startsWith("Fair"))      return { color: "#f59e0b", bg: "rgba(245,158,11,0.08)", border: "rgba(245,158,11,0.2)" };
  if (label.startsWith("Minor"))     return { color: "#f59e0b", bg: "rgba(245,158,11,0.08)", border: "rgba(245,158,11,0.2)" };
  if (label.startsWith("None") || label === "N/A") return { color: "#64748b", bg: "rgba(100,116,139,0.06)", border: "rgba(100,116,139,0.15)" };
  return { color: "#ef4444", bg: "rgba(239,68,68,0.08)", border: "rgba(239,68,68,0.2)" };
}

const METRIC_LABELS: Record<string, { label: string; description: string }> = {
  path_efficiency_ratio:      { label: "Path Efficiency",      description: "Effective actions / total actions" },
  token_waste_rate:           { label: "Token Waste",           description: "Tokens spent on reverted work" },
  first_pass_success_rate:    { label: "First Pass Success",    description: "Writes that stuck without revert" },
  write_without_verify_ratio: { label: "Write Without Verify",  description: "Writes not followed by a build/test" },
  file_churn_rate:            { label: "File Churn",            description: "Files rewritten multiple times" },
  repetition_cycles:          { label: "Repetition Cycles",     description: "Detected edit-error-fix loops" },
  duplicate_tool_call_count:  { label: "Duplicate Calls",       description: "Identical tool calls repeated" },
};

export function EfficiencyMetrics({ data }: { data: EfficiencyData }) {
  const rating = data.efficiency_rating;
  const color = ratingColor(rating);
  const containerRef = useRef<HTMLDivElement>(null);
  const animatedRef = useRef(false);

  // Check if there are no tool calls (rating is 0 and no meaningful metrics)
  const hasNoToolCalls = rating === 0 && Object.values(data.efficiency_metrics).every(v => v === 0 || v === null);

  useEffect(() => {
    if (animatedRef.current || !containerRef.current || hasNoToolCalls) return;
    animatedRef.current = true;

    const scoreEl = containerRef.current.querySelector("[data-score-number]");
    const barFill = containerRef.current.querySelector("[data-bar-fill]");
    const rows = containerRef.current.querySelectorAll("[data-metric-row]");
    const warnings = containerRef.current.querySelectorAll("[data-warning]");

    gsap.set(rows, { opacity: 0, x: -12 });
    gsap.set(warnings, { opacity: 0, y: 8 });

    const tl = gsap.timeline({ defaults: { ease: "expo.out" } });

    if (scoreEl) {
      const target = { val: 0 };
      tl.to(target, {
        val: rating * 100,
        duration: 1.2,
        ease: "expo.out",
        onUpdate: () => {
          scoreEl.textContent = Math.round(target.val).toString();
        },
      }, 0);
    }

    if (barFill) {
      gsap.set(barFill, { width: "0%" });
      tl.to(barFill, { width: `${rating * 100}%`, duration: 1, ease: "expo.out" }, 0.1);
    }

    tl.to(rows, { opacity: 1, x: 0, duration: 0.5, stagger: 0.04 }, 0.3);
    tl.to(warnings, { opacity: 1, y: 0, duration: 0.4, stagger: 0.06 }, "-=0.2");
  }, [rating, hasNoToolCalls]);

  const entries = Object.entries(data.interpretation);

  return (
    <Card className="overflow-hidden border-0 shadow-none bg-transparent">
      <CardHeader className="pb-2 px-0">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold tracking-tight flex items-center gap-2">
            <span
              className="w-5 h-5 rounded flex items-center justify-center text-[10px] font-black"
              style={{ background: color + "1a", color, border: `1px solid ${color}33` }}
            >
              E
            </span>
            Process Efficiency
          </CardTitle>
          <span
            className="text-[10px] font-mono px-2 py-0.5 rounded"
            style={{ color: "rgba(148,163,184,0.5)", background: "rgba(148,163,184,0.06)" }}
          >
            v{data.scorer_version}
          </span>
        </div>
      </CardHeader>

      <CardContent className="px-0 pt-0" ref={containerRef}>
        <div
          className="rounded-xl overflow-hidden"
          style={{
            background: "linear-gradient(145deg, rgba(15,23,42,0.4) 0%, rgba(15,23,42,0.2) 100%)",
            border: "1px solid rgba(100,116,139,0.1)",
          }}
        >
          {/* Hero score section */}
          {!hasNoToolCalls && (
            <div className="px-5 pt-5 pb-4">
              <div className="flex items-end gap-4">
                <div className="flex items-baseline gap-1">
                  <span
                    data-score-number
                    className="text-5xl font-black tabular-nums leading-none"
                    style={{ color, textShadow: `0 0 40px ${color}40` }}
                  >
                    0
                  </span>
                  <span className="text-lg font-medium" style={{ color: color + "80" }}>/100</span>
                </div>
                <div className="flex-1 pb-2">
                  <div
                    className="h-2 rounded-full overflow-hidden"
                    style={{ background: "rgba(100,116,139,0.08)" }}
                  >
                    <div
                      data-bar-fill
                      className="h-full rounded-full"
                      style={{
                        background: `linear-gradient(90deg, ${color}cc, ${color})`,
                        boxShadow: `0 0 12px ${color}50`,
                        width: "0%",
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Metrics grid */}
          {entries.length > 0 && (
            <div className="px-4 pb-4 space-y-1">
              {entries.map(([key, label]) => {
                const meta = METRIC_LABELS[key] || { label: key, description: "" };
                const rawValue = data.efficiency_metrics[key];
                const displayValue = rawValue === null || rawValue === undefined
                  ? "—"
                  : typeof rawValue === "number" && !Number.isInteger(rawValue)
                    ? rawValue.toFixed(2)
                    : String(rawValue);
                const style = interpretStyle(label);

                return (
                  <div
                    key={key}
                    data-metric-row
                    className="flex items-center justify-between py-2 px-3 rounded-lg group"
                    style={{ background: "rgba(100,116,139,0.03)" }}
                  >
                    <div className="flex flex-col min-w-0 mr-3">
                      <span className="text-[12px] font-medium" style={{ color: "rgba(226,232,240,0.8)" }}>
                        {meta.label}
                      </span>
                      <span className="text-[10px]" style={{ color: "rgba(148,163,184,0.4)" }}>
                        {meta.description}
                      </span>
                    </div>
                    <div className="flex items-center gap-2.5 shrink-0">
                      <span
                        className="text-xs font-mono font-bold tabular-nums"
                        style={{ color: "rgba(226,232,240,0.7)" }}
                      >
                        {displayValue}
                      </span>
                      <span
                        className="text-[10px] font-semibold px-2 py-0.5 rounded-md whitespace-nowrap"
                        style={{ color: style.color, background: style.bg, border: `1px solid ${style.border}` }}
                      >
                        {label.split("(")[0].trim()}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Warnings */}
          {data.warnings.length > 0 && (
            <div className="p-4 space-y-1.5">
              {data.warnings.map((w, i) => (
                <div
                  key={i}
                  data-warning
                  className="flex items-start gap-2.5 px-3 py-2 rounded-lg text-[11px]"
                  style={{ background: "rgba(245,158,11,0.04)", border: "1px solid rgba(245,158,11,0.1)" }}
                >
                  <span
                    className="shrink-0 w-4 h-4 rounded flex items-center justify-center text-[9px] font-black mt-0.5"
                    style={{ background: "rgba(245,158,11,0.12)", color: "#f59e0b" }}
                  >
                    !
                  </span>
                  <span style={{ color: "rgba(251,191,36,0.8)" }}>{w}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
