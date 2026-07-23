import fs from 'node:fs';
import path from 'node:path';

export const CONTRACT_VERSION = '2.0';
export const RUN_STATUSES = new Set(['draft', 'needs_input', 'ready_to_build', 'verifying', 'complete']);
export const PRODUCT_STAGES = new Set(['spark', 'shape', 'harden']);
export const CRITICALITIES = new Set(['critical', 'supporting', 'deferred']);
export const SOURCES = new Set(['user', 'repository', 'derived', 'assumed', 'persona_hypothesis']);
export const CONFIDENCES = new Set(['low', 'medium', 'high']);
export const DECISION_CLASSES = new Set([
  'structural',
  'safety_integrity',
  'reversible_default',
  'policy_fork',
  'desirability_hypothesis',
  'evidence_backed',
]);
export const FINDING_FIX_TARGETS = new Set(['product', 'contract', 'ops']);
export const PROOF_BUDGET_LIMITS = Object.freeze({
  critical_promises: 3,
  active_operations: 10,
  active_workflows: 6,
  active_dependencies: 6,
  active_surfaces: 6,
  proofs: 12,
});
export const MAX_READY_CONTRACT_BYTES = 48 * 1024;
export const PROOF_EVIDENCE_LEVELS = new Set(['domain', 'boundary', 'journey']);
export const PROOF_TEST_REQUIREMENTS = new Set([
  'controlled_clock',
  'separate_actor_contexts',
  'restart_or_reload',
  'dependency_failure',
  'replay_or_concurrency',
  'responsive',
  'accessibility',
]);
const KIND_BY_COLLECTION = Object.freeze({
  actors: 'actor',
  entities: 'entity',
  operations: 'operation',
  workflows: 'workflow',
  invariants: 'invariant',
  dependencies: 'dependency',
  surfaces: 'surface',
  scenarios: 'scenario',
});
const COLLECTION_BY_KIND = Object.freeze(Object.fromEntries(Object.entries(KIND_BY_COLLECTION).map(([collection, kind]) => [kind, collection])));

