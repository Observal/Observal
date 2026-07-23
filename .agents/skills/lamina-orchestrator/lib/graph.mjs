import fs from 'node:fs';
import path from 'node:path';
import { CONTRACT_VERSION, PROOF_BUDGET_LIMITS, loadRunJson, validateRunFields } from './run.mjs';

const list = (value) => (Array.isArray(value) ? value : []);
const active = (items) => list(items).filter((item) => item.criticality !== 'deferred');
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

export function createRun({ id, target, problem, outcome, users = [], stage = 'spark', hook = 'design' }) {
  return {
    contract_version: CONTRACT_VERSION,
    id,
    status: 'draft',
    stage,
    hook,
    target,
    intent: {
      problem,
      outcome,
      users,
      critical_promises: [],
      success_signals: [],
      constraints: [],
      scope: { in: [], out: [] },
    },
    decisions: { assumptions: [], forks: [] },
    actors: [],
    entities: [],
    operations: [],
    workflows: [],
    invariants: [],
    dependencies: [],
    surfaces: [],
    scenarios: [],
    proof_budget: {
      strategy: 'smallest_complete_slice',
      max_critical_promises: PROOF_BUDGET_LIMITS.critical_promises,
      max_active_operations: PROOF_BUDGET_LIMITS.active_operations,
      max_active_workflows: PROOF_BUDGET_LIMITS.active_workflows,
      max_active_dependencies: PROOF_BUDGET_LIMITS.active_dependencies,
      max_active_surfaces: PROOF_BUDGET_LIMITS.active_surfaces,
      max_proofs: PROOF_BUDGET_LIMITS.proofs,
      rationale: 'Keep only behavior that can be implemented and proved as one coherent current slice.',
    },
    proofs: [],
    persona_findings: [],
    traceability: [],
    findings: [],
    evidence: [],
  };
}

function slug(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 56) || 'risk';
}

function scenarioMeta(reason) {
  return {
    criticality: 'supporting',
    source: 'derived',
    confidence: 'high',
    relevance_reason: reason,
  };
}

export function deriveScenarioSuggestions(run) {
  const existing = new Set(list(run.scenarios).map((item) => item.risk_key).filter(Boolean));
  const suggestions = [];
  const add = (scenario) => {
    if (!existing.has(scenario.risk_key)) {
      existing.add(scenario.risk_key);
      suggestions.push(scenario);
    }
  };

  for (const operation of active(run.operations)) {
    for (const failure of list(operation.failures)) {
      const key = `failure:${operation.id}:${slug(failure.code || failure.outcome || failure)}`;
      add({
        id: slug(key),
        ...scenarioMeta(`Distinct failure outcome for operation.${operation.id}`),
        kind: 'failure',
        risk_key: key,
        given: list(failure.given),
        when: { operation_ref: `operation.${operation.id}` },
        then: list(failure.then).length ? failure.then : [String(failure.outcome || failure)],
        covers: [`operation.${operation.id}`],
      });
    }
    if (operation.destructive === true) {
      const key = `recovery:${operation.id}:destructive`;
      add({
        id: slug(key),
        ...scenarioMeta(`Destructive operation.${operation.id} requires confirmation and recovery`),
        criticality: operation.criticality,
        kind: 'recovery',
        risk_key: key,
        given: ['The destructive action is available'],
        when: { operation_ref: `operation.${operation.id}` },
        then: ['The consequence is explicit', 'Cancellation is safe', 'Recovery or irreversibility is explained'],
        covers: [`operation.${operation.id}`],
      });
    }
  }

  for (const dependency of active(run.dependencies)) {
    const key = `dependency:${dependency.id}:unmet`;
    add({
      id: slug(key),
      ...scenarioMeta(`Unmet behavior for dependency.${dependency.id}`),
      criticality: dependency.criticality,
      kind: 'boundary',
      risk_key: key,
      given: [`dependency.${dependency.id} is unmet`],
      when: { operation_ref: dependency.operation_ref || firstOperationRef(run, dependency.from) },
      then: [dependency.unmet_behavior],
      covers: [`dependency.${dependency.id}`, dependency.from, dependency.to].filter(Boolean),
    });
  }

  return suggestions.filter((scenario) => scenario.when.operation_ref);
}

