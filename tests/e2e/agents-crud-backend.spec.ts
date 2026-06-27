// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { execSync } from "child_process";
import { API_BASE, getAccessToken } from "./helpers";

const CLI_TIMEOUT = 30_000;

function cli(cmd: string): string {
  return execSync(cmd, { encoding: "utf-8", timeout: CLI_TIMEOUT });
}

test.describe("Agents - Backend and CLI CRUD (#937)", () => {
  test.describe.configure({ mode: "serial" });

  let token: string;
  let agentId: string;
  const agentName = `e2e-crud-agent-${Date.now()}`;

  test.beforeAll(async () => {
    token = await getAccessToken();
  });

  test("Backend: create agent via POST /agents", async () => {
    const res = await fetch(`${API_BASE}/api/v1/agents`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: agentName,
        version: "1.0.0",
        description: "E2E CRUD test agent",
        owner: "admin",
        model_name: "claude-sonnet-4-20250514",
        prompt: "You are a test agent.",
      }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    agentId = body.id;
    expect(agentId).toBeTruthy();
  });

  test("Backend: approve agent", async () => {
    const res = await fetch(`${API_BASE}/api/v1/review/agents/${agentId}/approve`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ notes: "e2e" }),
    });
    expect(res.status).toBe(200);
  });

  test("Backend: GET /agents lists the created agent", async () => {
    const res = await fetch(`${API_BASE}/api/v1/agents`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.status).toBe(200);
    const agents = await res.json();
    const found = agents.find((a: { id: string }) => a.id === agentId);
    expect(found).toBeTruthy();
  });

  test("Backend: DELETE agent returns success, then 404", async () => {
    const delRes = await fetch(`${API_BASE}/api/v1/agents/${agentId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(delRes.status).toBe(200);

    const getRes = await fetch(`${API_BASE}/api/v1/agents/${agentId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(getRes.status).toBe(404);
  });

  test("CLI: observal pull --dry-run outputs file paths", () => {
    // Get an existing agent to pull
    let agents: { name?: string }[];
    try {
      agents = JSON.parse(cli("observal agent list --output json 2>/dev/null"));
    } catch {
      test.skip();
      return;
    }
    if (!agents || agents.length === 0) {
      test.skip();
      return;
    }

    const name = agents[0].name;
    const output = cli(
      `observal pull ${name} --ide cursor --dry-run 2>&1 || true`,
    );
    expect(output).not.toContain("Traceback");
    expect(output).toMatch(/Would write|dry.run|file/i);
  });
});