function array(value) {
  return Array.isArray(value) ? value : [];
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function refParts(ref) {
  const match = String(ref || '').match(/^(promise|actor|entity|operation|workflow|invariant|dependency|surface|scenario)\.([A-Za-z0-9_-]+)$/);
  return match ? { kind: match[1], id: match[2] } : null;
}

function nodeIndex(run) {
  const intent = object(run.intent);
  return {
    promise: new Set(array(intent.critical_promises).map((item) => item?.id).filter(Boolean)),
    actor: new Set(array(run.actors).map((item) => item?.id).filter(Boolean)),
    entity: new Set(array(run.entities).map((item) => item?.id).filter(Boolean)),
    operation: new Set(array(run.operations).map((item) => item?.id).filter(Boolean)),
    workflow: new Set(array(run.workflows).map((item) => item?.id).filter(Boolean)),
    invariant: new Set(array(run.invariants).map((item) => item?.id).filter(Boolean)),
    dependency: new Set(array(run.dependencies).map((item) => item?.id).filter(Boolean)),
    surface: new Set(array(run.surfaces).map((item) => item?.id).filter(Boolean)),
    scenario: new Set(array(run.scenarios).map((item) => item?.id).filter(Boolean)),
  };
}

function validateUniqueIds(items, label, rel, errors) {
  const seen = new Set();
  for (const item of array(items)) {
    if (!item?.id) {
      errors.push(`${rel}: ${label} node missing id`);
      continue;
    }
    if (seen.has(item.id)) errors.push(`${rel}: duplicate ${label} id "${item.id}"`);
    seen.add(item.id);
  }
}

function validateNodeMetadata(item, label, rel, errors, { require = false } = {}) {
  const prefix = `${rel}: ${label} "${item?.id || '?'}"`;
  for (const key of ['criticality', 'source', 'confidence', 'relevance_reason']) {
    if (require && !item?.[key]) errors.push(`${prefix} missing ${key}`);
  }
  if (item?.criticality && !CRITICALITIES.has(item.criticality)) {
    errors.push(`${prefix} invalid criticality "${item.criticality}"`);
  }
  if (item?.source && !SOURCES.has(item.source)) errors.push(`${prefix} invalid source "${item.source}"`);
  if (item?.confidence && !CONFIDENCES.has(item.confidence)) {
    errors.push(`${prefix} invalid confidence "${item.confidence}"`);
  }
}

function validateRef(ref, indexes, rel, owner, errors) {
  const parsed = refParts(ref);
  if (!parsed) {
    errors.push(`${rel}: ${owner} has invalid ref "${ref}"`);
    return;
  }
  if (!indexes[parsed.kind]?.has(parsed.id)) {
    errors.push(`${rel}: ${owner} references unknown ${parsed.kind}.${parsed.id}`);
  }
}

function validatePrerequisiteCycles(run, rel, errors) {
  const edges = new Map();
  for (const dependency of array(run.dependencies)) {
    if (dependency?.type !== 'prerequisite') continue;
    const from = String(dependency.from || '');
    const to = String(dependency.to || '');
    if (!edges.has(from)) edges.set(from, []);
    edges.get(from).push(to);
  }
  const active = new Set();
  const visited = new Set();
  const visit = (node) => {
    if (active.has(node)) return true;
    if (visited.has(node)) return false;
    visited.add(node);
    active.add(node);
    for (const next of edges.get(node) || []) {
      if (visit(next)) return true;
    }
    active.delete(node);
    return false;
  };
  for (const node of edges.keys()) {
    if (visit(node)) {
      errors.push(`${rel}: prerequisite dependency cycle includes ${node}`);
      break;
    }
  }
}

function validateProofPacket(run, rel, errors, indexes, { required = false } = {}) {
  const budget = object(run.proof_budget);
  const proofs = array(run.proofs);
  if (!required && !Object.keys(budget).length && !proofs.length) return;

  if (!Object.keys(budget).length) errors.push(`${rel}: proof_budget is required`);
  if (required && !proofs.length) errors.push(`${rel}: proofs[] requires at least one proof obligation`);
  if (budget.strategy !== 'smallest_complete_slice') errors.push(`${rel}: proof_budget.strategy must be "smallest_complete_slice"`);
  if (!String(budget.rationale || '').trim()) errors.push(`${rel}: proof_budget.rationale is required`);

  const declaredLimits = {
    critical_promises: budget.max_critical_promises,
    active_operations: budget.max_active_operations,
    active_workflows: budget.max_active_workflows,
    active_dependencies: budget.max_active_dependencies,
    active_surfaces: budget.max_active_surfaces,
    proofs: budget.max_proofs,
  };
  for (const [key, hardLimit] of Object.entries(PROOF_BUDGET_LIMITS)) {
    const value = declaredLimits[key];
    const minimum = key === 'active_dependencies' ? 0 : 1;
    if (!Number.isInteger(value) || value < minimum || value > hardLimit) {
      errors.push(`${rel}: proof_budget ${key} must be an integer from ${minimum} to ${hardLimit}`);
    }
  }

  const active = (items) => array(items).filter((item) => item?.criticality !== 'deferred');
  const actualCounts = {
    critical_promises: array(run.intent?.critical_promises).length,
    active_operations: active(run.operations).length,
    active_workflows: active(run.workflows).length,
    active_dependencies: active(run.dependencies).length,
    active_surfaces: active(run.surfaces).length,
    proofs: proofs.length,
  };
  for (const [key, actual] of Object.entries(actualCounts)) {
    const declared = declaredLimits[key];
    if (Number.isInteger(declared) && actual > declared) errors.push(`${rel}: ${key} count ${actual} exceeds declared proof budget ${declared}`);
  }

  const serializedBytes = Buffer.byteLength(JSON.stringify(run));
  if (required && serializedBytes > MAX_READY_CONTRACT_BYTES) {
    errors.push(`${rel}: ready proof-carrying contract is ${serializedBytes} bytes; maximum is ${MAX_READY_CONTRACT_BYTES}`);
  }

  const proofIds = new Set();
  const covered = {
    promise: new Set(),
    operation: new Set(),
    workflow: new Set(),
    invariant: new Set(),
    dependency: new Set(),
    surface: new Set(),
  };
  const allRequirements = new Set();
  for (const proof of proofs) {
    const label = `proof "${proof?.id || '?'}"`;
    if (!proof?.id) errors.push(`${rel}: proof obligation missing id`);
    else if (proofIds.has(proof.id)) errors.push(`${rel}: duplicate proof id "${proof.id}"`);
    else proofIds.add(proof.id);

    const refsByKind = {
      promise: array(proof?.promise_refs),
      operation: array(proof?.operation_refs),
      workflow: proof?.workflow_ref ? [proof.workflow_ref] : [],
      invariant: array(proof?.invariant_refs),
      dependency: array(proof?.dependency_refs),
      surface: array(proof?.surface_refs),
    };
    for (const [kind, refs] of Object.entries(refsByKind)) {
      if (['promise', 'operation', 'workflow', 'surface'].includes(kind) && !refs.length) errors.push(`${rel}: ${label} requires ${kind} refs`);
      for (const ref of refs) {
        validateRef(ref, indexes, rel, label, errors);
        const parsed = refParts(ref);
        if (parsed?.kind === kind) covered[kind].add(parsed.id);
        else if (parsed) errors.push(`${rel}: ${label} expected ${kind} ref, received ${ref}`);
      }
    }

    for (const key of ['given', 'then']) if (!array(proof?.[key]).length) errors.push(`${rel}: ${label} requires ${key}[]`);
    for (const key of ['action', 'authoritative_state', 'visible_outcome', 'recovery']) {
      if (!String(proof?.[key] || '').trim()) errors.push(`${rel}: ${label} requires ${key}`);
    }

    const evidenceLevels = array(proof?.evidence_levels);
    if (!evidenceLevels.includes('boundary') || !evidenceLevels.includes('journey')) {
      errors.push(`${rel}: ${label} must require both boundary and journey evidence`);
    }
    for (const level of evidenceLevels) if (!PROOF_EVIDENCE_LEVELS.has(level)) errors.push(`${rel}: ${label} has invalid evidence level "${level}"`);
    for (const requirement of array(proof?.test_requirements)) {
      if (!PROOF_TEST_REQUIREMENTS.has(requirement)) errors.push(`${rel}: ${label} has invalid test requirement "${requirement}"`);
      else allRequirements.add(requirement);
    }

    const workflowId = refParts(proof?.workflow_ref)?.id;
    const workflow = array(run.workflows).find((item) => item.id === workflowId);
    const workflowOperations = new Set(array(workflow?.steps).map((step) => step.operation_ref));
    for (const ref of refsByKind.operation) {
      if (workflow && !workflowOperations.has(ref)) errors.push(`${rel}: ${label} operation ${ref} is not a step in ${proof.workflow_ref}`);
    }
  }

  for (const requirement of ['restart_or_reload', 'responsive', 'accessibility']) {
    if (required && !allRequirements.has(requirement)) errors.push(`${rel}: proof packet must include ${requirement} evidence`);
  }

  if (required) {
    const criticalCollections = {
      promise: array(run.intent?.critical_promises),
      operation: array(run.operations).filter((item) => item.criticality === 'critical'),
      workflow: array(run.workflows).filter((item) => item.criticality === 'critical'),
      invariant: array(run.invariants).filter((item) => item.criticality === 'critical'),
      dependency: array(run.dependencies).filter((item) => item.criticality === 'critical'),
      surface: array(run.surfaces).filter((item) => item.criticality === 'critical'),
    };
    for (const [kind, items] of Object.entries(criticalCollections)) {
      for (const item of items) if (!covered[kind].has(item.id)) errors.push(`${rel}: critical ${kind}.${item.id} lacks executable proof coverage`);
    }
  }
}

export function parseRunJson(source, rel = 'run.json') {
  try {
    const parsed = JSON.parse(source);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('root must be an object');
    }
    return parsed;
  } catch (error) {
    throw new Error(`${rel}: invalid JSON: ${error.message}`);
  }
}