function firstOperationRef(run, fromRef) {
  if (String(fromRef || '').startsWith('operation.')) return fromRef;
  if (String(fromRef || '').startsWith('workflow.')) {
    const id = fromRef.slice('workflow.'.length);
    const workflow = list(run.workflows).find((item) => item.id === id);
    return workflow?.steps?.[0]?.operation_ref;
  }
  return undefined;
}

function section(title, rows) {
  return rows.length ? `\n## ${title}\n\n${rows.join('\n')}\n` : '';
}

function nodeLine(item, detail = '') {
  return `- **${item.id}** [${item.criticality}]${detail ? ` — ${detail}` : ''}`;
}

function text(value, fallback = 'not specified') {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return fallback;
}

function bullets(values, fallback = '- Not specified') {
  const rows = list(values).map((value) => `- ${typeof value === 'string' ? value : JSON.stringify(value)}`);
  return rows.length ? rows.join('\n') : fallback;
}

function actorImplementation(item) {
  return [
    `### actor.${item.id}`,
    '',
    `- **Goal:** ${text(item.goal || item.relevance_reason)}`,
    `- **Authority and identity proof:** ${text(item.authority)}`,
    `- **Reachable entry or activation path:** ${text(item.entry_path)}`,
    `- **Owns:** ${list(item.owns).join(', ') || 'nothing declared'}`,
    `- **Permissions:** ${list(item.permissions).join('; ') || 'none declared'}`,
  ].join('\n');
}

function entityImplementation(item) {
  const relationships = list(item.relationships).map((relationship) =>
    `${relationship.to} (${text(relationship.cardinality)}); lifecycle: ${text(relationship.lifecycle)}`);
  return [
    `### entity.${item.id}`,
    '',
    `- **Identity:** ${text(item.identity)}`,
    '- **Key field contracts:**',
    bullets(list(item.attributes).map((attribute) => `${text(attribute.name)}: ${text(attribute.contract)}`)),
    `- **States:** ${list(item.states).join(' → ') || 'none declared'}`,
    `- **Relationships:** ${relationships.join('; ') || 'none declared'}`,
    '- **Lifecycle consequences:**',
    bullets(item.lifecycle_consequences),
  ].join('\n');
}

function transitionLine(transition) {
  return `${transition.entity_ref}: ${text(transition.from, '*')} → ${text(transition.to)}`;
}

function failureLine(failure) {
  if (typeof failure === 'string') return failure;
  const given = list(failure?.given).join('; ');
  const then = list(failure?.then).join('; ');
  return `**${text(failure?.code, 'failure')}**${given ? ` — given ${given}` : ''}: ${text(failure?.outcome)}${then ? `; recovery outcome: ${then}` : ''}`;
}

function operationImplementation(item) {
  return [
    `### operation.${item.id}`,
    '',
    `- **Actors:** ${list(item.actor_refs).join(', ') || 'none declared'}`,
    '- **Preconditions:**',
    bullets(item.preconditions),
    '- **Trusted enforcement:**',
    bullets(item.enforces),
    '- **State transitions:**',
    bullets(list(item.transitions).map(transitionLine)),
    '- **Durable effects and projections:**',
    bullets(item.effects),
    '- **Failures:**',
    bullets(list(item.failures).map(failureLine)),
    `- **Recovery:** ${text(item.recovery)}`,
    `- **Visible outcome:** ${text(item.outcome || item.relevance_reason)}`,
  ].join('\n');
}

function workflowImplementation(item) {
  const steps = list(item.steps).map((step, index) => `${index + 1}. ${step.operation_ref}${step.outcome ? ` — ${step.outcome}` : ''}`);
  return [
    `### workflow.${item.id}`,
    '',
    `- **Responsible actor:** ${text(item.actor_ref)}`,
    `- **Dependencies:** ${list(item.dependency_refs).join(', ') || 'none declared'}`,
    '- **Reachable sequence:**',
    steps.length ? steps.join('\n') : '- Not specified',
    `- **Terminal outcomes:** ${list(item.terminal_outcomes).join('; ') || 'none declared'}`,
  ].join('\n');
}

