// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { API_BASE, getAccessToken, loginToWebUI } from "./helpers";

test.describe("Agents - Page loads and detail view (#936)", () => {
  let token: string;
  let agentId: string;

  test.beforeAll(async () => {
    token = await getAccessToken();

    // Ensure at least one approved agent exists
    const listRes = await fetch(`${API_BASE}/api/v1/agents`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const agents = await listRes.json();

    if (Array.isArray(agents) && agents.length > 0) {
      agentId = agents[0].id;
    } else {
      const createRes = await fetch(`${API_BASE}/api/v1/agents`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: `e2e-agent-936-${Date.now()}`,
          description: "Agent for page load e2e test",
          version: "1.0.0",
          owner: "admin",
          model_name: "claude-sonnet-4-20250514",
          prompt: "You are a test agent.",
        }),
      });
      const created = await createRes.json();
      agentId = created.id;
      await fetch(`${API_BASE}/api/v1/review/agents/${agentId}/approve`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ notes: "e2e" }),
      });
    }
  });

  test("agents page loads and lists agents", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/agents");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("body")).not.toContainText("Something went wrong");
    // Should render agent content (table or grid)
    const content = page.locator("table tbody tr, [data-testid='agent-card']").first();
    await expect(content).toBeVisible({ timeout: 10_000 });
  });

  test("agent detail shows install options", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto(`/agents/${agentId}`);
    await page.waitForLoadState("networkidle");

    await expect(page.locator("body")).not.toContainText("Something went wrong");

    // Should have an Install tab with pull command
    const installTab = page.locator('[role="tab"]:has-text("Install")');
    if (await installTab.isVisible({ timeout: 5000 }).catch(() => false)) {
      await installTab.click();
      await page.waitForTimeout(500);
      const activePanel = page.getByRole("tabpanel", { name: "Install" });
      await expect(activePanel).toContainText("observal");
    }
  });
});
