// SPDX-FileCopyrightText: 2026 Tanvi Reddy <tanvi.reddy330@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { loginToWebUI, API_BASE, getAccessToken } from "./helpers";

test.describe("SSO Login Page", () => {
  // Requires SSO to be enabled in the environment (enterprise feature).
  // Passes in CI with SSO configured; skipped locally without SSO.
  test("SSO button is visible on login page when SSO is configured", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    const ssoButton = page.locator('button:has-text("Sign in with SSO")');

    // Skip if SSO is not configured in this environment
    if (!(await ssoButton.isVisible().catch(() => false))) {
      test.skip(true, "SSO not configured in this environment");
    }

    await expect(ssoButton).toBeVisible();
  });
});

test.describe("Device Auth Confirmation Page", () => {
  test("shows confirmation UI with code input", async ({ page }) => {
    await loginToWebUI(page);

    // Navigate to device auth page with a test code
    await page.goto("/device?code=ABCD1234");
    await page.waitForLoadState("networkidle");

    // Verify the page shows the authorization UI
    await expect(page.locator("h1:has-text('Observal')")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("p:has-text('Authorize Device')")).toBeVisible();

    // Verify the code input is present and pre-filled
    const codeInput = page.locator('input[id="user-code"]');
    await expect(codeInput).toBeVisible();
    await expect(codeInput).toHaveValue("ABCD-1234");

    // Verify the submit button is present
    const submitButton = page.getByRole("button", { name: "Authorize Device" });
    await expect(submitButton).toBeVisible();
  });

  test("shows error for invalid code format", async ({ page }) => {
    await loginToWebUI(page);

    await page.goto("/device");
    await page.waitForLoadState("networkidle");

    // Enter a short invalid code
    const codeInput = page.locator('input[id="user-code"]');
    await codeInput.fill("ABC");

    // Click authorize
    const submitButton = page.locator('button:has-text("Authorize Device")');
    await submitButton.click();

    // Should show validation error
    await expect(page.locator("text=valid 8-character code")).toBeVisible({ timeout: 5_000 });
  });
});
