const SCENARIO_CATEGORIES = ['empty', 'failure', 'permission', 'conflict', 'boundary', 'precondition', 'external'];

/** @typedef {{ id: string; operation: string; subject: string; screenId: string; kind: 'read_collection' | 'read_resource' | 'mutate' | 'navigate'; flowId?: string }} DerivedOperation */
/** @typedef {{ operationId: string; category: string; required: boolean; scenarioId: string | null; covered: boolean; flowId?: string }} MatrixCell */
/** @typedef {{ flowId: string; operationId: string; operation: string; category: string; screenId: string; reason: string }} CoverageGap */
/** @typedef {{ id: string; title: string; screen: string; flow?: string; category: string; severity?: string; ux: string; trigger: { operation: string; subject: string; when: string }; description?: string }} ScenarioLike */

const WHEN_LABELS = {
  collection_empty: 'collection is empty',
  not_found: 'resource not found',
  validation_failed: 'validation fails',
  state_disallows: 'action not allowed in current state',
  concurrent_edit: 'concurrent edit conflict',
  session_expired: 'session expired',
  forbidden: 'access denied',
  dependency_unavailable: 'dependency unavailable',
  dependency_unmet: 'prerequisite not met',
  limit_reached: 'limit reached',
  timeout: 'request times out',
};

/**
 * @param {string} when
 */
export function whenToLabel(when) {
  return WHEN_LABELS[/** @type {keyof typeof WHEN_LABELS} */ (when)] ?? when.replace(/_/g, ' ');
}

/**
 * @param {{ operation: string; when: string }} trigger
 */
export function plainLanguageTrigger(trigger) {
  return `${trigger.operation} · ${whenToLabel(trigger.when)}`;
}

/**
 * @param {import('./run.mjs').RunScreenElement} el
 * @param {string} screenId
 * @returns {DerivedOperation | null}
 */
function operationFromElement(el, screenId) {
  const component = el.component;
  if (!component) return null;

  if (component === 'Table' || component === 'List' || component === 'Grid') {
    const source = el.source ?? el.name ?? screenId;
    return {
      id: `${screenId}:view:${source}`,
      operation: `view ${source}`,
      subject: source,
      screenId,
      kind: 'read_collection',
    };
  }

  if (component === 'Button' || component === 'Action' || component === 'Link') {
    const trigger = el.trigger ?? el.label?.toLowerCase() ?? 'action';
    const subject = el.name ?? trigger;
    return {
      id: `${screenId}:${trigger}`,
      operation: trigger.replace(/-/g, ' '),
      subject,
      screenId,
      kind: 'mutate',
    };
  }

  if (component === 'Form') {
    const name = el.name ?? 'form';
    return {
      id: `${screenId}:submit:${name}`,
      operation: `submit ${name}`,
      subject: name,
      screenId,
      kind: 'mutate',
    };
  }

  return null;
}

/**
 * @param {import('./run.mjs').RunScreen[]} screens
 * @returns {DerivedOperation[]}
 */
export function deriveOperations(screens = []) {
  /** @type {Map<string, DerivedOperation>} */
  const byId = new Map();

  for (const screen of screens) {
    for (const el of screen.elements ?? []) {
      const op = operationFromElement(el, screen.id);
      if (op && !byId.has(op.id)) byId.set(op.id, op);
    }
  }

  return [...byId.values()];
}

/**
 * @param {DerivedOperation} op
 * @returns {string[]}
 */
function requiredCategoriesForOperation(op) {
  switch (op.kind) {
    case 'read_collection':
      return ['empty', 'failure'];
    case 'read_resource':
      return ['empty', 'failure'];
    case 'mutate':
      return ['failure', 'permission'];
    case 'navigate':
      return [];
    default:
      return ['failure'];
  }
}

/**
 * @param {import('./run.mjs').RunFlow} flow
 */
export function screensForFlow(flow) {
  const screens = new Set();
  const graphs = flow.graphs?.length ? flow.graphs : [{ id: flow.id, transitions: [] }];
  for (const graph of graphs) {
    if (graph.entry_screen) screens.add(graph.entry_screen);
    for (const t of graph.transitions ?? []) {
      if (t.from) screens.add(t.from);
      if (t.target) screens.add(t.target);
    }
  }
  return screens;
}

/**
 * @param {ScenarioLike[]} scenarios
 * @param {DerivedOperation[]} operations
 * @param {string} flowId
 */
