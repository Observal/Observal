# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from observal_shared.opencode_plugin_source import OPENCODE_PLUGIN_SOURCE, OPENCODE_PLUGIN_VERSION

if TYPE_CHECKING:
    from pathlib import Path


def test_generated_plugin_uses_durable_acknowledged_delivery():
    assert OPENCODE_PLUGIN_VERSION == "4"
    assert "saveSessionState(state); // Durable before network delivery." in OPENCODE_PLUGIN_SOURCE
    assert "acknowledged_line" in OPENCODE_PLUGIN_SOURCE
    assert "pushedMessageIds" not in OPENCODE_PLUGIN_SOURCE
    assert "state.acknowledgedLine + 1" in OPENCODE_PLUGIN_SOURCE


def test_native_outbox_survives_restart_and_clears_only_after_ack(tmp_path: Path):
    plugin = tmp_path / "plugin.ts"
    plugin.write_text(
        OPENCODE_PLUGIN_SOURCE
        + "\nexport { newSessionState, statePath, loadSessionState, saveSessionState, applyAcknowledgement };\n"
    )
    runner = tmp_path / "runner.mjs"
    runner.write_text(
        """
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const plugin = await import(pathToFileURL(process.argv[2]));
let state = plugin.newSessionState("session");
state.agentName = "agent";
state.pending = {
  destination: "http://server",
  userId: "user",
  startLine: 0,
  endLine: 1,
  lines: ["one", "two"],
  agentId: "agent-id",
  agentVersion: "1.0.0",
  final: false,
};
plugin.saveSessionState(state);
const path = plugin.statePath("session");
assert.equal(existsSync(path), true);
assert.equal(Number.parseInt((await import("node:fs")).statSync(path).mode.toString(8).slice(-3)), 600);

state = plugin.loadSessionState("session");
assert.equal(state.pending.endLine, 1);
assert.equal(plugin.applyAcknowledgement(state, { acknowledged_line: 0 }), false);
assert.equal(plugin.loadSessionState("session").pending.endLine, 1);
assert.equal(plugin.applyAcknowledgement(state, { acknowledged_line: 1 }), true);
state = plugin.loadSessionState("session");
assert.equal(state.pending, null);
assert.equal(state.acknowledgedLine, 1);

writeFileSync(path, "not-json");
assert.throws(() => plugin.loadSessionState("session"), /outbox is corrupt/);
assert.equal(readFileSync(path, "utf-8"), "not-json");

const observalDir = join(process.env.HOME, ".observal");
mkdirSync(observalDir, { recursive: true });
writeFileSync(join(observalDir, "config.json"), JSON.stringify({
  server_url: "http://server",
  access_token: "token",
  user_id: "user",
}));
writeFileSync(join(observalDir, "lockfile.json"), JSON.stringify({
  harnesses: { opencode: { agents: [{ name: "custom", id: "agent-id", version: "1.0.0", scope: "user" }] } },
}));
const client = {
  app: { log: async () => {} },
  session: { messages: async () => ({ data: [
    { info: { id: "m1", role: "user", timestamp: "2026-01-01T00:00:00Z" }, parts: [{ type: "text", text: "hello" }] },
    { info: { id: "m2", role: "assistant", timestamp: "2026-01-01T00:00:01Z" }, parts: [{ type: "text", text: "hi" }] },
  ] }) },
};
let shouldFail = true;
let requests = 0;
globalThis.fetch = async () => {
  requests += 1;
  if (shouldFail) return { ok: false, status: 503 };
  return { ok: true, json: async () => ({ acknowledged_line: 1, acknowledged_offset: 0 }) };
};
const hooks = await plugin.ObservalPlugin({ client, directory: "/work" });
await hooks.event({ event: { type: "session.created", properties: { sessionID: "delivery", agent: "custom" } } });
await hooks.event({ event: { type: "message.updated", properties: { sessionID: "delivery" } } });
await hooks.event({ event: { type: "session.idle", properties: { sessionID: "delivery" } } });
let delivery = plugin.loadSessionState("delivery");
assert.equal(delivery.acknowledgedLine, -1);
assert.equal(delivery.pending.endLine, 1);
shouldFail = false;
await hooks.event({ event: { type: "session.idle", properties: { sessionID: "delivery" } } });
delivery = plugin.loadSessionState("delivery");
assert.equal(delivery.pending, null);
assert.equal(delivery.acknowledgedLine, 1);
assert.equal(requests, 2);
"""
    )
    env = os.environ | {"HOME": str(tmp_path)}

    result = subprocess.run(
        ["node", "--experimental-strip-types", str(runner), str(plugin)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
