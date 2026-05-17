// SPDX-FileCopyrightText: 2026 Tanvi Reddy <tanvi.reddy330@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect, BrowserContext } from "@playwright/test";
import { API_BASE, getAccessToken } from "./helpers";

const EMAIL = process.env.DEMO_ADMIN_EMAIL ?? "admin@demo.example";
const PASSWORD = process.env.DEMO_ADMIN_PASSWORD ?? "admin-changeme";

let sharedContext: BrowserContext;

test.beforeAll(async ({ browser }) => {
  sharedContext = await browser.newContext();
  const page = await sharedContext.newPage();
  await page.goto("/login");
  await page.fill("#email", EMAIL);
  await page.fill("#password", PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 15_000 });
  await page.close();
});

test.afterAll(async () => {
  await sharedContext?.close();
});

test.describe("Eval", () => {
  /**
   * P1: Eval page shows agent scores
   * Issue #953 — Table with scores renders
   */
  test("eval page renders agent cards or empty state", async () => {
    const page = await sharedContext.newPage();
    await page.goto("/eval");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("text=Agent Evaluations")).toBeVisible({ timeout: 10_000 });

    // Skeletons should clear
    await expect(page.locator(".animate-pulse").first()).not.toBeVisible({ timeout: 10_000 });

    // Either agent cards or empty state — never stuck loading
    const hasCards = await page.locator('a[href^="/eval/"]').count();
    const hasEmpty = await page.locator("text=No agents to evaluate").count();
    expect(hasCards + hasEmpty).toBeGreaterThan(0);

    await page.close();
  });

  /**
   * P1: Eval detail — dimension radar chart renders
   * Issue #953 — Dimension radar renders
   */
  test("eval detail page renders radar chart for an agent", async () => {
    const token = await getAccessToken();
    const res = await fetch(`${API_BASE}/api/v1/agents`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const agents = await res.json();
    const agent = Array.isArray(agents) && agents.length > 0 ? agents[0] : null;

    if (!agent) {
      test.skip(true, "No agents available");
      return;
    }

    const page = await sharedContext.newPage();
    await page.goto(`/eval/${agent.id}`);
    await page.waitForLoadState("networkidle");

    // Page should load without error
    await expect(page.locator("text=Eval").first()).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".animate-pulse").first()).not.toBeVisible({ timeout: 10_000 });

    // Radar SVG renders (has scores) or empty state (no evals yet) — never a crash
    const hasSvg = await page.locator("svg").count();
    const hasEmpty = await page.locator("text=No evaluations, text=No scorecards").count();
    expect(hasSvg + hasEmpty).toBeGreaterThan(0);

    await page.close();
  });
});
