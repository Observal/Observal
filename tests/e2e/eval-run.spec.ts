// SPDX-FileCopyrightText: 2026 Tanvi Reddy <tanvi.reddy330@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { execSync } from "child_process";
import { API_BASE, getAccessToken } from "./helpers";

test.describe("Eval - Run eval and scorecard creation", () => {
  let agentId: string;
  let adminToken: string;

  test("POST eval run and GET scorecards", async () => {
    adminToken = await getAccessToken();

    // Create an agent to run eval against
    const agentName = `e2e-eval-agent-${Date.now()}`;
    const createRes = await fetch(`${API_BASE}/api/v1/agents`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${adminToken}`,
      },
      body: JSON.stringify({
        name: agentName,
        version: "1.0.0",
        description: "Agent for eval e2e test",
        owner: "admin",
        model_name: "claude-sonnet-4-20250514",
        goal_template: {
          description: "E2E eval test goal",
          sections: [{ name: "Goal", content: "Complete the task" }],
        },
      }),
    });
    expect(createRes.status).toBe(200);
    const agent = await createRes.json();
    agentId = agent.id;

    // Trigger an eval run
    const evalRes = await fetch(`${API_BASE}/api/v1/eval/agents/${agentId}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    // Eval may return 200 (success) or 202 (queued) or 404 (no traces to eval)
    expect([200, 202, 404]).toContain(evalRes.status);

    // Get scorecards for this agent
    const scorecardsRes = await fetch(`${API_BASE}/api/v1/eval/agents/${agentId}/scorecards`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(scorecardsRes.status).toBe(200);
    const scorecards = await scorecardsRes.json();
    expect(Array.isArray(scorecards)).toBe(true);
  });

  test.afterAll(async () => {
    // Cleanup: delete the test agent
    if (agentId && adminToken) {
      try {
        await fetch(`${API_BASE}/api/v1/agents/${agentId}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${adminToken}` },
        });
      } catch {
        // Best-effort cleanup
      }
    }
  });
});

test.describe("Eval - CLI", () => {
  test("observal admin eval run command exists", async () => {
    const output = execSync("observal admin eval run --help", {
      timeout: 10_000,
      encoding: "utf-8",
    });
    // Verify the CLI command exists and shows help output
    expect(output).toContain("run");
  });
});
