// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const home = fs.mkdtempSync(path.join(os.tmpdir(), "observal-pi-updates-"));
process.env.HOME = home;
const dir = path.join(home, ".observal");
fs.mkdirSync(dir, { recursive: true });
fs.writeFileSync(path.join(dir, "config.json"), JSON.stringify({
  server_url: "http://localhost:8000", access_token: "local-token", user_id: "alice",
}));
const worker = path.join(home, "mock-observal");
fs.writeFileSync(worker, `#!/usr/bin/env node
const fs = require('fs'); const path = require('path');
const args = process.argv.slice(2);
if (args[0] !== '_startup-check' && args[0] !== '_startup-apply') process.exit(2);
const key = args[args.indexOf('--notice-key') + 1];
const session = args[args.indexOf('--session-id') + 1];
fs.appendFileSync(path.join(process.env.HOME, 'worker-starts'), args[0] + ':' + session + '\\n');
setTimeout(() => {
  const root = path.join(process.env.HOME, '.observal', 'update-notices');
  fs.mkdirSync(root, {recursive: true, mode: 0o700});
  fs.writeFileSync(path.join(root, key + '.json'), JSON.stringify({schema: 1,
    registry: 'http://localhost:8000', account_id: 'alice', session_id: session,
    checked_at: Math.floor(Date.now()/1000), items: [{name: 'alice/code', type: 'agent',
      scope: 'user', status: session === 'pilot-session' ? 'updated' : 'available', current_version: '1.0', latest_version: '2.0',
      description: 'Fixed bugs', manual_command: 'observal agent pull alice/code --upgrade'}]}), {mode: 0o600});
}, 200);
`, { mode: 0o700 });
process.env.OBSERVAL_CLI_BIN = worker;

const handlers = new Map<string, (event: any, ctx: any) => Promise<void>>();
const pi = { on: (name: string, fn: any) => handlers.set(name, fn), registerCommand() {} };
const extension = await import(`../extensions/observal.ts?updates=${Date.now()}`);
extension.default(pi);
const messages: string[] = [];
const updateMessages = () => messages.filter((text) => text.includes("Fixed bugs") || text.includes("update check"));
const context = (session: string, ui: boolean) => ({
  cwd: home, hasUI: ui,
  sessionManager: { getSessionFile: () => null, getSessionId: () => session },
  ui: { notify: (text: string) => messages.push(text), theme: { fg: (_: string, text: string) => text }, setStatus() {} },
});
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitUntil(predicate: () => boolean): Promise<void> {
  for (let i = 0; i < 40; i++) {
    if (predicate()) return;
    await sleep(100);
  }
  assert.fail("startup result not delivered within 4 seconds");
}

await handlers.get("session_start")!({ reason: "startup" }, context("print-session", false));
await sleep(50);
assert.equal(fs.existsSync(path.join(dir, "update-notices")), false, "print mode must not start worker");

await handlers.get("session_start")!({ reason: "startup" }, context("session-a", true));
await handlers.get("session_start")!({ reason: "resume" }, context("session-a", true));
await handlers.get("session_shutdown")!({}, context("session-a", true));
const shutdown = path.join(dir, "update-shutdown");
assert.equal(fs.readdirSync(shutdown).length, 1, "departure marker written before a worker can start mutation");
assert.equal(fs.statSync(path.join(shutdown, fs.readdirSync(shutdown)[0]!)).mode & 0o777, 0o600);
await waitUntil(() => fs.existsSync(path.join(dir, "update-notices"))
  && fs.readdirSync(path.join(dir, "update-notices")).length === 1);
assert.equal(updateMessages().length, 0, "completed check must not notify a departed session");
assert.equal(fs.readdirSync(path.join(dir, "update-notices")).length, 1, "result survives shutdown");

await handlers.get("session_start")!({ reason: "startup" }, context("session-b", true));
assert.equal(updateMessages().length, 1);
assert.match(updateMessages()[0], /previous Pi session/);
assert.match(updateMessages()[0], /this check did not change files/);
assert.match(updateMessages()[0], /Fixed bugs/);
assert.match(updateMessages()[0], /1\.0 → 2\.0/);
await waitUntil(() => updateMessages().length === 2);
assert.equal(updateMessages().length, 2, "live result delivered once after child exits");
assert.equal(fs.readdirSync(path.join(dir, "update-notices")).length, 0);
assert.deepEqual(fs.readFileSync(path.join(home, "worker-starts"), "utf-8").trim().split("\n"),
  ["_startup-apply:session-a", "_startup-apply:session-b"], "start once per Pi session");
