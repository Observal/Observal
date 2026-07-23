export const CATEGORY_LABELS = {
  empty: 'Empty',
  precondition: 'Precondition',
  partial: 'Partial',
  conflict: 'Conflict',
  failure: 'Failure',
  permission: 'Permission',
  external: 'External',
  boundary: 'Boundary',
};

export function categoryLabel(category) {
  return CATEGORY_LABELS[category] ?? category;
}

/**
 * @param {{ gaps?: Array<{ flowId: string; screenId: string }> } | null} coverage
 * @param {string} flowId
 */
export function gapCountByScreenForFlow(coverage, flowId) {
  const map = new Map();
  for (const gap of coverage?.gaps ?? []) {
    if (gap.flowId !== flowId) continue;
    map.set(gap.screenId, (map.get(gap.screenId) ?? 0) + 1);
  }
  return map;
}

/**
 * @param {{ gaps?: Array<{ flowId: string; operationId: string; category: string; operation: string; screenId: string; reason: string }>; flows?: Array<{ id: string; score: number; gapCount: number }> } | null} coverage
 * @param {string} flowId
 */
export function flowCoverageInsights(coverage, flowId) {
  const gaps = (coverage?.gaps ?? []).filter((g) => g.flowId === flowId);
  const flowSummary = coverage?.flows?.find((f) => f.id === flowId);
  return {
    flowId,
    gaps,
    gapCount: gaps.length,
    score: flowSummary?.score ?? (gaps.length ? 0 : 100),
  };
}

/**
 * @param {{ category: string; operation: string }} gap
 */
export function formatGapSummary(gap) {
  return `Missing ${categoryLabel(gap.category).toLowerCase()} edge case for ${gap.operation}`;
}