function dependencyImplementation(item) {
  return [
    `### dependency.${item.id}`,
    '',
    `- **Type:** ${text(item.type)}`,
    `- **Required edge:** ${text(item.from)} requires ${text(item.to)}`,
    `- **Condition:** ${text(item.condition)}`,
    `- **Concrete fulfillment:** ${text(item.fulfillment)}`,
    `- **Unmet behavior:** ${text(item.unmet_behavior)}`,
    `- **Verification:** ${text(item.verification)}`,
  ].join('\n');
}

function surfaceImplementation(item) {
  return [
    `### surface.${item.id}`,
    '',
    `- **Purpose:** ${text(item.purpose || item.relevance_reason)}`,
    `- **Primary actors:** ${list(item.primary_actor_refs).join(', ') || 'none declared'}`,
    `- **Workflows:** ${list(item.workflow_refs).join(', ') || 'none declared'}`,
    `- **Operations:** ${list(item.operation_refs).join(', ') || 'none declared'}`,
    '- **Interaction and recovery contract:**',
    bullets(item.contract),
  ].join('\n');
}

function proofImplementation(item) {
  return [
    `### proof.${item.id}`,
    '',
    `- **Promises:** ${list(item.promise_refs).join(', ')}`,
    `- **Workflow:** ${text(item.workflow_ref)}`,
    `- **Operations:** ${list(item.operation_refs).join(', ')}`,
    `- **Rules and dependencies:** ${[...list(item.invariant_refs), ...list(item.dependency_refs)].join(', ') || 'none declared'}`,
    `- **Surfaces:** ${list(item.surface_refs).join(', ')}`,
    '- **Given:**',
    bullets(item.given),
    `- **Action:** ${text(item.action)}`,
    '- **Observable assertions:**',
    bullets(item.then),
    `- **Authoritative state:** ${text(item.authoritative_state)}`,
    `- **Visible outcome:** ${text(item.visible_outcome)}`,
    `- **Recovery:** ${text(item.recovery)}`,
    `- **Evidence levels:** ${list(item.evidence_levels).join(', ')}`,
    `- **Test requirements:** ${list(item.test_requirements).join(', ') || 'none beyond the proof'}`,
  ].join('\n');
}

export function renderRunMarkdown(run) {
  const intent = run.intent || {};
  let output = `# ${run.target || run.id}\n\n`;
  output += `Stage: **${run.stage}** · Status: **${run.status}** · Contract: **${run.contract_version}**\n\n`;
  output += `## Intent\n\n${intent.problem || ''}\n\n**Outcome:** ${intent.outcome || ''}\n`;
  output += section('Critical promises', list(intent.critical_promises).map((item) => nodeLine(item, item.promise)));
  output += section('Actors', active(run.actors).map((item) => nodeLine(item, item.goal || item.relevance_reason)));
  output += section('Entities and lifecycles', active(run.entities).map((item) => nodeLine(item, `${list(item.states).join(' → ') || 'no lifecycle states'}`)));
  output += section('Operations', active(run.operations).map((item) => nodeLine(item, item.outcome || item.relevance_reason)));
  output += section('Workflows', active(run.workflows).map((item) => nodeLine(item, `${list(item.steps).map((step) => step.operation_ref).join(' → ')}`)));
  output += section('Rules and invariants', active(run.invariants).map((item) => nodeLine(item, item.rule)));
  output += section('Dependencies', active(run.dependencies).map((item) => nodeLine(item, `${item.from} requires ${item.to}; unmet: ${item.unmet_behavior}`)));
  output += section('Scenarios', active(run.scenarios).map((item) => nodeLine(item, `${item.kind}: ${list(item.then).join('; ')}`)));
  output += section('Executable proofs', list(run.proofs).map((item) => nodeLine(item, `${item.workflow_ref}: ${item.visible_outcome}`)));
  output += section('Decision forks', list(run.decisions?.forks).map((item) => `- **${item.id}** [${item.status || 'unresolved'}] — ${item.question || item.statement}`));
  output += section('Persona findings', list(run.persona_findings).map((item) => `- **${item.id}** [${item.classification}] — ${item.finding}`));
  return `${output.trim()}\n`;
}

