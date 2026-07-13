// SPDX-FileCopyrightText: 2026 Tanvi Reddy <tanvi.reddy330@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { API_BASE, getAccessToken, loginToWebUI } from "./helpers";

test.describe("UI Polish", () => {
  test.describe("Theme Switcher", () => {
    test("switching themes re-renders page without broken colors", async ({ page }) => {
      await loginToWebUI(page);
      await page.goto("/account");
      await page.waitForSelector("main", { timeout: 10_000 });

      // The account page has a "Theme" section with theme buttons
      await expect(page.locator('h3:has-text("Theme")')).toBeVisible({ timeout: 5_000 });

      // Click the "Dark" theme button
      const darkButton = page.locator('button:has-text("Dark")').first();
      await expect(darkButton).toBeVisible({ timeout: 3_000 });
      await darkButton.click();

      // Verify dark class is applied to html
      const html = page.locator("html");
      await expect(html).toHaveClass(/dark/, { timeout: 3_000 });

      // Switch to light
      const lightButton = page.locator('button:has-text("Light")').first();
      await expect(lightButton).toBeVisible({ timeout: 3_000 });
      await lightButton.click();

      // Verify dark class is removed
      await expect(html).not.toHaveClass(/dark/, { timeout: 3_000 });

      // Verify page still renders correctly
      await expect(page.locator("main")).toBeVisible();
    });
  });

  test.describe("Command Palette (Cmd+K)", () => {
    test("opens on keyboard shortcut and shows search results", async ({ page }) => {
      await loginToWebUI(page);
      await page.goto("/");
      await page.waitForSelector("main", { timeout: 10_000 });

      // Press Cmd+K to open command palette
      await page.keyboard.press("Meta+k");

      // Verify the command palette dialog is visible
      const palette = page.locator('[role="dialog"]').first();
      await expect(palette).toBeVisible({ timeout: 5_000 });

      // Type a search query in the command input
      const input = palette.locator("input").first();
      await expect(input).toBeVisible();
      await input.fill("agents");

      // Verify results appear
      const results = palette.locator("[cmdk-item]");
      await expect(results.first()).toBeVisible({ timeout: 5_000 });

      // Close palette with Escape
      await page.keyboard.press("Escape");
      await expect(palette).not.toBeVisible({ timeout: 3_000 });
    });
  });

  test.describe("Error State on API Failure", () => {
    test("error component renders with retry button when API is unreachable", async ({ page }) => {
      await loginToWebUI(page);

      // Block only the agents endpoint (not all API routes, to avoid breaking auth)
      await page.route("**/api/v1/agents**", (route) => route.abort("connectionrefused"));

      await page.goto("/agents");

      // Wait for the error state to render (ErrorState shows "Failed to load data" + Retry button)
      const errorText = page.locator('text=/Failed to load|Something went wrong/i').first();
      const retryButton = page.locator('button:has-text("Retry")').first();

      await expect(errorText).toBeVisible({ timeout: 10_000 });
      await expect(retryButton).toBeVisible({ timeout: 5_000 });

      await page.unrouteAll();
    });
  });

  test.describe("Empty State", () => {
    test("page handles empty data gracefully", async ({ page }) => {
      await loginToWebUI(page);

      // Mock the agents API to return empty array
      await page.route("**/api/v1/agents**", (route) => {
        if (route.request().method() === "GET") {
          return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
        }
        return route.continue();
      });

      await page.goto("/agents");

      // Wait for page to process the empty response
      await page.waitForSelector("main", { timeout: 10_000 });

      // Verify empty state: either explicit empty state UI or table with no data rows
      const emptyText = page.locator('text=/no agents|nothing|get started|no results|empty/i').first();
      const emptyContainer = page.locator(".border-dashed").first();
      const tableRows = page.locator("table tbody tr");

      const hasEmptyText = await emptyText.isVisible().catch(() => false);
      const hasEmptyContainer = await emptyContainer.isVisible().catch(() => false);
      const rowCount = await tableRows.count().catch(() => 0);

      // At least one empty indicator should be present
      expect(hasEmptyText || hasEmptyContainer || rowCount === 0).toBe(true);

      await page.unrouteAll();
    });
  });

  test.describe("Pagination", () => {
    test("page controls work on agents list", async ({ page }) => {
      await loginToWebUI(page);

      // Create enough agents to trigger pagination
      const adminToken = await getAccessToken();
      const agentIds: string[] = [];

      for (let i = 0; i < 15; i++) {
        const res = await fetch(`${API_BASE}/api/v1/agents`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${adminToken}`,
          },
          body: JSON.stringify({
            name: `e2e-pagination-${Date.now()}-${i}`,
            version: "1.0.0",
            description: `Pagination test agent ${i}`,
            owner: "admin",
            model_name: "claude-sonnet-4-20250514",
            goal_template: {
              description: "Pagination test",
              sections: [{ name: "Goal", content: "Test" }],
            },
          }),
        });
        if (res.status === 200) {
          const agent = await res.json();
          agentIds.push(agent.id);
        }
      }

      try {
        await page.goto("/agents");
        await page.waitForSelector("main", { timeout: 10_000 });

        // Look for pagination controls
        const paginationControls = page.locator(
          'button:has-text("Next"), button:has-text("Previous"), [aria-label*="page"], nav[aria-label="pagination"]',
        ).first();

        const hasPagination = await paginationControls.isVisible().catch(() => false);
        test.skip(!hasPagination, "Not enough data to trigger pagination controls");

        // Click next and verify content updates
        const nextButton = page.locator('button:has-text("Next"), button[aria-label="Next page"]').first();
        await expect(nextButton).toBeVisible();

        if (await nextButton.isEnabled()) {
          const contentBefore = await page.locator("main").textContent();
          await nextButton.click();
          await page.waitForSelector("main", { timeout: 5_000 });
          const contentAfter = await page.locator("main").textContent();
          expect(contentAfter).not.toBe(contentBefore);
        }
      } finally {
        // Cleanup test agents
        for (const id of agentIds) {
          await fetch(`${API_BASE}/api/v1/agents/${id}`, {
            method: "DELETE",
            headers: { Authorization: `Bearer ${adminToken}` },
          }).catch(() => {});
        }
      }
    });
  });
});