export function buildCoverageMatrix(scenarios = [], operations = [], flowId = 'default') {
  /** @type {MatrixCell[]} */
  const cells = [];
  /** @type {CoverageGap[]} */
  const gaps = [];

  for (const op of operations) {
    const required = requiredCategoriesForOperation(op);
    for (const category of SCENARIO_CATEGORIES) {
      const isRequired = required.includes(category);
      const match = scenarios.find(
        (s) =>
          s.category === category &&
          (s.trigger?.operation === op.operation ||
            s.trigger?.subject === op.subject ||
            s.screen === op.screenId),
      );
      cells.push({
        operationId: op.id,
        category,
        required: isRequired,
        scenarioId: match?.id ?? null,
        covered: Boolean(match),
        flowId,
      });
      if (isRequired && !match) {
        gaps.push({
          flowId,
          operationId: op.id,
          operation: op.operation,
          category,
          screenId: op.screenId,
          reason: `Missing ${category} edge case for "${op.operation}"`,
        });
      }
    }
  }

  const requiredCells = cells.filter((c) => c.required);
  const coveredRequired = requiredCells.filter((c) => c.covered).length;
  const score =
    requiredCells.length > 0 ? Math.round((coveredRequired / requiredCells.length) * 100) : 100;

  const taggedOperations = operations.map((op) => ({ ...op, flowId }));

  return { cells, gaps, score, operations: taggedOperations };
}

/**
 * @param {string} laminaRoot
 * @param {string} runId
 * @param {import('node:fs')} fs
 * @param {import('./run.mjs')} runMod
 */
export function loadCoverageForRun(laminaRoot, runId, fs, runMod) {
  const runPath = runMod.resolveRunPath(laminaRoot, runId);
  if (!fs.existsSync(runPath)) {
    return { ok: false, error: 'run not found', runId };
  }
  const run = runMod.parseRunJson(fs.readFileSync(runPath, 'utf8'));
  if (run.contract_version === '2.0') {
    const scenarios = run.scenarios ?? [];
    const scenarioRefs = new Set(scenarios.flatMap((scenario) => scenario.covers ?? []));
    const operations = (run.operations ?? []).map((operation) => ({
      id: operation.id,
      operation: operation.id,
      subject: operation.id,
      screenId: operation.surface_ref?.replace(/^surface\./, '') || '',
      kind: 'mutate',
    }));
    const gaps = (run.operations ?? [])
      .filter((operation) => operation.criticality === 'critical' && !scenarioRefs.has(`operation.${operation.id}`))
      .map((operation) => ({
        flowId: (run.workflows ?? []).find((workflow) =>
          (workflow.steps ?? []).some((step) => step.operation_ref === `operation.${operation.id}`),
        )?.id || 'default',
        operationId: operation.id,
        operation: operation.id,
        category: 'distinct_risk',
        screenId: operation.surface_ref?.replace(/^surface\./, '') || '',
        reason: `Missing distinct risk scenario for "${operation.id}"`,
      }));
    const flows = (run.workflows ?? []).map((workflow) => {
      const workflowGaps = gaps.filter((gap) => gap.flowId === workflow.id);
      const workflowOperations = (workflow.steps ?? []).length;
      return {
        id: workflow.id,
        score: workflowOperations ? Math.round(((workflowOperations - workflowGaps.length) / workflowOperations) * 100) : 100,
        gapCount: workflowGaps.length,
      };
    });
    return {
      ok: true,
      runId,
      run: { id: run.id, hook: run.hook, stage: run.stage },
      screens: run.surfaces ?? [],
      scenarios,
      flows,
      gaps,
      cells: [],
      operations,
      score: operations.length ? Math.round(((operations.length - gaps.length) / operations.length) * 100) : 100,
    };
  }
  const screens = /** @type {import('./run.mjs').RunScreen[]} */ (run.screens ?? []);
  const scenarios = /** @type {ScenarioLike[]} */ (run.scenarios ?? []);
  const runFlows = /** @type {import('./run.mjs').RunFlow[]} */ (run.flows ?? []);

  /** @type {CoverageGap[]} */
  const gaps = [];
  /** @type {MatrixCell[]} */
  const cells = [];
  /** @type {DerivedOperation[]} */
  const operations = [];
  /** @type {{ id: string; score: number; gapCount: number }[]} */
  const flows = [];

  if (runFlows.length) {
    for (const flow of runFlows) {
      const flowScreenIds = screensForFlow(flow);
      const flowScreens = screens.filter((s) => flowScreenIds.has(s.id));
      const flowScenarios = scenarios.filter((s) => !s.flow || s.flow === flow.id);
      const flowOperations = deriveOperations(flowScreens);
      const matrix = buildCoverageMatrix(flowScenarios, flowOperations, flow.id);
      gaps.push(...matrix.gaps);
      cells.push(...matrix.cells);
      operations.push(...matrix.operations);
      flows.push({ id: flow.id, score: matrix.score, gapCount: matrix.gaps.length });
    }
  } else {
    const matrix = buildCoverageMatrix(scenarios, deriveOperations(screens), 'default');
    gaps.push(...matrix.gaps);
    cells.push(...matrix.cells);
    operations.push(...matrix.operations);
    flows.push({ id: 'default', score: matrix.score, gapCount: matrix.gaps.length });
  }

  const requiredCells = cells.filter((c) => c.required);
  const coveredRequired = requiredCells.filter((c) => c.covered).length;
  const score =
    requiredCells.length > 0 ? Math.round((coveredRequired / requiredCells.length) * 100) : 100;

  return {
    ok: true,
    runId,
    run: {
      id: run.id,
      hook: run.hook,
      command: run.command,
    },
    screens,
    scenarios,
    flows,
    gaps,
    cells,
    operations,
    score,
  };
}
