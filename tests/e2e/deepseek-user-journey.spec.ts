// SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
// SPDX-License-Identifier: Apache-2.0

/**
 * DeepSeek Harness integration - full user-journey screenshots.
 *
 * Walks the web UI the way a real user would (login -> dashboard -> traces ->
 * session detail -> agents -> registry -> admin) and captures one screenshot
 * per screen as PR evidence.
 *
 * Run: cd web && pnpm e2e --grep "DeepSeek User Journey"
 */
import { test, expect } from "@playwright/test";
import { loginToWebUI, getAccessToken, API_BASE } from "./helpers";

const SHOT_DIR = "../docs/img/deepseek";

/** The live headless session that invoked the pulled agent skill. */
const LIVE_SESSION_ID = process.env.DSH_LIVE_SESSION_ID ?? "";

async function settle(page: import("@playwright/test").Page, ms = 1500) {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(ms);
}

test.describe("DeepSeek User Journey", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("01 - login screen", async ({ page }) => {
    await page.goto("/login");
    await settle(page, 1200);
    await page.screenshot({ path: `${SHOT_DIR}/01-login.png`, fullPage: false });
    await expect(page.locator("body")).toBeVisible();
  });

  test("02 - dashboard after sign-in", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/dashboard");
    await settle(page, 2500);
    await page.screenshot({ path: `${SHOT_DIR}/02-dashboard.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("03 - traces filtered to the DeepSeek harness", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/traces");
    await settle(page, 2500);
    const search = page.getByPlaceholder(/days:7/);
    if (await search.count()) {
      await search.first().fill("platform:deepseek");
      await page.keyboard.press("Enter");
      await settle(page, 2500);
    }
    await page.screenshot({ path: `${SHOT_DIR}/03-traces-deepseek.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("04 - live session detail", async ({ page }) => {
    const token = await getAccessToken();
    // Prefer the live headless session; fall back to the newest DeepSeek session.
    let sessionId = LIVE_SESSION_ID;
    if (!sessionId) {
      const res = await fetch(`${API_BASE}/api/v1/sessions?limit=50`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const rows = (await res.json()) as Array<{ session_id: string; service_name?: string }>;
      sessionId = rows.find((r) => r.service_name === "deepseek")?.session_id ?? "";
    }
    expect(sessionId).not.toBe("");

    await loginToWebUI(page);
    await page.goto(`/traces/${sessionId}`);
    await settle(page, 3000);
    await page.screenshot({ path: `${SHOT_DIR}/04-live-session-detail.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("05 - agents registry", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/agents");
    await settle(page, 2500);
    await page.screenshot({ path: `${SHOT_DIR}/05-agents.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("06 - agent detail", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/agents/super/dsh-e2e-agent");
    await settle(page, 2500);
    await page.screenshot({ path: `${SHOT_DIR}/06-agent-detail.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("07 - components registry", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/components");
    await settle(page, 2500);
    await page.screenshot({ path: `${SHOT_DIR}/07-components.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("08 - discover", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/discover");
    await settle(page, 2500);
    await page.screenshot({ path: `${SHOT_DIR}/08-discover.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("09 - admin review queue", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/review");
    await settle(page, 2500);
    await page.screenshot({ path: `${SHOT_DIR}/09-admin-review.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("10 - admin users", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/users");
    await settle(page, 2500);
    await page.screenshot({ path: `${SHOT_DIR}/10-admin-users.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("11 - admin audit log", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/audit-log");
    await settle(page, 2500);
    await page.screenshot({ path: `${SHOT_DIR}/11-admin-audit-log.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("12 - admin diagnostics", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/diagnostics");
    await settle(page, 2500);
    await page.screenshot({ path: `${SHOT_DIR}/12-admin-diagnostics.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("13 - admin security events", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/security-events");
    await settle(page, 2500);
    await page.screenshot({ path: `${SHOT_DIR}/13-admin-security-events.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("14 - leaderboard", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/leaderboard");
    await settle(page, 2500);
    await page.screenshot({ path: `${SHOT_DIR}/14-leaderboard.png`, fullPage: false });
    await expect(page.locator("body")).not.toContainText("Something went wrong");
  });

  test("15 - DeepSeek install command for the agent", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/agents/super/dsh-e2e-agent");
    await settle(page, 2500);

    // A real user picks their harness from the Install card, which is
    // server-populated from /api/v1/config/harnesses.
    const trigger = page.getByRole("combobox").first();
    if (await trigger.count()) {
      await trigger.click();
    } else {
      await page.getByText("Cursor", { exact: true }).first().click();
    }
    await page.getByText("DeepSeek Harness", { exact: true }).last().click();
    await settle(page, 1200);

    await expect(page.locator("body")).toContainText("--harness deepseek");
    await page.screenshot({ path: `${SHOT_DIR}/15-agent-deepseek-install.png`, fullPage: false });
  });
});
