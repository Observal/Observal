import { test, expect, Page } from "@playwright/test";
import { API_BASE } from "./helpers";

/**
 * Real SSO integration tests using Microsoft Entra ID.
 *
 * Prerequisites:
 *   - API running on localhost:8000 with OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET,
 *     OAUTH_SERVER_METADATA_URL configured for a Microsoft Entra ID tenant
 *   - Frontend running on localhost:3000
 *   - FRONTEND_URL=http://localhost:3000 in the API environment
 *   - Redis running (for OAuth code exchange)
 *
 * These tests are skipped automatically if SSO is not configured.
 */

const SSO_EMAIL =
  process.env.SSO_TEST_EMAIL ?? "hari-srinivasan@tx131.onmicrosoft.com";
const SSO_PASSWORD = process.env.SSO_TEST_PASSWORD ?? "TestObserval@2026!";

/** Check if SSO is enabled on the running API.
 *  Tries the public config endpoint first, falls back to probing
 *  the OAuth login endpoint (302 redirect means OAuth is configured). */
async function isSsoEnabled(): Promise<boolean> {
  try {
    // Preferred: check the public config endpoint
    const configRes = await fetch(`${API_BASE}/api/v1/config/public`);
    if (configRes.ok) {
      const config = await configRes.json();
      return config.sso_enabled === true;
    }
  } catch {
    // Config endpoint not available
  }

  try {
    // Fallback: probe the OAuth login endpoint (redirect = configured)
    const oauthRes = await fetch(`${API_BASE}/api/v1/auth/oauth/login`, {
      redirect: "manual",
    });
    return oauthRes.status === 302;
  } catch {
    return false;
  }
}

/** New password to use if Microsoft forces a password update during login. */
const SSO_NEW_PASSWORD = process.env.SSO_TEST_NEW_PASSWORD ?? SSO_PASSWORD;

/** Fill out the Microsoft Entra ID login form.
 *  Handles: email → password → optional password update → optional consent
 *  → optional "Stay signed in?" prompt. */
async function completeMicrosoftLogin(page: Page) {
  // Microsoft login page — wait for the email input
  await page.waitForURL(/login\.microsoftonline\.com/, { timeout: 15_000 });

  // Enter email
  const emailInput = page.locator('input[type="email"]');
  await emailInput.waitFor({ state: "visible", timeout: 10_000 });
  await emailInput.fill(SSO_EMAIL);
  await page.locator('input[type="submit"][value="Next"]').click();

  // Enter password
  const passwordInput = page.locator('input[type="password"]');
  await passwordInput.waitFor({ state: "visible", timeout: 10_000 });
  await passwordInput.fill(SSO_PASSWORD);
  await page.locator('input[type="submit"][value="Sign in"]').click();

  // Handle "Update your password" prompt if it appears (first sign-in or expired)
  try {
    const updateHeading = page.locator('text="Update your password"');
    await updateHeading.waitFor({ state: "visible", timeout: 5_000 });
    // Fill current + new + confirm
    await page
      .locator('input[placeholder="Current password"]')
      .fill(SSO_PASSWORD);
    await page
      .locator('input[placeholder="New password"]')
      .fill(SSO_NEW_PASSWORD);
    await page
      .locator('input[placeholder="Confirm password"]')
      .fill(SSO_NEW_PASSWORD);
    await page.locator('input[type="submit"][value="Sign in"]').click();
  } catch {
    // No password update needed — continue
  }

  // Handle consent prompt if it appears (first-time app authorization)
  try {
    const acceptButton = page.locator(
      'input[type="submit"][value="Accept"], button:has-text("Accept")',
    );
    await acceptButton.first().waitFor({ state: "visible", timeout: 5_000 });
    await acceptButton.first().click();
  } catch {
    // No consent prompt — continue
  }

  // Handle "Stay signed in?" prompt if it appears
  try {
    const staySignedIn = page.locator(
      'input[type="submit"][value="Yes"], input[type="button"][value="No"]',
    );
    await staySignedIn.first().waitFor({ state: "visible", timeout: 5_000 });
    // Click "No" to avoid persistent cookies that affect other tests
    const noButton = page.locator('input[type="button"][value="No"]');
    if (await noButton.isVisible()) {
      await noButton.click();
    } else {
      await staySignedIn.first().click();
    }
  } catch {
    // No "Stay signed in?" prompt — continue
  }
}

