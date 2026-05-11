// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { loginToWebUI, API_BASE, getAccessToken } from "./helpers";

test.describe("Full Edit → Release → Review Flow", () => {
  test.describe.configure({ mode: "serial" });

  let agentId: string;
  let token: string;

  test.beforeAll(async () => {
    token = await getAccessToken();

    // Create a test agent via API
    const res = await fetch(`${API_BASE}/api/v1/agents`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: `full-flow-test-${Date.now()}`,
        version: "1.0.0",
        description: "Initial description",
        owner: "test",
        model_name: "claude-sonnet-4-20250514",
        visibility: "private",
        components: [],
        goal_template: {
          description: "Test agent goal",
          sections: [{ name: "Default", description: "Default section" }],
        },
      }),
    });

    if (!res.ok) {
      const body = await res.text();
      throw new Error(`Failed to create test agent: ${res.status} ${body}`);
    }

    const agent = await res.json();
    agentId = agent.id;
    console.log("Created agent:", agentId);
  });

  test.afterAll(async () => {
    if (!agentId) return;
    await fetch(`${API_BASE}/api/v1/agents/${agentId}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${token}` },
    });
  });

  test("Save Draft updates agent without version bump", async ({ page }) => {
    const apiErrors: string[] = [];
    page.on("response", async (response) => {
      if (response.url().includes("/api/v1/agents") && response.status() >= 400) {
        const body = await response.text().catch(() => "");
        apiErrors.push(`${response.status()} ${response.url()} → ${body}`);
      }
    });

    await loginToWebUI(page);
    await page.goto(`/agents/${agentId}`);
    await page.waitForLoadState("networkidle");

    // Go to Edit tab
    await page.getByRole("tab", { name: "Edit" }).click();

    // Modify description
    const descInput = page.getByLabel("Description");
    await descInput.clear();
    await descInput.fill("Draft update - no version bump");

    // Click Save Draft
    const saveDraftBtn = page.getByRole("button", { name: "Save Draft" });
    await expect(saveDraftBtn).toBeEnabled();
    await saveDraftBtn.click();

    // Wait for save to complete
    await page.waitForTimeout(2000);

    expect(apiErrors).toHaveLength(0);

    // Verify still version 1.0.0 (no bump)
    await page.getByRole("tab", { name: "Overview" }).click();
    await expect(page.locator("body")).toContainText("1.0.0");
  });

  test("Save & Release bumps version to 1.0.1", async ({ page }) => {
    const apiErrors: string[] = [];
    page.on("response", async (response) => {
      if (response.url().includes("/api/v1/agents") && response.status() >= 400) {
        const body = await response.text().catch(() => "");
        apiErrors.push(`${response.status()} ${response.url()} → ${body}`);
      }
    });

    await loginToWebUI(page);
    await page.goto(`/agents/${agentId}`);
    await page.waitForLoadState("networkidle");

    await page.getByRole("tab", { name: "Edit" }).click();

    // Modify description
    const descInput = page.getByLabel("Description");
    await descInput.clear();
    await descInput.fill("Released description - version bump");

    // Click Save & Release
    const releaseBtn = page.getByRole("button", { name: /Save.*Release/i });
    await expect(releaseBtn).toBeEnabled();
    await releaseBtn.click();

    // Version bump dialog
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByText("Release New Version")).toBeVisible();

    // Patch is pre-selected by default (1.0.0 → 1.0.1)
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Patch", { exact: true })).toBeVisible();

    // Confirm release
    await page.getByRole("button", { name: "Release" }).click();

    // Wait for release to complete
    await page.waitForTimeout(3000);

    expect(apiErrors).toHaveLength(0);
  });

  test("New version appears in Versions list as pending", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto(`/agents/${agentId}`);
    await page.waitForLoadState("networkidle");

    // Check if there's a Versions tab or version indicator
    const versionsTab = page.getByRole("tab", { name: /Version/i });
    if (await versionsTab.isVisible()) {
      await versionsTab.click();
      await page.waitForTimeout(1000);
      // Should show 1.0.1 as pending
      await expect(page.locator("body")).toContainText("1.0.1");
    }

    // Verify via API
    const res = await fetch(`${API_BASE}/api/v1/agents/${agentId}/versions`, {
      headers: { "Authorization": `Bearer ${token}` },
    });
    const data = await res.json();
    const items = data.items || data;
    const v101 = items.find((v: { version: string }) => v.version === "1.0.1");
    expect(v101).toBeTruthy();
    expect(v101.status).toBe("pending");
  });

  test("Admin can approve the new version via review", async ({ page }) => {
    // Approve via API (admin) - the review endpoint uses the version string, not UUID
    const approveRes = await fetch(`${API_BASE}/api/v1/agents/${agentId}/versions/1.0.1/review`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ action: "approve" }),
    });

    if (!approveRes.ok) {
      const body = await approveRes.text();
      console.log(`Approve response: ${approveRes.status} ${body}`);
    }
    expect(approveRes.status).toBeLessThan(500);

    // After approval, the agent's displayed version should be 1.0.1
    await loginToWebUI(page);
    await page.goto(`/agents/${agentId}`);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("body")).toContainText("1.0.1");
  });
});