export function renderImplementMarkdown(run) {
  const errors = validateRunFields(run, 'run.json', { requireProofPacket: true });
  if (errors.length) throw new Error(`Cannot render implementation contract:\n${errors.join('\n')}`);
  const intent = run.intent || {};
  let output = `# Implement: ${run.target || run.id}\n\nSource: \`run.json\` contract ${run.contract_version}\n\n`;
  output += `Stage: **${run.stage}**. Implement only the active graph, but satisfy every active critical promise at its declared trust boundary. A demo identity switcher, browser-local storage, or an open-page timer is not a substitute for authenticated authority, durable shared state, or an operational system actor unless the contract explicitly declares that prototype limitation.\n\n`;
  output += `## Product outcome\n\n${intent.outcome}\n`;
  output += `\n## Proof budget\n\nImplement the smallest complete slice. The active graph is capped at ${run.proof_budget.max_active_operations} operations, ${run.proof_budget.max_active_workflows} workflows, ${run.proof_budget.max_active_dependencies} dependencies, ${run.proof_budget.max_active_surfaces} surfaces, and ${run.proof_budget.max_proofs} proof obligations. Do not add current-slice behavior outside this packet. If implementation pressure appears, preserve the critical promises and proof paths and defer unrelated breadth.\n`;
  output += `\n## Build protocol\n\n1. Before broad implementation, turn every proof below into named automated checks containing the exact marker \`[proof:<id>]\`.\n2. Create a method-neutral root \`product-proof-manifest.json\` with version \`1.0\`. Use either \`{"version":"1.0","proofs":[{"proof_id":"<id>","test_files":[],"evidence_levels":[],"test_requirements":[]}]}\` or an equivalent id-keyed \`proofs\` object; map every proof to its test files, evidence levels, and test requirements.\n3. Implement only enough product behavior to make the proof paths complete at their trusted boundaries, including visible loading, empty, denial, error, success, and recovery feedback where applicable.\n4. Give every test a finite per-test timeout and release every test-owned server, worker, database, browser, context, listener, timer, and temporary resource from a \`finally\` block, including when setup or assertions fail.\n5. Run the complete repository check/build/test suite at least three times. A timeout, delayed exit from open handles, skip, or nonzero exit is a proof failure; no critical proof may remain represented only by prose, types, comments, or seed data.\n6. Before handoff, confirm every manifest test file exists, contains its proof marker, and is exercised by the declared test suite.\n`;
  output += section('Must preserve', list(intent.critical_promises).map((item) => `- [ ] **promise.${item.id}** — ${item.promise}`));
  output += section('Executable proof obligations', list(run.proofs).map(proofImplementation));
  output += section('Actors and trusted authority', active(run.actors).map(actorImplementation));
  output += section('Domain identity and lifecycle', active(run.entities).map(entityImplementation));
  output += section('Operations: enforcement to visible recovery', active(run.operations).map(operationImplementation));
  output += section('End-to-end workflows', active(run.workflows).map(workflowImplementation));
  output += section('Rules', active(run.invariants).map((item) => `- [ ] **invariant.${item.id}** — ${item.rule}`));
  output += section('Dependencies and degraded behavior', active(run.dependencies).map(dependencyImplementation));
  output += section('Surfaces and journey continuity', active(run.surfaces).map(surfaceImplementation));
  output += section('Risk scenarios', active(run.scenarios).map((item) => `- [ ] **scenario.${item.id}** — Given ${list(item.given).join('; ') || 'the workflow context'}, when ${item.when?.operation_ref}, then ${list(item.then).join('; ')}`));
  output += section('Promise trace and proof checklist', list(run.traceability).map((item) => `- [ ] **${item.promise_ref}** — prove ${list(item.graph_refs).join(' → ')}`));
  output += section('Resolved assumptions and policy forks', [...list(run.decisions?.assumptions), ...list(run.decisions?.forks)].map((item) => `- **decision.${item.id}** [${item.status || 'proposed'}; ${item.class}] — ${item.statement || item.question}`));
  output += section('In scope', list(intent.scope?.in).map((item) => `- ${item}`));
  output += section('Out of scope', list(intent.scope?.out).map((item) => `- ${item}`));
  output += `\n## Required implementation proof\n\nBefore handoff, trace every checked operation through reachable action → trusted enforcement → state mutation → durable commit → actor-scoped projection → visible outcome or recovery. Tests must synchronize on the authoritative post-action state rather than stale pre-action content. Use controlled clocks for time boundaries, separate authenticated contexts for multi-actor promises, and both API-boundary and UI evidence for privacy or revocation. Every test needs a finite timeout and failure-safe finally-block cleanup of all owned resources. Run the repository's build, complete test suite three times, responsive checks, and relevant accessibility checks; every run must exit cleanly with no skips or open handles.\n`;
  return `${output.trim()}\n`;
}