test.describe("SSO Login Flow", () => {
  test.beforeEach(async () => {
    const enabled = await isSsoEnabled();
    test.skip(!enabled, "SSO is not configured — skipping SSO tests");
  });

  test("SSO button is visible on login page when SSO is enabled", async ({
    page,
  }) => {
    await page.goto("/login");
    const ssoButton = page.locator('button:has-text("Sign in with SSO")');
    await expect(ssoButton).toBeVisible({ timeout: 10_000 });
  });

  test("full SSO login flow authenticates user and redirects to home", async ({
    page,
  }) => {
    // Extend timeout for the full OAuth round-trip
    test.setTimeout(90_000);

    // Navigate to login page
    await page.goto("/login");

    // Click SSO button
    const ssoButton = page.locator('button:has-text("Sign in with SSO")');
    await expect(ssoButton).toBeVisible({ timeout: 10_000 });
    await ssoButton.click();

    // Complete Microsoft login flow
    await completeMicrosoftLogin(page);

    // After SSO callback, we should land back on our app
    await page.waitForURL(
      (url) => url.origin === "http://localhost:3000" && url.pathname !== "/login",
      { timeout: 30_000 },
    );

    // Verify authentication state
    const role = await page.evaluate(() =>
      localStorage.getItem("observal_user_role"),
    );
    expect(role).toBeTruthy();

    const apiKey = await page.evaluate(() =>
      localStorage.getItem("observal_api_key"),
    );
    expect(apiKey).toBeTruthy();
  });

  test("SSO user can access authenticated endpoints after login", async ({
    page,
  }) => {
    test.setTimeout(90_000);

    await page.goto("/login");
    const ssoButton = page.locator('button:has-text("Sign in with SSO")');
    await ssoButton.click();

    await completeMicrosoftLogin(page);

    // Wait for redirect back to the app
    await page.waitForURL(
      (url) => url.origin === "http://localhost:3000" && url.pathname !== "/login",
      { timeout: 30_000 },
    );

    // Verify the whoami endpoint works with the stored credentials
    const apiKey = await page.evaluate(() =>
      localStorage.getItem("observal_api_key"),
    );
    expect(apiKey).toBeTruthy();

    const whoami = await page.evaluate(async (key) => {
      const res = await fetch("/api/v1/auth/whoami", {
        headers: { "Authorization": `Bearer ${key!}` },
      });
      return res.json();
    }, apiKey);

    expect(whoami.email).toBe(SSO_EMAIL);
    expect(whoami.role).toBeTruthy();
  });
});

test.describe("Enterprise Mode Login Page", () => {
  test("enterprise mode hides password form and shows only SSO button", async ({
    page,
  }) => {
    // Mock the config endpoint BEFORE navigation and wait for it to resolve
    let configFetched = false;
    await page.route("**/api/v1/config/public", (route) => {
      configFetched = true;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          deployment_mode: "enterprise",
          sso_enabled: true,
          saml_enabled: false,
        }),
      });
    });

    await page.goto("/login");

    // Wait for the config response to be processed by React by waiting for the
    // SSO button to appear — this confirms the deployment config has loaded
    const ssoButton = page.locator('button:has-text("Sign in with SSO")');
    await expect(ssoButton).toBeVisible({ timeout: 10_000 });

    // In enterprise mode, the email/password form is conditionally not rendered.
    // Wait for the email input to be detached from the DOM (not just hidden).
    await expect(page.locator('input[id="email"]')).toHaveCount(0, {
      timeout: 5_000,
    });
    await expect(page.locator('input[id="password"]')).toHaveCount(0);

    // Registration, forgot password, API key links should not be rendered
    await expect(
      page.locator('button:has-text("Don\'t have an account")'),
    ).toHaveCount(0);
    await expect(
      page.locator('button:has-text("Forgot password")'),
    ).toHaveCount(0);
    await expect(
      page.locator('button:has-text("Sign in with API key")'),
    ).toHaveCount(0);
  });

  test("local mode shows full login UI with SSO button when enabled", async ({
    page,
  }) => {
    await page.route("**/api/v1/config/public", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          deployment_mode: "local",
          sso_enabled: true,
          saml_enabled: false,
        }),
      }),
    );

    await page.goto("/login");

    // Wait for config to load — SSO button confirms it
    const ssoButton = page.locator('button:has-text("Sign in with SSO")');
    await expect(ssoButton).toBeVisible({ timeout: 10_000 });

    // Email and password should be visible in local mode
    await expect(page.locator('input[id="email"]')).toBeVisible();
    await expect(page.locator('input[id="password"]')).toBeVisible();

    // Registration link should be visible
    await expect(
      page.locator('button:has-text("Don\'t have an account")'),
    ).toBeVisible();
  });

  test("local mode without SSO shows only password login", async ({
    page,
  }) => {
    await page.route("**/api/v1/config/public", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          deployment_mode: "local",
          sso_enabled: false,
          saml_enabled: false,
        }),
      }),
    );

    await page.goto("/login");

    // Email and password should be visible
    await expect(page.locator('input[id="email"]')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.locator('input[id="password"]')).toBeVisible();

    // SSO button should NOT be in the DOM when sso_enabled is false
    // and deployment_mode is "local"
    await expect(
      page.locator('button:has-text("Sign in with SSO")'),
    ).toHaveCount(0, { timeout: 5_000 });
  });
});
