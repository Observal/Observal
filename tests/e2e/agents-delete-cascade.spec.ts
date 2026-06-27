// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { API_BASE, getAccessToken } from "./helpers";

test.describe("Agents - Delete cascade (#941)", () => {
  test.describe.configure({ mode: "serial" });

  let token: string;
  let agentId: string;

  test.beforeAll(async () => {
    token = await getAccessToken();

    // Create agent with a component link
    const mcpRes = await fetch(`${API_BASE}/api/v1/mcps/submit`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: `e2e-cascade-mcp-${Date.now()}`,
        description: "MCP for cascade test",
        version: "1.0.0",
        category: "developer-tools",
        owner: "admin",
        command: "echo",
        args: ["hello"],
      }),
    });
    const mcp = await mcpRes.json();
    const mcpId = mcp.id;

    // Approve MCP
    await fetch(`${API_BASE}/api/v1/review/${mcpId}/approve`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ notes: "e2e" }),
    });

    // Create agent with that MCP
    const createRes = await fetch(`${API_BASE}/api/v1/agents`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: `e2e-cascade-agent-${Date.now()}`,
        version: "1.0.0",
        description: "Agent for delete cascade test",
        owner: "admin",
        model_name: "claude-sonnet-4-20250514",
        prompt: "You are a test agent.",
        mcp_server_ids: [mcpId],
      }),
    });
    if (!createRes.ok) throw new Error(`Create failed: ${await createRes.text()}`);
    const agent = await createRes.json();
    agentId = agent.id;
  });

  test("DELETE agent succeeds", async () => {
    const res = await fetch(`${API_BASE}/api/v1/agents/${agentId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.deleted).toBe(agentId);
  });

  test("deleted agent returns 404", async () => {
    const res = await fetch(`${API_BASE}/api/v1/agents/${agentId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.status).toBe(404);
  });

  test("resolve endpoint returns 404 for deleted agent", async () => {
    const res = await fetch(`${API_BASE}/api/v1/agents/${agentId}/resolve`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.status).toBe(404);
  });
});