export function coverageReport(run) {
  const promises = list(run.intent?.critical_promises);
  const traced = new Set(list(run.traceability).filter((item) => list(item.graph_refs).length).map((item) => item.promise_ref));
  const critical = [...active(run.operations), ...active(run.workflows), ...active(run.invariants)].filter((item) => item.criticality === 'critical');
  const scenarioRefs = new Set(list(run.scenarios).flatMap((item) => list(item.covers)));
  const proofPromiseRefs = new Set(list(run.proofs).flatMap((item) => list(item.promise_refs)));
  const proofWorkflowRefs = new Set(list(run.proofs).map((item) => item.workflow_ref));
  const proofOperationRefs = new Set(list(run.proofs).flatMap((item) => list(item.operation_refs)));
  return {
    promises: { total: promises.length, traced: promises.filter((item) => traced.has(`promise.${item.id}`)).length },
    critical_nodes: { total: critical.length, scenario_covered: critical.filter((item) => scenarioRefs.has(`${kindFor(run, item)}.${item.id}`)).length },
    proofs: {
      total: list(run.proofs).length,
      promises_covered: promises.filter((item) => proofPromiseRefs.has(`promise.${item.id}`)).length,
      workflows_covered: active(run.workflows).filter((item) => item.criticality === 'critical' && proofWorkflowRefs.has(`workflow.${item.id}`)).length,
      operations_covered: active(run.operations).filter((item) => item.criticality === 'critical' && proofOperationRefs.has(`operation.${item.id}`)).length,
    },
    unresolved_blocking_forks: list(run.decisions?.forks).filter((item) => item.blocking && item.status !== 'resolved').map((item) => item.id),
    deferred_nodes: Object.entries(KIND_BY_COLLECTION).flatMap(([key, kind]) => list(run[key]).filter((item) => item.criticality === 'deferred').map((item) => `${kind}.${item.id}`)),
  };
}

function kindFor(run, item) {
  for (const key of ['operations', 'workflows', 'invariants']) if (list(run[key]).includes(item)) return key.slice(0, -1);
  return 'node';
}

