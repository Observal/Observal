import fs from 'fs';
import os from 'os';
import path from 'path';
import { spawnSync } from 'child_process';
import { fileURLToPath } from 'url';
import { validateRunJson } from '../../lamina-orchestrator/lib/run.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../../..');
const tool = path.resolve(HERE, '../../lamina-orchestrator/lib/graph-tool.mjs');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lamina-ready-'));
const runPath = path.join(dir, 'run.json');
const meta = (crit = 'critical') => ({
  criticality: crit,
  source: 'user',
  confidence: 'high',
  relevance_reason: 'Required for the current design slice',
});

spawnSync('node', [tool, 'create', runPath, 'id=budgeting', 'stage=shape', 'problem=household shared budget tracking', 'outcome=members see shared spend and category limits', 'users=owner'], { encoding: 'utf8' });

const run = {
  ...JSON.parse(fs.readFileSync(runPath, 'utf8')),
  status: 'draft',
  intent: {
    problem: 'household shared budget tracking',
    outcome: 'members see shared spend and category limits',
    users: ['owner'],
    critical_promises: [
      {
        id: 'shared-view',
        promise: 'Household members see the same consolidated balance for linked accounts',
        ...meta(),
      },
    ],
    success_signals: ['Shared balance visible after link'],
    constraints: ['Mobile-first'],
    scope: { in: ['link account', 'view budget'], out: ['tax filing'] },
  },
  decisions: {
    assumptions: [
      { id: 'monthly', class: 'reversible_default', statement: 'Budget periods are monthly', ...meta('supporting') },
    ],
    forks: [],
  },
  actors: [
    { id: 'owner', name: 'Owner', role: 'household owner', goal: 'Keep household budget accurate', authority: 'link accounts and set limits', entry_path: 'mobile app sign-in', ...meta() },
    { id: 'member', name: 'Member', role: 'household member', goal: 'See shared spend', authority: 'view household projection', entry_path: 'invite accept', ...meta('supporting') },
  ],
  entities: [
    {
      id: 'household',
      name: 'Household',
      identity: 'household id owned by primary member',
      attributes: [{ name: 'id', contract: 'stable id' }],
      relationships: [{ to: 'entity.account-link', type: 'has_many', cardinality: '1:n', lifecycle: 'cascade-archive' }],
      lifecycle_consequences: ['archive hides linked balances'],
      states: ['active', 'archived'],
      ...meta(),
    },
    {
      id: 'account-link',
      name: 'Account link',
      identity: 'provider account linkage per household',
      attributes: [{ name: 'status', contract: 'linked|error|revoked' }],
      relationships: [],
      lifecycle_consequences: ['revoke removes projections'],
      states: ['unlinked', 'linked', 'error', 'revoked'],
      ...meta(),
    },
  ],
  operations: [
    {
      id: 'link-account',
      name: 'Link account',
      actor_refs: ['actor.owner'],
      enforces: ['invariant.owner-only-link'],
      preconditions: ['Actor is authenticated owner'],
      failures: ['Provider denies OAuth', 'Member attempts link'],
      recovery: 'Remain unlinked and offer retry',
      transitions: [{ entity_ref: 'entity.account-link', from: 'unlinked', to: 'linked' }],
      outcome: 'Account appears in household budget',
      ...meta(),
    },
    {
      id: 'view-budget',
      name: 'View consolidated budget',
      actor_refs: ['actor.owner', 'actor.member'],
      enforces: ['invariant.household-scope'],
      preconditions: ['Actor belongs to household'],
      failures: ['Unauthenticated', 'Non-member'],
      recovery: 'Show sign-in or access denied',
      effects: ['Render household projection'],
      transitions: [],
      outcome: 'Shared balances and limits are shown',
      ...meta(),
    },
  ],
  workflows: [
    {
      id: 'link-and-view',
      name: 'Link account and view budget',
      actor_ref: 'actor.owner',
      steps: [
        { operation_ref: 'operation.link-account', actor_ref: 'actor.owner', dependency_refs: ['dependency.oauth'] },
        { operation_ref: 'operation.view-budget', actor_ref: 'actor.owner', dependency_refs: [] },
      ],
      terminal_outcomes: ['Shared budget visible', 'Link failed with recovery'],
      ...meta(),
    },
  ],
  invariants: [
    { id: 'owner-only-link', rule: 'Only owner may link accounts', ...meta() },
    { id: 'household-scope', rule: 'Members only see their household projection', ...meta() },
  ],
  dependencies: [
    {
      id: 'oauth',
      type: 'data',
      from: 'operation.link-account',
      to: 'entity.account-link',
      unmet_behavior: 'Show recoverable link error and keep account unlinked',
      ...meta('supporting'),
    },
  ],
  surfaces: [
    {
      id: 'budget-home',
      name: 'Budget home',
      purpose: 'Inspect shared balances and account link status',
      primary_actor_refs: ['actor.owner'],
      workflow_refs: ['workflow.link-and-view'],
      operation_refs: ['operation.link-account', 'operation.view-budget'],
      contract: ['Show shared balance', 'Show link status'],
      graph_refs: ['promise.shared-view'],
      ...meta(),
    },
  ],
  scenarios: [
    {
      id: 'link-failure',
      risk_key: 'provider_failure',
      when: { operation_ref: 'operation.link-account' },
      given: ['OAuth provider returns error'],
      then: ['Account remains unlinked', 'User sees recoverable error'],
      covers: ['operation.link-account', 'workflow.link-and-view'],
      ...meta(),
    },
    {
      id: 'empty-budget',
      risk_key: 'empty_state',
      when: { operation_ref: 'operation.view-budget' },
      given: ['No linked accounts'],
      then: ['Empty state explains next step to link'],
      covers: ['operation.view-budget', 'invariant.household-scope'],
      ...meta(),
    },
    {
      id: 'member-denied-link',
      risk_key: 'permission_denied',
      when: { operation_ref: 'operation.link-account' },
      given: ['Actor is member not owner'],
      then: ['Link is denied without changing state'],
      covers: ['operation.link-account', 'invariant.owner-only-link', 'workflow.link-and-view'],
      ...meta(),
    },
  ],
  proof_budget: {
    strategy: 'smallest_complete_slice',
    max_critical_promises: 3,
    max_active_operations: 10,
    max_active_workflows: 6,
    max_active_dependencies: 6,
    max_active_surfaces: 6,
    max_proofs: 12,
    rationale: 'One household link-and-view slice.',
  },
  proofs: [
    {
      id: 'shared-view',
      promise_refs: ['promise.shared-view'],
      operation_refs: ['operation.link-account', 'operation.view-budget'],
      workflow_ref: 'workflow.link-and-view',
      invariant_refs: ['invariant.household-scope', 'invariant.owner-only-link'],
      dependency_refs: ['dependency.oauth'],
      surface_refs: ['surface.budget-home'],
      given: ['Owner links an account'],
      then: ['Member and owner see the same consolidated balance'],
      evidence_levels: ['boundary', 'journey'],
      test_requirements: ['restart_or_reload', 'responsive', 'accessibility'],
      action: 'Owner completes account link then opens budget home',
      authoritative_state: 'account-link.status=linked and household projection refreshed',
      visible_outcome: 'Shared balance matches for owner and member',
      recovery: 'On provider failure, account stays unlinked with retry',
      ...meta(),
    },
  ],
  persona_findings: [
    {
      id: 'pf-owner-trust',
      persona_ref: 'owner',
      classification: 'risk',
      finding: 'Needs confidence that shared numbers match after link',
      source: 'persona_hypothesis',
      severity: 'high',
    },
  ],
  traceability: [
    {
      promise_ref: 'promise.shared-view',
      graph_refs: [
        'actor.owner',
        'entity.household',
        'operation.link-account',
        'operation.view-budget',
        'workflow.link-and-view',
        'invariant.household-scope',
        'surface.budget-home',
        'scenario.link-failure',
      ],
    },
  ],
  findings: [],
  evidence: [],
};

fs.writeFileSync(runPath, JSON.stringify(run, null, 2));
const ready = spawnSync('node', [tool, 'ready', runPath], { encoding: 'utf8' });
console.log('ready', ready.status);
console.log(((ready.stdout || '') + (ready.stderr || '')).split('\n').slice(0, 40).join('\n'));
const v = validateRunJson(runPath, { requireProofPacket: true });
console.log('validate', v.ok, v.errors?.slice(0, 20));
const final = JSON.parse(fs.readFileSync(runPath, 'utf8'));
console.log('status', final.status);
console.log('files', fs.readdirSync(dir));
if (ready.status === 0 && final.status === 'ready_to_build') {
  const outDir = path.join(HERE, '../templates');
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, 'minimal-ready-run.json'), JSON.stringify(final, null, 2));
  const impl = fs.existsSync(path.join(dir, 'implement.md')) ? fs.readFileSync(path.join(dir, 'implement.md'), 'utf8') : '';
  if (impl) fs.writeFileSync(path.join(outDir, 'minimal-implement.md'), impl);
  console.log('template ok', fs.statSync(path.join(outDir, 'minimal-ready-run.json')).size);
} else {
  process.exit(1);
}
