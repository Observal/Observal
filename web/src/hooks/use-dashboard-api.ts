// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
// SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import {
  useQuery,
} from "@tanstack/react-query";
import {
  dashboard,
  exec,
} from "@/lib/api";

// ── Dashboard ───────────────────────────────────────────────────────

export function useOverviewStats(range?: string) {
  return useQuery({ queryKey: ["overview", "stats", range], queryFn: () => dashboard.stats(range) });
}

export function useTopMcps() {
  return useQuery({ queryKey: ["overview", "top-mcps"], queryFn: dashboard.topMcps });
}

export function useTopAgents(limit?: number) {
  return useQuery({ queryKey: ["overview", "top-agents", limit], queryFn: () => dashboard.topAgents(limit) });
}

export function useTrends(range?: string) {
  return useQuery({ queryKey: ["overview", "trends", range], queryFn: () => dashboard.trends(range) });
}

// ── New Dashboard Hooks ─────────────────────────────────────────────

export function useTokenStats(range?: string) {
  return useQuery({ queryKey: ['dashboard', 'tokens', range], queryFn: () => dashboard.tokenStats(range) });
}
export function useIdeUsage() {
  return useQuery({ queryKey: ['dashboard', 'ide-usage'], queryFn: dashboard.ideUsage });
}
// ── Exec Dashboard ─────────────────────────────────────────────────

export function useExecAdoption() {
  return useQuery({ queryKey: ["exec", "adoption"], queryFn: exec.adoption });
}

export function useExecAgentCounts() {
  return useQuery({ queryKey: ["exec", "agent-counts"], queryFn: exec.agentCounts });
}

export function useExecUsageByCategory(range?: string) {
  return useQuery({ queryKey: ["exec", "usage-by-category", range], queryFn: () => exec.usageByCategory(range) });
}

export function useExecPlatformCoverage() {
  return useQuery({ queryKey: ["exec", "platform-coverage"], queryFn: exec.platformCoverage });
}

export function useExecPlatforms() {
  return useQuery({ queryKey: ["exec", "platforms"], queryFn: exec.platforms });
}

export function useExecVelocity() {
  return useQuery({ queryKey: ["exec", "velocity"], queryFn: exec.velocity });
}

export function useExecTopAgents(limit?: number) {
  return useQuery({ queryKey: ["exec", "top-agents", limit], queryFn: () => exec.topAgents(limit) });
}

export function useExecDepartments(range?: string) {
  return useQuery({ queryKey: ["exec", "departments", range], queryFn: () => exec.departments(range) });
}

export function useExecDeptTokens(range?: string) {
  return useQuery({ queryKey: ["exec", "dept-tokens", range], queryFn: () => exec.deptTokens(range) });
}

export function useExecCostSummary(range?: string) {
  return useQuery({ queryKey: ["exec", "cost-summary", range], queryFn: () => exec.costSummary(range) });
}

export function useExecConfig() {
  return useQuery({ queryKey: ["exec", "config"], queryFn: exec.config });
}

export function useExecROIProjections() {
  return useQuery({ queryKey: ["exec", "roi-projections"], queryFn: exec.roiProjections });
}

export function useExecStrategicInsights() {
  return useQuery({ queryKey: ["exec", "strategic-insights"], queryFn: exec.strategicInsights });
}

export function useExecDeveloperBreakdown(limit?: number) {
  return useQuery({ queryKey: ["exec", "developer-breakdown", limit], queryFn: () => exec.developerBreakdown(limit) });
}

export function useExecInactivityAlerts() {
  return useQuery({ queryKey: ["exec", "inactivity-alerts"], queryFn: exec.inactivityAlerts });
}

export function useExecTimeToValue() {
  return useQuery({ queryKey: ["exec", "time-to-value"], queryFn: exec.timeToValue });
}

export function useExecAIInsights() {
  return useQuery({ queryKey: ["exec", "ai-insights"], queryFn: exec.aiInsights, staleTime: 10 * 60 * 1000 });
}
