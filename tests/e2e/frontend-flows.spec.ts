// SPDX-FileCopyrightText: 2025 Observal Contributors
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { loginToWebUI, API_BASE, getAccessToken } from "./helpers";

/**
 * Frontend E2E tests — browser-level tests that drive the Next.js UI
 * and verify real user flows.
 */
test.describe("Frontend Flows", () => {
  // Use an existing approved agent for search/detail tests
  let agentName: string;

  test.beforeAll(async () => {
    const token = await getAccessToken();
    // Find an existing approved agent
    const res = await fetch(`${API_BASE}/api/v1/agents`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const agents = await res.json();
    if (Array.isArray(agents) && agents.length > 0) {
      agentName = agents[0].name;
    } else {
      // Create and approve one for fresh instances
      agentName = `e2e-agent-${Date.now()}`;
      await fetch(`${API_BASE}/api/v1/agents`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          name: agentName,
          description: "Agent for frontend e2e tests",
          version: "1.0.0",
          owner: "admin",
          model_name: "claude-sonnet-4-20250514"],
          },
        }),
      });
      await fetch(`${API_BASE}/api/v1/review/agents/${agentName}/approve`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
    }
  });

  /**
   * Flow 1: Login page → submit credentials → land on registry home
   */
  test("login and land on registry home", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator("h1")).toContainText("Observal");

    await page.fill("#email", "admin@demo.example");
    await page.fill("#password", "admin-changeme");
    await page.click('button[type="submit"]');

    // Should redirect to registry home
    await page.waitForURL("/", { timeout: 10_000 });
    await expect(page.locator("body")).toContainText("Agent Registry");
  });

  /**
   * Flow 2: Registry home → search for an agent → open agent detail page
   */
  test("search for agent and open detail", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/agents");
    await page.waitForLoadState("networkidle");

    // Use the search input on the agents page
    const searchInput = page.locator('input[placeholder*="Search"], input[type="search"]').first();
    await searchInput.fill(agentName);
    // Wait for results to filter (debounced)
    await page.waitForTimeout(500);

    // Click the agent in results
    const agentLink = page.locator(`a:has-text("${agentName}")`).first();
    await expect(agentLink).toBeVisible({ timeout: 10_000 });
    await agentLink.click();

    // Should land on agent detail page
    await page.waitForURL(/\/agents\//, { timeout: 10_000 });
    await expect(page.locator("body")).toContainText(agentName);
  });

  /**
   * Flow 3: Agent detail page → copy pull command → verify copy button works
   */
  test("copy pull command on agent detail", async ({ page, context }) => {
    await loginToWebUI(page);
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);

    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(`/agents/${agentName}`);
    await page.waitForLoadState("networkidle");

    // Click the "Install" tab to show the pull command
    const installTab = page.locator('[role="tab"]:has-text("Install")');
    await installTab.click();
    await page.waitForTimeout(300);

    // Click the copy button next to the install command in the main content area
    // The main tabpanel has the pull command with a copy button
    const copyBtn = page.locator('[role="tabpanel"] button[aria-label="Copy command"]').first();
    await expect(copyBtn).toBeVisible({ timeout: 5_000 });
    await copyBtn.click();

    // After clicking, a toast "Copied to clipboard" appears
    await expect(page.locator("text=Copied to clipboard")).toBeVisible({ timeout: 3_000 });

    // Verify clipboard contains the pull command
    const clipboardText = await page.evaluate(() => navigator.clipboard.readText());
    expect(clipboardText).toContain("observal agent pull");
    expect(clipboardText).toContain(agentName);
  });

  /**
   * Flow 4: Component browser → filter by type (MCP / skill / hook) → results update
   */
  test("component browser filter by type", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/components");
    await page.waitForLoadState("networkidle");

    // The component page has custom tab buttons for each type
    const mcpTab = page.locator('button:has-text("MCPs")');
    const skillsTab = page.locator('button:has-text("Skills")');
    const hooksTab = page.locator('button:has-text("Hooks")');

    await expect(mcpTab).toBeVisible();

    // MCPs tab should be active by default (has text-foreground class, not text-muted-foreground)
    await expect(mcpTab).toHaveClass(/text-foreground/);

    // Click Skills tab — should become active
    await skillsTab.click();
    await page.waitForLoadState("networkidle");
    await expect(skillsTab).toHaveClass(/text-foreground/);
    await expect(mcpTab).toHaveClass(/text-muted-foreground/);

    // Click Hooks tab
    await hooksTab.click();
    await page.waitForLoadState("networkidle");
    await expect(hooksTab).toHaveClass(/text-foreground/);
    await expect(skillsTab).toHaveClass(/text-muted-foreground/);
  });
});
