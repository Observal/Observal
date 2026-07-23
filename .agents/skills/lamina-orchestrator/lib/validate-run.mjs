#!/usr/bin/env node
import { validateRunJson } from './run.mjs';

const runPath = process.argv[2];
if (!runPath) {
  console.error('Usage: node <lamina-orchestrator-skill>/lib/validate-run.mjs <path-to-run.json>');
  process.exit(1);
}
const result = validateRunJson(runPath);
if (!result.ok) {
  for (const error of result.errors) console.error(error);
  process.exit(1);
}
console.log('run.json valid');