export function scopeRun(run, refs) {
  const selected = new Set(refs);
  const add = (ref) => {
    if (!ref || selected.has(ref)) return false;
    selected.add(ref);
    return true;
  };
  let changed = true;
  while (changed) {
    changed = false;
    for (const actor of list(run.actors)) {
      const actorRef = `actor.${actor.id}`;
      if (!selected.has(actorRef)) continue;
      for (const operation of list(run.operations)) if (list(operation.actor_refs).includes(actorRef)) changed = add(`operation.${operation.id}`) || changed;
      for (const workflow of list(run.workflows)) if (workflow.actor_ref === actorRef) changed = add(`workflow.${workflow.id}`) || changed;
      for (const surface of list(run.surfaces)) if (list(surface.primary_actor_refs).includes(actorRef)) changed = add(`surface.${surface.id}`) || changed;
    }
    for (const dependency of list(run.dependencies)) {
      const dependencyRef = `dependency.${dependency.id}`;
      if (selected.has(dependencyRef)) {
        changed = add(dependency.from) || add(dependency.to) || changed;
      } else if (selected.has(dependency.from)) {
        changed = add(dependency.to) || add(dependencyRef) || changed;
      }
    }
    for (const workflow of list(run.workflows)) {
      if (selected.has(`workflow.${workflow.id}`)) {
        changed = add(workflow.actor_ref) || changed;
        for (const step of list(workflow.steps)) changed = add(step.operation_ref) || changed;
        for (const ref of list(workflow.dependency_refs)) changed = add(ref) || changed;
      }
    }
    for (const operation of list(run.operations)) {
      if (!selected.has(`operation.${operation.id}`)) continue;
      for (const ref of list(operation.actor_refs)) changed = add(ref) || changed;
      for (const transition of list(operation.transitions)) changed = add(transition.entity_ref) || changed;
      for (const ref of list(operation.enforces)) changed = add(ref) || changed;
    }
    for (const entity of list(run.entities)) {
      if (!selected.has(`entity.${entity.id}`)) continue;
      for (const relationship of list(entity.relationships)) changed = add(relationship.to) || changed;
    }
    for (const scenario of list(run.scenarios)) {
      const scenarioRef = `scenario.${scenario.id}`;
      const relevant = selected.has(scenarioRef)
        || selected.has(scenario.when?.operation_ref)
        || list(scenario.covers).some((ref) => selected.has(ref));
      if (!relevant) continue;
      changed = add(scenarioRef) || add(scenario.when?.operation_ref) || changed;
      for (const ref of list(scenario.covers)) changed = add(ref) || changed;
    }
    for (const surface of list(run.surfaces)) {
      if (!selected.has(`surface.${surface.id}`)) continue;
      for (const ref of [...list(surface.graph_refs), ...list(surface.workflow_refs), ...list(surface.operation_refs)]) changed = add(ref) || changed;
    }
    for (const trace of list(run.traceability)) {
      if (selected.has(trace.promise_ref)) for (const ref of list(trace.graph_refs)) changed = add(ref) || changed;
    }
    for (const proof of list(run.proofs)) {
      const refs = [...list(proof.promise_refs), proof.workflow_ref, ...list(proof.operation_refs), ...list(proof.invariant_refs), ...list(proof.dependency_refs), ...list(proof.surface_refs)].filter(Boolean);
      if (!refs.some((ref) => selected.has(ref))) continue;
      for (const ref of refs) changed = add(ref) || changed;
    }
  }
  const scoped = structuredClone(run);
  for (const [key, kind] of Object.entries(KIND_BY_COLLECTION)) {
    scoped[key] = list(run[key]).filter((item) => selected.has(`${kind}.${item.id}`));
  }
  scoped.traceability = list(run.traceability)
    .filter((item) => selected.has(item.promise_ref) || list(item.graph_refs).some((ref) => selected.has(ref)))
    .map((item) => ({ ...item, graph_refs: list(item.graph_refs).filter((ref) => selected.has(ref)) }));
  scoped.proofs = list(run.proofs).filter((proof) => [proof.workflow_ref, ...list(proof.operation_refs), ...list(proof.surface_refs)].some((ref) => selected.has(ref)));
  return scoped;
}

function personaRef(persona) {
  return `persona.${persona.id}`;
}

export function actorRefsForPersona(run, persona) {
  const explicit = list(persona.actor_refs);
  if (explicit.length) return explicit;
  const fromActors = list(run.actors)
    .filter((actor) =>
      list(actor.persona_refs).some((ref) => ref === personaRef(persona) || ref.endsWith(`.${persona.id}`)),
    )
    .map((actor) => `actor.${actor.id}`);
  if (fromActors.length) return fromActors;
  const critical = list(run.actors).filter((actor) => actor.criticality === 'critical');
  if (critical.length) return [`actor.${critical[0].id}`];
  return list(run.actors)
    .slice(0, 1)
    .map((actor) => `actor.${actor.id}`);
}

