#!/usr/bin/env node
/**
 * Seed a draft audit/verify run under .lamina/runs/<slug>/.
 * Initializes workspace only — never marks complete or fabricates findings.
 * Usage:
 *   node ./scripts/seed-verify-run.mjs --slug <kebab-slug> --problem "..." --outcome "..."
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
function flag(name, fallback = '') {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
}

if (args.includes('--help') || args.includes('-h')) {
  console.log(`Usage:
  node seed-verify-run.mjs --slug <kebab-slug> --problem "..." --outcome "..." [--users a,b]

Writes .lamina/runs/<slug>/{run.json,run.md} as a draft audit workspace.
Passing --help/-h prints this message and does not write any files.`);
  process.exit(0);
}

function findWorkspaceRoot(start = process.cwd()) {
  const skillMarker = start.match(
    /^(.*)\/\.(?:opencode|claude|codex|agents|cursor)\/skills(?:\/|$)/,
  );
  if (skillMarker?.[1] && fs.existsSync(path.join(skillMarker[1], '.lamina'))) {
    return skillMarker[1];
  }
  let dir = path.resolve(start);
  for (;;) {
    if (fs.existsSync(path.join(dir, '.lamina', 'business-context.md'))) return dir;
    if (fs.existsSync(path.join(dir, '.lamina', 'personas.json'))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return process.cwd();
}

export function hasConcreteTarget(problem) {
  const text = problem.trim();
  if (/@[\w/-]+/.test(text)) return true;
  if (/\b(our|the|this)\s+(app|application|product)'s\s+\S+/i.test(text)) return true;
  const auditTail = text.match(/\b(audit|review)\s+(.+)$/is);
  if (auditTail) {
    let rest = auditTail[2].trim();
    rest = rest.replace(/^(our|the|this)\s+(app|application|product)\s*,?\s*/i, '').trim();
    if (rest && !/^(app|application|product)\.?$/i.test(rest)) return true;
  }
  if (
    /\b(audit|review)\b/i.test(text) &&
    !/\b(our app|the app|the product|this app|the application)\b/i.test(text.toLowerCase())
  ) {
    return true;
  }
  return false;
}

export function isVagueBrief(problem) {
  const trimmed = problem.trim();
  const lower = trimmed.toLowerCase();
  if (/\b(brief is complete|do not clarify|proceed with labeled assumptions)\b/i.test(problem)) return false;
  if (/^audit our app\.?$|^review our app\.?$|^audit the app\.?$|^review the product\.?$/i.test(trimmed)) {
    return true;
  }
  if (
    /\b(audit|review)\b/.test(lower) &&
    /\b(our app|the app|the product|this app|the application)\b/.test(lower)
  ) {
    return !hasConcreteTarget(problem);
  }
  return false;
}

function createDraftRun({ slug, problem, outcome, users }) {
  return {
    contract_version: '2.0',
    id: slug,
    status: 'draft',
    stage: 'shape',
    hook: 'audit',
    target: slug,
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
      max_critical_promises: 3,
      max_active_operations: 10,
      max_active_workflows: 6,
      max_active_dependencies: 6,
      max_active_surfaces: 6,
      max_proofs: 12,
      rationale:
        'Brownfield verification starts empty; populate only behavior evidenced in the target project.',
    },
    proofs: [],
    persona_findings: [],
    traceability: [],
    findings: [],
    evidence: [],
  };
}

function personasStatus(workspace) {
  const personasPath = path.join(workspace, '.lamina/personas.json');
  if (!fs.existsSync(personasPath)) return { state: 'missing', ids: [] };
  try {
    const doc = JSON.parse(fs.readFileSync(personasPath, 'utf8'));
    const ids = (doc.personas || []).map((p) => p.id).filter(Boolean);
    if (!ids.length) return { state: 'empty', ids: [] };
    return { state: 'ok', ids };
  } catch {
    return { state: 'invalid', ids: [] };
  }
}