export function validateRunFields(run, rel = 'run.json', { requireProofPacket = false } = {}) {
  const errors = [];
  const status = String(run.status || '');
  const stage = String(run.stage || '');
  const ready = ['ready_to_build', 'verifying', 'complete'].includes(status);

  if (run.contract_version !== CONTRACT_VERSION) {
    errors.push(`${rel}: contract_version must be "${CONTRACT_VERSION}"`);
  }
  if (!run.id) errors.push(`${rel}: missing id`);
  if (!RUN_STATUSES.has(status)) errors.push(`${rel}: invalid or missing status "${status}"`);
  if (!PRODUCT_STAGES.has(stage)) errors.push(`${rel}: invalid or missing stage "${stage}"`);
  if (!['design', 'verify', 'audit'].includes(run.hook)) errors.push(`${rel}: invalid or missing hook`);

  const intent = object(run.intent);
  if (!intent.problem) errors.push(`${rel}: intent.problem is required`);
  if (!intent.outcome) errors.push(`${rel}: intent.outcome is required`);
  if (!array(intent.users).length) errors.push(`${rel}: intent.users[] is required`);
  validateUniqueIds(intent.critical_promises, 'promise', rel, errors);
  for (const promise of array(intent.critical_promises)) validateNodeMetadata(promise, 'promise', rel, errors, { require: ready });

  const collections = Object.entries(KIND_BY_COLLECTION).map(([key, kind]) => [key, kind, run[key]]);
  for (const [, kind, items] of collections) {
    validateUniqueIds(items, kind, rel, errors);
    for (const item of array(items)) validateNodeMetadata(item, kind, rel, errors, { require: ready });
  }

  for (const decision of [...array(run.decisions?.assumptions), ...array(run.decisions?.forks)]) {
    if (!decision?.id) errors.push(`${rel}: decision missing id`);
    if (!DECISION_CLASSES.has(decision?.class)) {
      errors.push(`${rel}: decision "${decision?.id || '?'}" has invalid class "${decision?.class || ''}"`);
    }
    if (!SOURCES.has(decision?.source)) errors.push(`${rel}: decision "${decision?.id || '?'}" missing valid source`);
    if (!CONFIDENCES.has(decision?.confidence)) errors.push(`${rel}: decision "${decision?.id || '?'}" missing valid confidence`);
  }
  for (const fork of array(run.decisions?.forks)) {
    if (ready && fork?.blocking && fork?.status !== 'resolved') {
      errors.push(`${rel}: blocking decision fork "${fork.id || '?'}" is unresolved`);
    }
  }

  const indexes = nodeIndex(run);
  validateProofPacket(run, rel, errors, indexes, { required: ready && requireProofPacket });
  for (const actor of array(run.actors)) {
    if (ready && actor.criticality === 'critical' && !actor.goal) errors.push(`${rel}: critical actor "${actor.id}" requires goal`);
    if (ready && actor.criticality === 'critical' && !actor.authority) errors.push(`${rel}: critical actor "${actor.id}" requires authority`);
    if (ready && actor.criticality === 'critical' && !actor.entry_path) errors.push(`${rel}: critical actor "${actor.id}" requires entry_path`);
  }
  for (const entity of array(run.entities)) {
    const states = new Set(array(entity.states));
    for (const relationship of array(entity.relationships)) {
      validateRef(relationship.to, indexes, rel, `entity "${entity.id}" relationship`, errors);
      if (!relationship.cardinality) errors.push(`${rel}: entity "${entity.id}" relationship missing cardinality`);
      if (!relationship.lifecycle) errors.push(`${rel}: entity "${entity.id}" relationship missing lifecycle`);
    }
    if (ready && entity.criticality === 'critical' && !states.size) {
      errors.push(`${rel}: critical entity "${entity.id}" requires states[]`);
    }
    if (ready && entity.criticality === 'critical' && !entity.identity) {
      errors.push(`${rel}: critical entity "${entity.id}" requires identity`);
    }
    if (ready && entity.criticality === 'critical' && !array(entity.attributes).length) {
      errors.push(`${rel}: critical entity "${entity.id}" requires attributes[]`);
    }
    if (ready && entity.criticality === 'critical' && !array(entity.lifecycle_consequences).length) {
      errors.push(`${rel}: critical entity "${entity.id}" requires lifecycle_consequences[]`);
    }
  }

  for (const operation of array(run.operations)) {
    for (const actor of array(operation.actor_refs)) validateRef(actor, indexes, rel, `operation "${operation.id}"`, errors);
    for (const transition of array(operation.transitions)) {
      validateRef(transition.entity_ref, indexes, rel, `operation "${operation.id}" transition`, errors);
      const entityId = refParts(transition.entity_ref)?.id;
      const entity = array(run.entities).find((item) => item.id === entityId);
      const states = new Set(array(entity?.states));
      if (transition.from && transition.from !== '*' && !states.has(transition.from)) {
        errors.push(`${rel}: operation "${operation.id}" transition has unknown from state "${transition.from}"`);
      }
      if (transition.to && !states.has(transition.to)) {
        errors.push(`${rel}: operation "${operation.id}" transition has unknown to state "${transition.to}"`);
      }
    }
    for (const ref of array(operation.enforces)) validateRef(ref, indexes, rel, `operation "${operation.id}"`, errors);
    if (ready && operation.criticality === 'critical') {
      if (!array(operation.actor_refs).length) errors.push(`${rel}: critical operation "${operation.id}" requires actor_refs[]`);
      if (!operation.outcome) errors.push(`${rel}: critical operation "${operation.id}" requires outcome`);
      if (!array(operation.transitions).length && !array(operation.effects).length) errors.push(`${rel}: critical operation "${operation.id}" requires transitions[] or effects[]`);
      if (!array(operation.preconditions).length) errors.push(`${rel}: critical operation "${operation.id}" requires preconditions[]`);
      if (!array(operation.enforces).length) errors.push(`${rel}: critical operation "${operation.id}" requires enforces[]`);
      if (!array(operation.failures).length) errors.push(`${rel}: critical operation "${operation.id}" requires failures[]`);
      if (!operation.recovery) errors.push(`${rel}: critical operation "${operation.id}" requires recovery`);
    }
  }

  for (const workflow of array(run.workflows)) {
    validateRef(workflow.actor_ref, indexes, rel, `workflow "${workflow.id}"`, errors);
    if (!array(workflow.steps).length) errors.push(`${rel}: workflow "${workflow.id}" requires steps[]`);
    for (const step of array(workflow.steps)) validateRef(step.operation_ref, indexes, rel, `workflow "${workflow.id}" step`, errors);
    for (const ref of array(workflow.dependency_refs)) validateRef(ref, indexes, rel, `workflow "${workflow.id}"`, errors);
    if (ready && workflow.criticality === 'critical' && !array(workflow.terminal_outcomes).length) {
      errors.push(`${rel}: critical workflow "${workflow.id}" requires terminal_outcomes[]`);
    }
  }

  for (const dependency of array(run.dependencies)) {
    if (!['prerequisite', 'data', 'lifecycle', 'reachability'].includes(dependency.type)) {
      errors.push(`${rel}: dependency "${dependency.id}" has invalid type "${dependency.type || ''}"`);
    }
    validateRef(dependency.from, indexes, rel, `dependency "${dependency.id}"`, errors);
    validateRef(dependency.to, indexes, rel, `dependency "${dependency.id}"`, errors);
    if (!dependency.unmet_behavior) errors.push(`${rel}: dependency "${dependency.id}" missing unmet_behavior`);
    if (ready && dependency.criticality === 'critical' && !dependency.condition) errors.push(`${rel}: critical dependency "${dependency.id}" requires condition`);
    if (ready && dependency.criticality === 'critical' && !dependency.fulfillment) errors.push(`${rel}: critical dependency "${dependency.id}" requires fulfillment`);
    if (ready && dependency.criticality === 'critical' && !dependency.verification) errors.push(`${rel}: critical dependency "${dependency.id}" requires verification`);
  }
  validatePrerequisiteCycles(run, rel, errors);

  for (const invariant of array(run.invariants)) {
    if (ready && invariant.criticality === 'critical' && !invariant.rule) errors.push(`${rel}: critical invariant "${invariant.id}" requires rule`);
  }

  for (const surface of array(run.surfaces)) {
    for (const ref of [...array(surface.graph_refs), ...array(surface.workflow_refs), ...array(surface.operation_refs), ...array(surface.primary_actor_refs)]) {
      validateRef(ref, indexes, rel, `surface "${surface.id}"`, errors);
    }
    if (ready && surface.criticality === 'critical') {
      if (!surface.purpose) errors.push(`${rel}: critical surface "${surface.id}" requires purpose`);
      if (!array(surface.primary_actor_refs).length) errors.push(`${rel}: critical surface "${surface.id}" requires primary_actor_refs[]`);
      if (!array(surface.workflow_refs).length) errors.push(`${rel}: critical surface "${surface.id}" requires workflow_refs[]`);
      if (!array(surface.operation_refs).length) errors.push(`${rel}: critical surface "${surface.id}" requires operation_refs[]`);
      if (!array(surface.contract).length) errors.push(`${rel}: critical surface "${surface.id}" requires contract[]`);
    }
  }

  const riskKeys = new Set();
  for (const scenario of array(run.scenarios)) {
    validateRef(scenario.when?.operation_ref, indexes, rel, `scenario "${scenario.id}"`, errors);
    for (const ref of array(scenario.covers)) validateRef(ref, indexes, rel, `scenario "${scenario.id}"`, errors);
    if (!array(scenario.then).length) errors.push(`${rel}: scenario "${scenario.id}" requires then[]`);
    if (!scenario.risk_key) errors.push(`${rel}: scenario "${scenario.id}" missing risk_key`);
    else if (riskKeys.has(scenario.risk_key)) errors.push(`${rel}: duplicate scenario risk_key "${scenario.risk_key}"`);
    else riskKeys.add(scenario.risk_key);
  }

  for (const finding of array(run.persona_findings)) {
    if (!finding.id || !finding.persona_ref || !finding.classification) {
      errors.push(`${rel}: persona finding requires id, persona_ref, and classification`);
    }
    if (finding.source !== 'persona_hypothesis') errors.push(`${rel}: persona finding "${finding.id || '?'}" must use source persona_hypothesis`);
    for (const ref of array(finding.graph_refs)) validateRef(ref, indexes, rel, `persona finding "${finding.id}"`, errors);
  }

  for (const link of array(run.traceability)) {
    if (!link.promise_ref) errors.push(`${rel}: traceability item missing promise_ref`);
    else validateRef(link.promise_ref, indexes, rel, 'traceability item', errors);
    for (const ref of array(link.graph_refs)) validateRef(ref, indexes, rel, `traceability for ${link.promise_ref}`, errors);
  }

  if (ready) {
    if (!array(intent.critical_promises).length) errors.push(`${rel}: ready contract requires intent.critical_promises[]`);
    for (const key of ['actors', 'entities', 'operations', 'workflows', 'invariants', 'surfaces', 'scenarios']) {
      if (!array(run[key]).some((item) => item.criticality === 'critical')) {
        errors.push(`${rel}: ready contract requires at least one critical ${KIND_BY_COLLECTION[key]}`);
      }
    }
    for (const promise of array(intent.critical_promises)) {
      const linked = array(run.traceability).find((item) => item.promise_ref === `promise.${promise.id}`);
      if (!linked || !array(linked.graph_refs).length) errors.push(`${rel}: critical promise "${promise.id}" lacks traceability`);
      else {
        for (const kind of ['actor', 'entity', 'operation', 'workflow', 'invariant', 'surface', 'scenario']) {
          const collection = COLLECTION_BY_KIND[kind];
          const hasCriticalRef = array(linked.graph_refs).some((ref) => {
            const parsed = refParts(ref);
            return parsed?.kind === kind && array(run[collection]).some((item) => item.id === parsed.id && item.criticality === 'critical');
          });
          if (!hasCriticalRef) errors.push(`${rel}: critical promise "${promise.id}" lacks a critical ${kind} trace`);
        }
      }
    }
    const covered = new Set(array(run.scenarios).flatMap((scenario) => array(scenario.covers)));
    for (const key of ['operations', 'workflows', 'invariants', 'dependencies']) {
      for (const item of array(run[key]).filter((node) => node.criticality === 'critical')) {
        const ref = `${KIND_BY_COLLECTION[key]}.${item.id}`;
        if (!covered.has(ref)) errors.push(`${rel}: critical ${ref} lacks scenario coverage`);
      }
    }
    for (const deferred of collections.flatMap(([, , items]) => array(items)).filter((item) => item.criticality === 'deferred')) {
      const refSuffix = `.${deferred.id}`;
      if (array(run.traceability).some((item) => array(item.graph_refs).some((ref) => ref.endsWith(refSuffix)))) {
        errors.push(`${rel}: deferred node "${deferred.id}" cannot satisfy ready traceability`);
      }
    }
  }

  if (['verify', 'audit'].includes(run.hook) || status === 'complete') {
    for (const finding of array(run.findings)) {
      if (!finding.id || !FINDING_FIX_TARGETS.has(finding.fix_target)) {
        errors.push(`${rel}: verification finding requires id and fix_target`);
      }
      if (finding.fix_target !== 'ops' && (!finding.evidence || !array(finding.acceptance).length)) {
        errors.push(`${rel}: finding "${finding.id || '?'}" requires evidence and acceptance[]`);
      }
    }
  }
  return errors;
}

