// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { API_BASE, getAccessToken } from "./helpers";

test.describe("Review - Version diff and edit lock (#944)", () => {
  test.describe.configure({ mode: "serial" });

  let token: string;
  let mcpId: string;

  test.beforeAll(async () => {
    token = await getAccessToken();

    // Create a pending MCP
    const res = await fetch(`${API_BASE}/api/v1/mcps/submit`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: `e2e-editlock-${Date.now()}`,
        description: "MCP for edit lock test",
        version: "1.0.0",
        category: "developer-tools",
        owner: "admin",
        command: "echo",
        args: ["lock-test"],
      }),
    });
    if (!res.ok) throw new Error(`Submit failed: ${await res.text()}`);
    const created = await res.json();
    mcpId = created.id;
  });

  test.afterAll(async () => {
    if (mcpId) {
      // Cancel any lingering edit lock
      await fetch(`${API_BASE}/api/v1/mcps/${mcpId}/cancel-edit`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {});
      await fetch(`${API_BASE}/api/v1/mcps/${mcpId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {});
    }
  });

  test("Backend: edit lock blocks review with 409", async () => {
    // Acquire edit lock
    const lockRes = await fetch(`${API_BASE}/api/v1/mcps/${mcpId}/start-edit`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(lockRes.status).toBe(200);

    // Try to approve — should get 409
    const approveRes = await fetch(`${API_BASE}/api/v1/review/${mcpId}/approve`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ notes: "should fail" }),
    });
    expect(approveRes.status).toBe(409);
    const body = await approveRes.json();
    expect(body.detail).toContain("editing");
  });

  test("Backend: edit lock releases on cancel, reviewer can approve", async () => {
    // Release the lock
    const cancelRes = await fetch(`${API_BASE}/api/v1/mcps/${mcpId}/cancel-edit`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(cancelRes.status).toBe(200);

    // Now approve should succeed
    const approveRes = await fetch(`${API_BASE}/api/v1/review/${mcpId}/approve`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ notes: "e2e after lock release" }),
    });
    expect(approveRes.status).toBe(200);
    const body = await approveRes.json();
    expect(body.status).toBe("approved");
  });
});
