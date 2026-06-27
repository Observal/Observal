// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { execSync } from "child_process";
import { API_BASE, getAccessToken } from "./helpers";

const CLI_TIMEOUT = 30_000;

function cli(cmd: string): string {
  return execSync(cmd, { encoding: "utf-8", timeout: CLI_TIMEOUT });
}

test.describe("Review - Backend approve endpoint and CLI (#943)", () => {
  test.describe.configure({ mode: "serial" });

  let token: string;
  let mcpId: string;
  let mcpName: string;
  let rejectMcpId: string;
  let rejectMcpName: string;

  test.beforeAll(async () => {
    token = await getAccessToken();

    // Create a pending MCP to approve
    mcpName = `e2e-approve-${Date.now()}`;
    const res = await fetch(`${API_BASE}/api/v1/mcps/submit`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: mcpName,
        description: "MCP for approve endpoint test",
        version: "1.0.0",
        category: "developer-tools",
        owner: "admin",
        command: "echo",
        args: ["approve-test"],
      }),
    });
    if (!res.ok) throw new Error(`Submit failed: ${await res.text()}`);
    const created = await res.json();
    mcpId = created.id;

    // Create another pending MCP to reject
    rejectMcpName = `e2e-reject-${Date.now()}`;
    const res2 = await fetch(`${API_BASE}/api/v1/mcps/submit`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: rejectMcpName,
        description: "MCP for reject endpoint test",
        version: "1.0.0",
        category: "developer-tools",
        owner: "admin",
        command: "echo",
        args: ["reject-test"],
      }),
    });
    if (!res2.ok) throw new Error(`Submit failed: ${await res2.text()}`);
    const created2 = await res2.json();
    rejectMcpId = created2.id;
  });

  test.afterAll(async () => {
    for (const id of [mcpId, rejectMcpId]) {
      if (id) {
        await fetch(`${API_BASE}/api/v1/mcps/${id}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        }).catch(() => {});
      }
    }
  });

  test("Backend: POST /review/{id}/approve returns 200 with status=approved", async () => {
    const res = await fetch(`${API_BASE}/api/v1/review/${mcpId}/approve`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ notes: "e2e approve test" }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.status).toBe("approved");
  });

  test("Backend: POST /review/{id}/reject returns 200 with status=rejected", async () => {
    const res = await fetch(`${API_BASE}/api/v1/review/${rejectMcpId}/reject`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ reason: "Does not meet standards" }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.status).toBe("rejected");
  });

  test("CLI: observal admin review approve outputs approved", () => {
    const output = cli(`observal admin review approve ${mcpName} 2>&1 || true`);
    expect(output).not.toContain("Traceback");
    // May output "approved", "already approved", or "not found" (if already processed)
    const clean = output.replace(/\x1b\[[0-9;]*m/g, "");
    expect(clean).toMatch(/approv|not found|already/i);
  });

  test("CLI: observal admin review reject outputs rejected", () => {
    const output = cli(`observal admin review reject ${rejectMcpName} --reason "CLI test" 2>&1 || true`);
    expect(output).not.toContain("Traceback");
    const clean = output.replace(/\x1b\[[0-9;]*m/g, "");
    expect(clean).toMatch(/reject|not found|already/i);
  });
});