const WORKSPACE = findWorkspaceRoot();
const slug = flag('slug', '');
const problem = flag('problem', 'Existing product flow needs an evidence-backed UX audit');
const outcome = flag('outcome', 'Prioritized findings with fix.md and report.md');
const users = flag('users', 'primary-user')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

const isMain =
  process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
if (!slug || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
  console.error(
    'Missing/invalid --slug <kebab-slug>. Example: node seed-verify-run.mjs --slug <kebab-slug> --problem "..." --outcome "..."',
  );
  process.exit(2);
}

const asksTruncation =
  /\b(top\s*[0-9]|pick\s+[0-9]|skip the rest|only\s+[0-9]\s+lens|truncate|skip\s+(?:the\s+)?(?:rest|other)s?)\b/i.test(
    problem,
  );

if (isVagueBrief(problem)) {
  console.error(
    'REFUSE_SEED: problem lacks a concrete flow/surface target. Emit the clarification contract and STOP — do not write .lamina/runs.',
  );
  process.exit(3);
}

const run = createDraftRun({ slug, problem, outcome, users });

const errors = [];
if (run.contract_version !== '2.0') errors.push('contract_version');
if (run.status !== 'draft') errors.push('status');
if (run.hook !== 'audit') errors.push('hook');
if (run.findings.length) errors.push('findings');
if (run.persona_findings.length) errors.push('persona_findings');
if (errors.length) {
  console.error('Seeded run failed basic checks: ' + errors.join(', '));
  process.exit(1);
}

const personas = personasStatus(WORKSPACE);

const outDir = path.join(WORKSPACE, '.lamina/runs', slug);
fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(path.join(outDir, 'run.json'), JSON.stringify(run, null, 2) + '\n');

const runMd = `# Run — ${slug}

**Status:** draft (audit in progress)

## Problem
${problem}

## Outcome
${outcome}

## Next steps
1. Inspect the named target in the project (read-only app source and/or runnable UI).
2. Choose grounding mode: prefer live UI capture when runnable; otherwise static UI source. Record mode and evidence gaps.
3. Build or load a project-grounded graph in \`run.json\`; set \`status: verifying\` while auditing.
4. Ensure valid personas exist (use \`lamina-user-modeling\` to derive provisional personas from business context plus observed source when \`.lamina/personas.json\` is missing, empty, or invalid), then run \`persona-packs\` and isolated persona reviewers before completion.
5. Merge evidence-backed \`findings[]\`; validate; render \`report.md\`, \`fix.md\`, and \`implement.md\`; set \`status: complete\`.
`;

fs.writeFileSync(path.join(outDir, 'run.md'), runMd);

console.log(`Seeded ${path.relative(WORKSPACE, outDir) || outDir} (status=${run.status}) workspace=${WORKSPACE}`);
console.log(
  'NEXT: Inspect the target project (read-only). Choose grounding mode (live UI preferred; static source fallback) and build a project-grounded graph in run.json.',
);
console.log('NEXT: Persona panel is mandatory for brownfield verification.');
if (personas.state === 'ok') {
  console.log(
    `NEXT: Run graph-tool.mjs persona-packs (${personas.ids.join(', ')}) and spawn isolated reviewers before marking complete.`,
  );
} else {
  console.log(
    `NEXT: personas.json is ${personas.state}. Read lamina-user-modeling/SKILL.md, derive evidence-grounded provisional personas from business-context.md plus observed brownfield source, write and validate .lamina/personas.json, then run persona-packs. Never skip the panel or fabricate persona findings.`,
  );
}
console.log(
  'NEXT: After evidence-backed findings merge, validate run.json, render report.md/fix.md/implement.md, then set status=complete.',
);
console.log('Do not emit ### Executive summary / ### Findings until completion artifacts validate.');
if (asksTruncation) {
  console.log(
    'TRUNCATION_REFUSE: user asked to skip lenses — refuse truncation and apply the full-flow lens set during verification.',
  );
}
}