export function selectPanelPersonas(personasDoc, run, max = 3) {
  const personas = list(personasDoc?.personas);
  if (!personas.length) return [];
  const selected = [];
  const used = new Set();

  const primary = personas.find((item) => item.primary === true);
  if (primary) {
    selected.push(primary);
    used.add(primary.id);
  }

  const criticalActorRefs = new Set(
    list(run.actors)
      .filter((actor) => actor.criticality === 'critical')
      .map((actor) => `actor.${actor.id}`),
  );
  for (const persona of personas) {
    if (selected.length >= max) break;
    if (used.has(persona.id)) continue;
    if (actorRefsForPersona(run, persona).some((ref) => criticalActorRefs.has(ref))) {
      selected.push(persona);
      used.add(persona.id);
    }
  }

  for (const persona of personas) {
    if (selected.length >= max) break;
    if (used.has(persona.id)) continue;
    const roleKey = String(persona.role || '').toLowerCase();
    if (!selected.some((item) => String(item.role || '').toLowerCase() === roleKey)) {
      selected.push(persona);
      used.add(persona.id);
    }
  }

  for (const persona of personas) {
    if (selected.length >= max) break;
    if (!used.has(persona.id)) {
      selected.push(persona);
      used.add(persona.id);
    }
  }

  return selected.slice(0, max);
}

export function buildPersonaPack(run, persona) {
  const actorRefs = actorRefsForPersona(run, persona);
  const seedRefs = new Set(actorRefs);
  for (const workflow of list(run.workflows)) {
    if (actorRefs.includes(workflow.actor_ref)) seedRefs.add(`workflow.${workflow.id}`);
  }
  for (const promise of list(run.intent?.critical_promises)) {
    if (promise.criticality !== 'deferred') seedRefs.add(`promise.${promise.id}`);
  }

  const graph_slice = scopeRun(run, [...seedRefs]);
  return {
    persona_ref: personaRef(persona),
    persona: {
      id: persona.id,
      role: persona.role,
      goals: list(persona.goals),
      constraints: list(persona.constraints),
      evidence: list(persona.evidence),
      confidence: persona.confidence,
      actor_refs: actorRefs,
    },
    critical_promises: list(run.intent?.critical_promises).filter((promise) => promise.criticality !== 'deferred'),
    graph_slice,
    output_contract: 'prompts/subagents/persona-panel-spawn.md',
  };
}

export function buildPersonaPacks(run, personasDoc, max = 3) {
  return selectPanelPersonas(personasDoc, run, max).map((persona) => buildPersonaPack(run, persona));
}

export function preflightRun(run, { includeDerive = true } = {}) {
  const coverage = coverageReport(run);
  const derive_suggestions = includeDerive ? deriveScenarioSuggestions(run) : [];
  const validation_errors = validateRunFields(run, 'run.json', { requireProofPacket: false });
  return {
    coverage,
    derive_suggestions,
    validation_ok: validation_errors.length === 0,
    validation_errors,
    unresolved_blocking_forks: coverage.unresolved_blocking_forks,
  };
}

export function finalizeReadyRun(runPath) {
  const abs = path.resolve(runPath);
  const run = loadRunJson(abs);
  let errors = validateRunFields(run, abs, { requireProofPacket: false });
  if (errors.length) return { ok: false, phase: 'draft', errors };

  run.status = 'ready_to_build';
  fs.writeFileSync(abs, `${JSON.stringify(run, null, 2)}\n`);

  errors = validateRunFields(run, abs, { requireProofPacket: true });
  if (errors.length) {
    run.status = 'draft';
    fs.writeFileSync(abs, `${JSON.stringify(run, null, 2)}\n`);
    return { ok: false, phase: 'ready_to_build', errors };
  }

  const dir = path.dirname(abs);
  fs.writeFileSync(path.join(dir, 'run.md'), renderRunMarkdown(run));
  fs.writeFileSync(path.join(dir, 'implement.md'), renderImplementMarkdown(run));
  return { ok: true, artifacts: ['run.md', 'implement.md'] };
}

export function writeGeneratedArtifacts(runPath) {
  const run = loadRunJson(runPath);
  const dir = path.dirname(path.resolve(runPath));
  fs.writeFileSync(path.join(dir, 'run.md'), renderRunMarkdown(run));
  if (run.status === 'ready_to_build') fs.writeFileSync(path.join(dir, 'implement.md'), renderImplementMarkdown(run));
}