export function loadRunJson(runPath) {
  const file = path.resolve(runPath);
  if (!fs.existsSync(file)) throw new Error(`Not found: ${file}`);
  return parseRunJson(fs.readFileSync(file, 'utf8'), path.basename(file));
}

export function validateWalkthroughPack(runDir, indexRel, rel = 'run.json') {
  const errors = [];
  const indexPath = path.resolve(runDir, indexRel);
  if (!indexPath.startsWith(path.resolve(runDir) + path.sep)) return [`${rel}: walkthrough index resolves outside run directory`];
  if (!fs.existsSync(indexPath)) return [`${rel}: walkthrough index not found: ${indexRel}`];
  const content = fs.readFileSync(indexPath, 'utf8');
  if (!/^mode:\s*live_app\s*$/m.test(content)) errors.push(`${rel}: walkthrough mode must be live_app`);
  if (!/^source:\s*product\s*$/m.test(content)) errors.push(`${rel}: walkthrough source must be product`);
  const walkDir = path.dirname(indexPath);
  for (const screenshot of [...content.matchAll(/^\s+screenshot:\s*(\S+)/gm)].map((match) => match[1])) {
    const screenshotPath = path.resolve(walkDir, screenshot);
    if (!screenshotPath.startsWith(path.resolve(runDir) + path.sep)) errors.push(`${rel}: walkthrough screenshot resolves outside run directory: ${screenshot}`);
    else if (!fs.existsSync(screenshotPath)) errors.push(`${rel}: walkthrough screenshot not found: ${screenshot}`);
  }
  return errors;
}

export function validateRunJson(runPath, { requireProofPacket = true } = {}) {
  try {
    const run = loadRunJson(runPath);
    const rel = path.basename(runPath);
    const errors = validateRunFields(run, rel, { requireProofPacket });
    const runDir = path.dirname(path.resolve(runPath));
    for (const evidence of array(run.evidence)) {
      if (evidence.kind === 'visual_walkthrough' && evidence.path) {
        errors.push(...validateWalkthroughPack(runDir, evidence.path, rel));
      }
    }
    return { ok: errors.length === 0, errors, run };
  } catch (error) {
    return { ok: false, errors: [error.message], run: {} };
  }
}

export function resolveRunPath(laminaRoot, runId) {
  return path.join(path.resolve(laminaRoot), 'runs', runId, 'run.json');
}

export function loadScenariosFromRun(laminaRoot, runId) {
  return array(loadRunJson(resolveRunPath(laminaRoot, runId)).scenarios);
}
