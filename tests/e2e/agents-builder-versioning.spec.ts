// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { API_BASE, getAccessToken, loginToWebUI } from "./helpers";

test.describe("Agents - Builder and versioning (#938)", () => {
  test.describe.configure({ mode: "serial" });

  let token: string;
  let agentId: string;
  const agentName = `e2e-builder-${Date.now()}`;

  test.beforeAll(async () => {
    token = await getAccessToken();
  });

  test.afterAll(async () => {
    if (agentId) {
      await fetch(`${API_BASE}/api/v1/agents/${agentId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {});
    }
  });

  test("Playwright: agent builder page loads", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/agents/builder");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("body")).not.toContainText("Something went wrong");
    // Builder should render form elements
    await expect(page.locator("input, textarea").first()).toBeVisible({ timeout: 10_000 });
  });

  test("Backend: create agent, publish new version, version is pending", async () => {
    // Create agent
    const createRes = await fetch(`${API_BASE}/api/v1/agents`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: agentName,
        version: "1.0.0",
        description: "Builder versioning test",
        owner: "admin",
        model_name: "claude-sonnet-4-20250514",
        prompt: "You are a test agent.",
      }),
    });
    expect(createRes.status).toBe(200);
    const agent = await createRes.json();
    agentId = agent.id;

    // Approve v1
    await fetch(`${API_BASE}/api/v1/review/agents/${agentId}/approve`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ notes: "e2e" }),
    });

    // Publish v2 via agent versions endpoint
    const versionRes = await fetch(`${API_BASE}/api/v1/agents/${agentId}/versions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        version: "2.0.0",
        description: "Version 2",
        changelog: "New features",
        model_name: "claude-sonnet-4-20250514",
        prompt: "You are a test agent v2.",
      }),
    });
    // May be 200 or 201
    expect(versionRes.status).toBeLessThan(300);
    const ver = await versionRes.json();
    expect(ver.status).toBe("pending");
  });

  test("Backend: archive agent - disappears from list", async () => {
    const archiveRes = await fetch(`${API_BASE}/api/v1/agents/${agentId}/archive`, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    });
    expect(archiveRes.status).toBe(200);

    // Should not appear in main list
    const listRes = await fetch(`${API_BASE}/api/v1/agents`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const agents = await listRes.json();
    const found = agents.find((a: { id: string }) => a.id === agentId);
    expect(found).toBeFalsy();
  });

  test("Backend: unarchive agent - reappears in list", async () => {
    const unarchiveRes = await fetch(`${API_BASE}/api/v1/agents/${agentId}/unarchive`, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    });
    expect(unarchiveRes.status).toBe(200);

    const listRes = await fetch(`${API_BASE}/api/v1/agents`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const agents = await listRes.json();
    const found = agents.find((a: { id: string }) => a.id === agentId);
    expect(found).toBeTruthy();
  });
});
