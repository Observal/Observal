// SPDX-FileCopyrightText: 2026 Tanvi Reddy <tanvi.reddy330@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";

const EMAIL = process.env.DEMO_ADMIN_EMAIL ?? "admin@demo.example";
const PASSWORD = process.env.DEMO_ADMIN_PASSWORD ?? "admin-changeme";

/**
 * P0: Login with wrong password — error shown
 * Issue #927
 */
test("login with wrong password shows error and stays on /login", async ({ page }) => {
  await page.goto("/login");
  await page.fill("#email", EMAIL);
  await page.fill("#password", "wrong-password-123");
  await page.click('button[type="submit"]');

  // Should stay on /login
  await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });

  // Error message should appear
  await expect(page.locator("span").filter({ hasText: /invalid|incorrect|wrong|failed|credentials|password/i }).first()).toBeVisible({ timeout: 10_000 });
});

/**
 * P0: Logout — redirected to /login, protected pages inaccessible
 * Issue #927
 */
test("logout redirects to /login and blocks protected pages", async ({ page }) => {
  // Login first
  await page.goto("/login");
  await page.fill("#email", EMAIL);
  await page.fill("#password", PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 15_000 });

  // Open user menu and click Sign out
  await page.locator("button").filter({ hasText: /demo admin|admin/i }).first().click();
  await page.locator("text=Sign out").click();

  // Should redirect to /login
  await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });

  // Protected page should redirect back to /login
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
});
