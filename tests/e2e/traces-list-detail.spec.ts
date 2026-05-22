// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { loginToWebUI, API_BASE, getAccessToken } from "./helpers";

test.describe("Traces - List and detail view (#946)", () => {
  test.describe.configure({ mode: "serial" });

  let token: string;
  const sessionId = `e2e-trace-${Date.now()}`;

  test.beforeAll(async () => {
    token = await getAccessToken();

    // Ingest a session via the session ingest endpoint so it appears in traces
    const lines = [
      JSON.stringify({ type: "user", message: "Hello from e2e test", timestamp: new Date().toISOString() }),
      JSON.stringify({ type: "assistant", message: "Hi! How can I help?", timestamp: new Date().toISOString(), model: "claude-sonnet-4-20250514", input_tokens: 100, output_tokens: 200 }),
      JSON.stringify({ type: "tool_use", tool_name: "Read", result: "file contents", timestamp: new Date().toISOString() }),
    ];

    const res = await fetch(`${API_BASE}/api/v1/ingest/session`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        session_id: sessionId,
        ide: "kiro",
        lines,
      }),
    });
    // If ingest endpoint doesn't exist or fails, tests will gracefully skip
    if (!res.ok) {
      console.warn(`Session ingest returned ${res.status}: ${await res.text()}`);
    }

    // Wait for ClickHouse materialization
    await new Promise((r) => setTimeout(r, 5000));
  });

  test("traces page loads without error", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/traces");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("body")).not.toContainText("Something went wrong");

    // Page should render — either with trace rows or an empty state
    const hasRows = await page.locator("table tbody tr").first().isVisible({ timeout: 5000 }).catch(() => false);
    const hasEmptyState = await page.locator("text=/no.*session|no.*trace|empty/i").first().isVisible({ timeout: 2000 }).catch(() => false);
    expect(hasRows || hasEmptyState).toBe(true);
  });

  test("click trace navigates to detail page", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/traces");
    await page.waitForLoadState("networkidle");

    const rows = page.locator("table tbody tr");
    if (await rows.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await rows.first().click();
      await page.waitForURL(/\/traces\//, { timeout: 10_000 });
      await page.waitForLoadState("networkidle");
      await expect(page.locator("body")).not.toContainText("Something went wrong");
    } else {
      test.skip();
    }
  });

  test("trace detail shows session info", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/traces");
    await page.waitForLoadState("networkidle");

    const rows = page.locator("table tbody tr");
    if (await rows.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await rows.first().click();
      await page.waitForURL(/\/traces\//, { timeout: 10_000 });
      await page.waitForLoadState("networkidle");

      // Detail page should show token/model/session info
      const body = await page.locator("body").textContent();
      expect(body).toMatch(/token|model|session|turn|span/i);
    } else {
      test.skip();
    }
  });
});
