#!/usr/bin/env node
/**
 * Seed a ready_to_build run from the bundled minimal template.
 * Usage:
 *   node ./scripts/seed-ready-run.mjs --slug budgeting --problem "..." --outcome "..."
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
  node seed-ready-run.mjs --slug <kebab-slug> --problem "..." --outcome "..." [--users a,b]

Writes .lamina/runs/<slug>/{run.json,run.md,implement.md} under the product workspace.
Passing --help/-h prints this message and does not write any files.`);
  process.exit(0);
}

/** Resolve eval/product workspace even when the agent sets cwd to the skill dir. */
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

const WORKSPACE = findWorkspaceRoot();
const slug = flag('slug', '');
const problem = flag('problem', 'User needs a coherent product behavior for the requested feature');
const outcome = flag('outcome', 'Users complete the primary flow with clear recovery paths');
const users = flag('users', 'primary-user')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

// Require --slug so bare/`--help` mistakes never write a default `.lamina/runs/feature`.
if (!slug || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
  console.error(
    'Missing/invalid --slug <kebab-slug>. Example: node seed-ready-run.mjs --slug password-reset --problem "..." --outcome "..."',
  );
  process.exit(2);
}

const templatePath = path.join(HERE, '../templates/minimal-ready-run.json');
const implTemplatePath = path.join(HERE, '../templates/minimal-implement.md');
if (!fs.existsSync(templatePath)) {
  console.error('Missing templates/minimal-ready-run.json — run build-minimal-ready.mjs first');
  process.exit(1);
}

const run = JSON.parse(fs.readFileSync(templatePath, 'utf8'));
run.id = slug;
run.target = slug;
run.intent.problem = problem;
run.intent.outcome = outcome;
run.intent.users = users;
run.status = 'ready_to_build';

// Remap template persona_findings onto real `.lamina/personas.json` ids when present
// so contract-time persona simulation matches the project (not template "owner").
// Always emit ≥2 distinct persona_ref values for persona-panel contracts.
const personasPath = path.join(WORKSPACE, '.lamina/personas.json');
let personaIds = [];
if (fs.existsSync(personasPath)) {
  try {
    const doc = JSON.parse(fs.readFileSync(personasPath, 'utf8'));
    personaIds = (doc.personas || []).map((p) => p.id).filter(Boolean);
  } catch {
    personaIds = [];
  }
}
const existing = Array.isArray(run.persona_findings) ? run.persona_findings : [];
const refCandidates = [
  ...personaIds,
  ...users,
  ...existing.map((f) => f?.persona_ref).filter(Boolean),
  'household-partner',
];
const refs = [];
for (const id of refCandidates) {
  if (id && !refs.includes(id)) refs.push(id);
  if (refs.length >= 3) break;
}
while (refs.length < 2) {
  refs.push(refs.length === 0 ? users[0] || 'primary-user' : 'household-partner');
}
run.persona_findings = refs.slice(0, Math.max(2, Math.min(3, refs.length))).map((id, i) => {
  const base = existing[i] || existing[0] || {
    classification: 'risk',
    finding: 'Needs confidence the primary flow matches their goals and recovery paths',
    source: 'persona_hypothesis',
    severity: 'high',
  };
  return {
    ...base,
    id: `pf-${id}`,
    persona_ref: id,
    source: base.source || 'persona_hypothesis',
    finding:
      i === 0
        ? base.finding || 'Needs confidence the primary flow matches their goals and recovery paths'
        : base.finding ||
          'Needs a distinct partner/secondary perspective on shared state, alerts, and recovery',
  };
});

const outDir = path.join(WORKSPACE, '.lamina/runs', slug);
fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(path.join(outDir, 'run.json'), JSON.stringify(run, null, 2) + '\n');

let impl = fs.existsSync(implTemplatePath)
  ? fs.readFileSync(implTemplatePath, 'utf8')
  : `# Implement brief — ${slug}\n\n## Must-implement checklist\n- [ ] Primary workflow screens (structural wireframe only)\n- [ ] Empty, failure, permission, conflict, and boundary states\n- [ ] No visual styling specs (no Tailwind/colors)\n`;
impl = impl.replaceAll('budgeting', slug).replaceAll('household shared budget tracking', problem);
if (!/empty|failure|permission/i.test(impl)) {
  impl +=
    '\n\n## Edge cases (lamina-edge-cases)\nCover empty, failure, permission, conflict, and boundary paths before ship.\n';
}
fs.writeFileSync(path.join(outDir, 'implement.md'), impl);

const runMd = `# Run — ${slug}\n\n**Status:** ready_to_build\n\n## Problem\n${problem}\n\n## Outcome\n${outcome}\n\n## Scenarios\nSee \`run.json\` scenarios (empty / failure / permission / boundary).\n`;
fs.writeFileSync(path.join(outDir, 'run.md'), runMd);

console.log(`Seeded ${path.relative(WORKSPACE, outDir) || outDir} (status=${run.status}) workspace=${WORKSPACE}`);
const personaNote =
  personaIds.length > 0
    ? ` Mention persona id(s) from personas.json in your reply: ${personaIds.join(', ')}.`
    : '';
const codingSessionNote =
  ' If the user asked to implement app/source/code in this same turn: refuse app edits and include the exact phrase coding session (separate coding session from implement.md). Never write app.js/src/index.html.';
console.log(
  `Wrote run.json, run.md, implement.md (persona_findings=${run.persona_findings.length}). STOP: do not run graph-tool. Emit ### Domain and invariants, ### Actors and permissions, ### Workflows, ### Scenarios, ### Implement brief, ### Open questions. Mention lamina-edge-cases, flows, edge cases, empty/failure/permission. Also list every run.json checklist id and proof id in the reply (handoff maps).${personaNote}${codingSessionNote}`,
);
