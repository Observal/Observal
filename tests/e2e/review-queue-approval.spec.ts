// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { API_BASE, getAccessToken, loginToWebUI } from "./helpers";

test.describe("Review - Queue and approval workflow (#942)", () => {
  test.describe.configure({ mode: "serial" });

  let token: string;
  let mcpId: string;
  const mcpName = `e2e-review-mcp-${Date.now()}`;

  test.beforeAll(async () => {
    token = await getAccessToken();

    // Create a pending MCP so the review queue has something
    const res = await fetch(`${API_BASE}/api/v1/mcps/submit`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: mcpName,
        description: "MCP for review queue e2e test",
        version: "1.0.0",
        category: "developer-tools",
        owner: "admin",
        command: "echo",
        args: ["test"],
      }),
    });
    if (!res.ok) throw new Error(`MCP submit failed: ${await res.text()}`);
    const created = await res.json();
    mcpId = created.id;
  });

  test.afterAll(async () => {
    if (mcpId) {
      await fetch(`${API_BASE}/api/v1/mcps/${mcpId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {});
    }
  });

  test("review queue shows pending items", async ({ page }) => {
    // Create a fresh pending MCP for this test
    const freshName = `e2e-queue-${Date.now()}`;
    await fetch(`${API_BASE}/api/v1/mcps/submit`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: freshName,
        description: "Fresh pending MCP for queue test",
        version: "1.0.0",
        category: "developer-tools",
        owner: "admin",
        command: "echo",
        args: ["queue-test"],
      }),
    });

    await loginToWebUI(page);
    await page.goto("/review");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("body")).not.toContainText("Something went wrong");

    // Switch to Components tab (MCPs are components, not agents)
    const componentsTab = page.locator('[role="tab"]:has-text("Components")');
    if (await componentsTab.isVisible({ timeout: 5000 }).catch(() => false)) {
      await componentsTab.click();
      await page.waitForLoadState("networkidle");
    }

    // Should show pending items (at least the one we just created)
    await expect(page.locator("body")).toContainText(freshName, { timeout: 10_000 });
  });

  test("approve component via UI", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/review");
    await page.waitForLoadState("networkidle");

    // Switch to Components tab
    const componentsTab = page.locator('[role="tab"]:has-text("Components")');
    if (await componentsTab.isVisible({ timeout: 5000 }).catch(() => false)) {
      await componentsTab.click();
      await page.waitForLoadState("networkidle");
    }

    // Click the pending item to open detail
    const item = page.locator(`text=${mcpName}`).first();
    await expect(item).toBeVisible({ timeout: 10_000 });
    await item.click();
    await page.waitForTimeout(500);

    // Click approve button
    const approveBtn = page.getByRole("button", { name: /approve/i }).first();
    if (await approveBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await approveBtn.click();
      await page.waitForTimeout(1000);
      await expect(page.locator("body")).toContainText(/approved|success/i);
    }
  });

  test("reject component via UI with reason", async ({ page }) => {
    // Create another pending MCP to reject
    const rejectName = `e2e-reject-mcp-${Date.now()}`;
    const res = await fetch(`${API_BASE}/api/v1/mcps/submit`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: rejectName,
        description: "MCP to reject",
        version: "1.0.0",
        category: "developer-tools",
        owner: "admin",
        command: "echo",
        args: ["reject-test"],
      }),
    });
    const created = await res.json();

    await loginToWebUI(page);
    await page.goto("/review");
    await page.waitForLoadState("networkidle");

    // Switch to Components tab
    const componentsTab = page.locator('[role="tab"]:has-text("Components")');
    if (await componentsTab.isVisible({ timeout: 5000 }).catch(() => false)) {
      await componentsTab.click();
      await page.waitForLoadState("networkidle");
    }

    const item = page.locator(`text=${rejectName}`).first();
    await expect(item).toBeVisible({ timeout: 10_000 });
    await item.click();
    await page.waitForTimeout(500);

    // Click reject button
    const rejectBtn = page.getByRole("button", { name: /reject/i }).first();
    if (await rejectBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await rejectBtn.click();

      // Enter rejection reason if a dialog/input appears
      const reasonInput = page.locator('textarea, input[placeholder*="reason" i]').first();
      if (await reasonInput.isVisible({ timeout: 3000 }).catch(() => false)) {
        await reasonInput.fill("Does not meet quality standards");
        // Confirm rejection
        const confirmBtn = page.getByRole("button", { name: /reject|confirm/i }).last();
        await confirmBtn.click();
      }

      await page.waitForTimeout(1000);
      await expect(page.locator("body")).toContainText(/rejected|success/i);
    }

    // Cleanup
    await fetch(`${API_BASE}/api/v1/mcps/${created.id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => {});
  });
});
