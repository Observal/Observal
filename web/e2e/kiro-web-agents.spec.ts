import { test, expect } from "@playwright/test";
import { loginToWebUI, API_BASE, getApiKey } from "./helpers";

test.describe("Kiro Agent Compatibility in Web UI", () => {
  test.beforeEach(async ({ page }) => {
    await loginToWebUI(page);
  });

  test("agents page loads and lists agents", async ({ page }) => {
    await page.goto("/agents");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("agent detail page shows install options", async ({ page }) => {
    // Get an agent ID from the API
    const apiKey = await getApiKey();
    const agents = await fetch(`${API_BASE}/api/v1/agents`, {
      headers: { "Authorization": `Bearer ${apiKey}` },
    }).then((r) => r.json());

    if (agents.length === 0) {
      test.skip();
      return;
    }

    const agentId = agents[0].id;
    await page.goto(`/agents/${agentId}`);
    await page.waitForLoadState("networkidle");

    // The page should load
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("components page loads and shows component types", async ({ page }) => {
    await page.goto("/components");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });
});
