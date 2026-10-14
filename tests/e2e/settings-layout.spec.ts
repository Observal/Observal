// SPDX-License-Identifier: Apache-2.0

import { expect, test } from "@playwright/test";
import { API_BASE } from "./helpers";

let accessToken: string;

test.beforeAll(async () => {
  const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: process.env.DEMO_SUPER_ADMIN_EMAIL ?? "super@demo.example",
      password: process.env.DEMO_SUPER_ADMIN_PASSWORD ?? "super-changeme",
    }),
  });
  if (!response.ok) throw new Error(`Super-admin login failed: ${response.status}`);
  const body = await response.json();
  if (!body.access_token) throw new Error("Super-admin login returned no access token");
  accessToken = body.access_token;
});

for (const [name, width, height] of [["desktop", 1440, 900], ["mobile", 390, 844]] as const) {
  test(`settings directory and section navigation on ${name}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await page.evaluate((token) => {
      sessionStorage.setItem("observal_access_token", token);
      localStorage.setItem("observal_user_role", "super_admin");
    }, accessToken);
    await page.goto("/settings");

    const search = page.getByRole("searchbox", { name: "Find a setting" });
    await expect(page.getByRole("button", { name: /Identity & access/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Review policy/ })).toBeVisible();
    await expect(search).toHaveValue("");
    await expect(search).toHaveAttribute("readonly", "");
    await search.click();
    await search.fill("retention");
    await page.getByRole("region", { name: "Matching settings" }).getByRole("button", { name: /Data retention/i }).click();
    await expect(page.locator("#settings-retention")).toBeVisible();
    await expect(page.locator("#settings-retention")).toHaveCSS("border-top-width", "1px");

    await page.getByRole("button", { name: "All settings" }).click();
    await page.getByRole("button", { name: /Identity & access/ }).click();
    await expect(page.locator("#settings-appearance")).toBeVisible();
    await expect(page.locator("#settings-access")).toBeVisible();
    await expect(page.locator("#settings-experimental")).toBeVisible();
    await expect(page.getByRole("switch", { name: "Enable experimental review checks" })).toBeVisible();
    await expect(page.getByRole("switch", { name: "Show the Leaderboard" })).toBeVisible();
    await expect(page.locator("#settings-appearance")).toHaveCSS("border-top-width", "1px");

    await page.getByRole("button", { name: "All settings" }).click();
    await page.getByRole("button", { name: /Security & deployment/ }).click();
    await expect(page.locator("#settings-security")).toBeVisible();
    expect(await page.locator("button button").count()).toBe(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  });
}
