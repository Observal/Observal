// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as http from "node:http";
import * as os from "node:os";
import * as path from "node:path";

const home = fs.mkdtempSync(path.join(os.tmpdir(), "observal-pi-"));
process.env.HOME = home;

const observalDir = path.join(home, ".observal");
fs.mkdirSync(observalDir, { recursive: true });
const sessionFile = path.join(home, "session.jsonl");
const lines = Array.from({ length: 501 }, (_, index) => JSON.stringify({ type: "message", index }));
fs.writeFileSync(sessionFile, `${lines.join("\n")}\n`);

const ingestPayloads = [];
let serverAcknowledgedLine = -1;
let serverAcknowledgedOffset = 0;
let repairFinalOnce = false;
const server = http.createServer((request, response) => {
  response.setHeader("Content-Type", "application/json");
  if (request.method === "GET" && request.url?.startsWith("/api/v1/ingest/session/checkpoint")) {
    response.end(JSON.stringify({
      session_id: "pi-session",
      harness: "pi",
      acknowledged_line: serverAcknowledgedLine,
      acknowledged_offset: serverAcknowledgedOffset,
    }));
    return;
  }
  const chunks = [];
  request.on("data", (chunk) => chunks.push(chunk));
  request.on("end", () => {
    const payload = JSON.parse(Buffer.concat(chunks).toString("utf-8"));
    if (request.url === "/api/v1/layer-snapshots") {
      response.end(JSON.stringify({ hash: payload.hash }));
      return;
    }

    ingestPayloads.push(payload);
    if (ingestPayloads.length === 2) {
      response.end(JSON.stringify({ ingested: payload.lines.length })); // HTTP success without acknowledgement.
      return;
    }
    if (repairFinalOnce && payload.final) {
      repairFinalOnce = false;
      serverAcknowledgedLine = 499;
      serverAcknowledgedOffset = ingestPayloads[0].end_byte_offsets.at(-1);
      response.end(JSON.stringify({
        acknowledged_line: serverAcknowledgedLine,
        acknowledged_offset: serverAcknowledgedOffset,
        integrity_ok: false,
        repair_from_line: 500,
      }));
      return;
    }
    if (payload.lines.length > 0) {
      serverAcknowledgedLine = payload.start_offset + payload.lines.length - 1;
      serverAcknowledgedOffset = payload.end_byte_offsets.at(-1);
    }
    response.end(
      JSON.stringify({
        acknowledged_line: serverAcknowledgedLine,
        acknowledged_offset: serverAcknowledgedOffset,
      }),
    );
  });
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const address = server.address();
assert(address && typeof address === "object");
fs.writeFileSync(
  path.join(observalDir, "config.json"),
  JSON.stringify({
    server_url: `http://127.0.0.1:${address.port}`,
    access_token: "token",
    user_id: "user",
  }),
);

const handlers = new Map();
const pi = {
  on(name, handler) {
    handlers.set(name, handler);
  },
  registerCommand() {},
};
const extension = await import(`../extensions/observal.ts?test=${Date.now()}`);
extension.default(pi);
const context = {
  cwd: "/project",
  hasUI: false,
  sessionManager: {
    getSessionFile: () => sessionFile,
    getSessionId: () => "pi-session",
  },
};

await handlers.get("session_start")({ reason: "resume" }, context);
await handlers.get("agent_end")({}, context);

const statePath = path.join(observalDir, "sync_state.json");
let cursor = JSON.parse(fs.readFileSync(statePath, "utf-8"))["pi-session"];
assert.equal(cursor.line_count, 500, "only the acknowledged first chunk advances");
assert(cursor.offset < fs.statSync(sessionFile).size);
const outboxDir = path.join(observalDir, "pi_session_outbox");
let outboxFiles = fs.readdirSync(outboxDir);
assert.equal(outboxFiles.length, 1);
const pending = JSON.parse(fs.readFileSync(path.join(outboxDir, outboxFiles[0]), "utf-8"));
assert.equal(pending.payload.start_offset, 500);
assert.deepEqual(pending.payload.lines, [lines[500]]);

const restartedHandlers = new Map();
const restartedPi = {
  on(name, handler) {
    restartedHandlers.set(name, handler);
  },
  registerCommand() {},
};
const restartedExtension = await import(`../extensions/observal.ts?restart=${Date.now()}`);
restartedExtension.default(restartedPi);
await restartedHandlers.get("session_start")({ reason: "resume" }, context);
await restartedHandlers.get("agent_end")({}, context);
cursor = JSON.parse(fs.readFileSync(statePath, "utf-8"))["pi-session"];
assert.equal(cursor.line_count, 501);
assert.equal(cursor.offset, fs.statSync(sessionFile).size);
outboxFiles = fs.readdirSync(outboxDir);
assert.equal(outboxFiles.length, 0);
assert.equal(ingestPayloads.length, 3);
assert.deepEqual(ingestPayloads[1], ingestPayloads[2], "retry keeps the same source identity and content");

fs.unlinkSync(statePath);
const recoveredHandlers = new Map();
const recoveredPi = {
  on(name, handler) {
    recoveredHandlers.set(name, handler);
  },
  registerCommand() {},
};
const recoveredExtension = await import(`../extensions/observal.ts?recover=${Date.now()}`);
recoveredExtension.default(recoveredPi);
await recoveredHandlers.get("session_start")({ reason: "resume" }, context);
await recoveredHandlers.get("agent_end")({}, context);
cursor = JSON.parse(fs.readFileSync(statePath, "utf-8"))["pi-session"];
assert.equal(cursor.line_count, 501, "missing local state recovers from the server checkpoint");
assert.equal(ingestPayloads.length, 3, "checkpoint recovery avoids replaying acknowledged history");

repairFinalOnce = true;
await recoveredHandlers.get("session_shutdown")({}, context);
cursor = JSON.parse(fs.readFileSync(statePath, "utf-8"))["pi-session"];
assert.equal(cursor.finalized, true, "finality also requires a server acknowledgement");
assert.equal(ingestPayloads[3].final, true);
assert.deepEqual(ingestPayloads[3].lines, []);
assert.equal(ingestPayloads[4].start_offset, 500, "repair rewinds and replays in the same finalizer");
assert.deepEqual(ingestPayloads[4].lines, [lines[500]]);
assert.equal(ingestPayloads[4].final, true);

await new Promise((resolve) => server.close(resolve));
fs.rmSync(home, { recursive: true, force: true });
console.log("Pi acknowledged delivery check passed");
