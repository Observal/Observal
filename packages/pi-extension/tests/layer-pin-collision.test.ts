// SPDX-FileCopyrightText: 2026 Naraen Rammoorthi
// SPDX-License-Identifier: Apache-2.0

// Phase 0 current-behaviour proof: file-only Pi hashes do not identify registry pins.
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as http from "node:http";
import * as os from "node:os";
import * as path from "node:path";

const home = fs.mkdtempSync(path.join(os.tmpdir(), "observal-pi-phase0-"));
process.env.HOME = home;
const observalDir = path.join(home, ".observal");
const piDir = path.join(home, ".pi", "agent");
fs.mkdirSync(observalDir, { recursive: true });
fs.mkdirSync(piDir, { recursive: true });
fs.writeFileSync(path.join(piDir, "mcp.json"), JSON.stringify({ mcpServers: { fixture: { command: "fixture" } } }));
const snapshots: any[] = [];
const server = http.createServer((request, response) => {
  response.setHeader("Content-Type", "application/json");
  const chunks: Buffer[] = [];
  request.on("data", (chunk) => chunks.push(chunk));
  request.on("end", () => {
    if (request.url === "/api/v1/layer-snapshots") {
      const snapshot = JSON.parse(Buffer.concat(chunks).toString("utf-8"));
      snapshots.push(snapshot);
      response.end(JSON.stringify({ hash: snapshot.hash }));
    } else {
      response.statusCode = 404;
      response.end("{}");
    }
  });
});
await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
const address = server.address();
assert(address && typeof address === "object");
const url = `http://127.0.0.1:${address.port}`;
fs.writeFileSync(path.join(observalDir, "config.json"), JSON.stringify({ server_url: url, access_token: "fixture-token" }));
const lockPath = path.join(observalDir, "lockfile.json");
const agent = { id: "00000000-0000-4000-8000-000000000001", name: "fixture", version: "1.0.0", components: [
  { type: "mcp", name: "probe", id: "11111111-1111-4111-8111-111111111111", version: "1.0.0", local_name: "first" },
] };
function writePins() {
  fs.writeFileSync(lockPath, JSON.stringify({ registries: { [url]: { harnesses: { pi: { agents: [agent], standalone: [] } } } } }));
}
writePins();
const handlers = new Map<string, (event: unknown, ctx: unknown) => Promise<void>>();
const pi = { on: (name: string, handler: any) => handlers.set(name, handler), registerCommand() {} };
const extension = await import(`../extensions/observal.ts?phase0=${Date.now()}`);
extension.default(pi);
const context = { cwd: home, hasUI: false, sessionManager: { getSessionFile: () => null, getSessionId: () => "pi-phase0" } };
async function snapshotNumber(count: number) {
  await handlers.get("session_start")!({ reason: "start" }, context);
  const deadline = Date.now() + 3000;
  while (snapshots.length < count && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(snapshots.length, count);
  return snapshots[count - 1];
}
const first = await snapshotNumber(1);
agent.components[0].id = "22222222-2222-4222-8222-222222222222";
agent.components[0].version = "2.0.0";
agent.components[0].local_name = "second";
writePins();
// Current file-only hash prevents a second upload; wait for and remove only our test cache.
const cache = path.join(observalDir, "layer_snapshot.json");
const cacheDeadline = Date.now() + 3000;
while (!fs.existsSync(cache) && Date.now() < cacheDeadline) await new Promise((resolve) => setTimeout(resolve, 10));
assert(fs.existsSync(cache));
fs.unlinkSync(cache);
const second = await snapshotNumber(2);
assert.equal(first.hash, second.hash);
assert.equal(first.hash.length, 16);
assert.deepEqual(first.harnesses, second.harnesses);
assert.notDeepEqual(first.pinned_versions, second.pinned_versions);
assert.equal(first.pinned_versions.agents[0].components[0].id, "11111111-1111-4111-8111-111111111111");
assert.equal(second.pinned_versions.agents[0].components[0].local_name, "second");
server.close();
fs.rmSync(home, { recursive: true, force: true });
console.log("Pi layer pin collision current behaviour verified");
