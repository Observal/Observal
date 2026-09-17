// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { expect, test } from "@playwright/test";

import { API_BASE } from "./helpers";

/**
 * The Data Migration dialog is the only sanctioned way to move an instance.
 *
 * A telemetry-only move must stay available: it is how a DuckDB analytics
 * deployment carries session/audit history between environments without
 * touching registry rows. The scope a client picks also has to survive the
 * multipart upload, which is why this spec asserts the option set renders
 * before anything is started.
 */

async function loginAsSuperAdmin(page: import("@playwright/test").Page) {
  const email = process.env.DEMO_SUPER_ADMIN_EMAIL ?? "super@demo.example";
  const password = process.env.DEMO_SUPER_ADMIN_PASSWORD ?? "super-changeme";
  const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer e2e-admin-migration-${crypto.randomUUID()}`,
    },
    body: JSON.stringify({ email, password }),
  });
  const body = await response.json();
  if (!response.ok || !body.access_token) {
    throw new Error(`super admin login failed: status=${response.status}`);
  }

  await page.goto("/");
  await page.evaluate((token) => {
    sessionStorage.setItem("observal_access_token", token);
    localStorage.setItem("observal_user_role", "super_admin");
  }, body.access_token as string);
  await page.reload();
}

test.describe("data migration dialog", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsSuperAdmin(page);
    await page.goto("/settings");
  });

  test("offers telemetry-only, registry-only, and combined exports", async ({ page }) => {
    await page.getByRole("button", { name: "Migrate", exact: true }).first().click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Data migration")).toBeVisible();

    for (const option of ["Registry data", "Telemetry data", "Registry + telemetry"]) {
      await expect(dialog.getByText(option, { exact: true })).toBeVisible();
    }
  });

  test("starting a telemetry export requires picking the telemetry scope", async ({ page }) => {
    await page.getByRole("button", { name: "Migrate", exact: true }).first().click();

    const dialog = page.getByRole("dialog");
    const startButton = dialog.getByRole("button", { name: "Start export" });
    await expect(startButton).toBeEnabled();

    await dialog.getByText("Telemetry data", { exact: true }).click();
    await expect(dialog.getByLabel("Telemetry data")).toBeChecked();
    await expect(startButton).toBeEnabled();
  });
});
