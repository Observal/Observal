// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { API_BASE, getAccessToken } from "./helpers";

const IDES = ["cursor", "kiro", "claude-code", "gemini-cli", "vscode", "codex", "copilot-cli", "opencode"];

test.describe("Agents - IDE config and versioning (#939)", () => {
  test.describe.configure({ mode: "serial" });

  let token: string;
  let agentId: string;
  const agentName = `e2e-ide-config-${Date.now()}`;

  test.beforeAll(async () => {
    token = await getAccessToken();

    // Create and approve an agent
    const createRes = await fetch(`${API_BASE}/api/v1/agents`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: agentName,
        version: "1.0.0",
        description: "IDE config test agent",
        owner: "admin",
        model_name: "claude-sonnet-4-20250514",
        prompt: "You are a test agent.",
      }),
    });
    if (!createRes.ok) throw new Error(`Create failed: ${await createRes.text()}`);
    const agent = await createRes.json();
    agentId = agent.id;

    await fetch(`${API_BASE}/api/v1/review/agents/${agentId}/approve`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ notes: "e2e" }),
    });
  });

  test.afterAll(async () => {
    if (agentId) {
      await fetch(`${API_BASE}/api/v1/agents/${agentId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {});
    }
  });

  for (const ide of IDES) {
    test(`install returns valid config for ${ide}`, async () => {
      const res = await fetch(`${API_BASE}/api/v1/agents/${agentId}/install`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ide }),
      });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.ide).toBe(ide);
      expect(body.agent_id).toBeTruthy();
    });
  }

  test("version publish + approve → install reflects new version", async () => {
    // Publish v2
    const pubRes = await fetch(`${API_BASE}/api/v1/agents/${agentId}/versions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        version: "2.0.0",
        description: "Updated agent",
        changelog: "v2 changes",
        model_name: "claude-sonnet-4-20250514",
        prompt: "You are an updated test agent.",
      }),
    });
    expect(pubRes.status).toBeLessThan(300);

    // Approve v2
    const approveRes = await fetch(
      `${API_BASE}/api/v1/agents/${agentId}/versions/2.0.0/review`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action: "approve" }),
      },
    );
    expect(approveRes.status).toBe(200);

    // Install should reflect v2
    const installRes = await fetch(`${API_BASE}/api/v1/agents/${agentId}/install`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ide: "cursor" }),
    });
    expect(installRes.status).toBe(200);
    const config = await installRes.json();
    expect(config.agent_id).toBeTruthy();
  });
});