fs.writeFileSync(path.join(dir, "update-notices", `${"c".repeat(64)}.json`), JSON.stringify({
  schema: 1, registry: "http://localhost:8000", account_id: "alice", session_id: "session-a",
  checked_at: Math.floor(Date.now() / 1000), items: [{ name: "alice/code", type: "agent",
    scope: "user", status: "updated", current_version: "1.0", latest_version: "2.0",
    changelog: "Author release notes", reason: "Installed on disk and verified. Reload Pi." }],
}), { mode: 0o600 });
await handlers.get("session_start")!({ reason: "resume" }, context("session-b", true));
assert.match(messages.at(-1)!, /installed on disk/);
assert.match(messages.at(-1)!, /re-select the saved agent with \/agent/);
assert.match(messages.at(-1)!, /Author release notes/);
const multiFile = path.join(dir, "update-notices", `${"e".repeat(64)}.json`);
fs.writeFileSync(multiFile, JSON.stringify({
  schema: 1, registry: "http://localhost:8000", account_id: "alice", session_id: "session-a",
  checked_at: Math.floor(Date.now() / 1000), items: Array.from({ length: 20 }, (_, index) => ({
    name: `alice/item-${index}`, scope: "user", status: "available",
    current_version: "1.0", latest_version: "2.0", description: `notes-${index} ${"x".repeat(500)}`,
  })),
}), { mode: 0o600 });
await handlers.get("session_start")!({ reason: "resume" }, context("session-b", true));
assert.ok(messages.some((message) => message.includes("notes-19")), "the last item must not be truncated");
assert.equal(fs.existsSync(multiFile), false);
const recoveryFile = path.join(dir, "update-notices", `${"d".repeat(64)}.json`);
fs.writeFileSync(recoveryFile, JSON.stringify({
  schema: 1, registry: "http://localhost:8000", account_id: "alice", session_id: "session-a",
  checked_at: Math.floor(Date.now() / 1000), items: [{name: "alice/code", scope: "user", status: "failed",
    current_version: "1.0", latest_version: "2.0", description: "x".repeat(3900),
    reason: "Installer failed after admission; inspect managed files before retrying."}],
}), { mode: 0o600 });
await handlers.get("session_start")!({ reason: "resume" }, context("session-b", true));
assert.ok(messages.some((message) => message.includes("update failure from a previous Pi session")));
assert.ok(messages.some((message) => message.includes("inspect managed files before retrying")),
  "failure notices must explain manual inspection even with long release notes");
assert.equal(fs.existsSync(recoveryFile), false);
const pendingKey = "f".repeat(64);
const pendingFile = path.join(dir, "update-notices", `${pendingKey}.pending`);
const backupDir = path.join(dir, "update-backups", pendingKey);
fs.mkdirSync(backupDir, {recursive: true, mode: 0o700});
fs.writeFileSync(path.join(backupDir, "manifest.json"), JSON.stringify({schema: 1}));
const pendingIdentity = {registry: "http://localhost:8000", account_id: "alice", session_id: "session-a"};
fs.writeFileSync(pendingFile, JSON.stringify({schema: 1, state: "pending", ...pendingIdentity, backup_dir: backupDir,
  checked_at: Math.floor(Date.now() / 1000), item: {name: "alice/code", current_version: "1.0", latest_version: "2.0"}}),
{mode: 0o600});
const beforePending = messages.length;
await handlers.get("session_start")!({ reason: "resume" }, context("session-b", true));
assert.match(messages[beforePending]!, /outcome pending from a Pi session/);
assert.match(messages[beforePending]!, /Files may have changed/);
assert.ok(messages.slice(beforePending).some((message) => message.includes("inspect managed profiles and installed locks")),
  "unsealed mid-write crash must require manual inspection");
assert.ok(messages.slice(beforePending).some((message) => message.includes(backupDir)),
  "unresolved outcome must surface its private backup when available");
assert.ok(fs.existsSync(pendingFile), "unresolved journal must never be deleted on notification");
const unsealed = path.join(dir, "update-notices", `${pendingKey}.json`);
fs.writeFileSync(unsealed, JSON.stringify({schema: 1, ...pendingIdentity, journaled: true,
  outcome_final: true, checked_at: Math.floor(Date.now() / 1000), items: [{name: "alice/code",
    status: "updated", current_version: "1.0", latest_version: "2.0", scope: "user"}]}), {mode: 0o600});
const beforeSeal = messages.length;
await handlers.get("session_start")!({ reason: "resume" }, context("session-b", true));
assert.equal(messages.length, beforeSeal, "an unsealed final file cannot claim a verified install");
assert.ok(fs.existsSync(pendingFile) && fs.existsSync(unsealed));
const sealFile = path.join(dir, "update-notices", `${pendingKey}.complete`);
fs.writeFileSync(sealFile, JSON.stringify({schema: 1, state: "complete", ...pendingIdentity}), {mode: 0o600});
await handlers.get("session_start")!({ reason: "resume" }, context("session-b", true));
assert.match(messages.at(-1)!, /installed on disk/);
assert.ok(!fs.existsSync(pendingFile) && !fs.existsSync(unsealed) && !fs.existsSync(sealFile));
await handlers.get("session_shutdown")!({}, context("session-b", true));

await handlers.get("session_start")!({ reason: "startup" }, context("pilot-no-ui", false));
await sleep(100);
assert.equal(fs.readFileSync(path.join(home, "worker-starts"), "utf-8").trim().split("\n").length, 2,
  "pilot never launches an installer without UI");
await handlers.get("session_start")!({ reason: "startup" }, context("pilot-session", true));
await waitUntil(() => messages.some((message) => message.includes("installed on disk") && message.includes("Fixed bugs")));
assert.match(fs.readFileSync(path.join(home, "worker-starts"), "utf-8"), /_startup-apply:pilot-session/);
await handlers.get("session_shutdown")!({}, context("pilot-session", true));

fs.rmSync(home, { recursive: true, force: true });
console.log("startup update notices ok");
