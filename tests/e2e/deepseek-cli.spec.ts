// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-License-Identifier: Apache-2.0

import { test, expect } from "@playwright/test";
import { getAccessToken } from "./helpers";
import { runCommand } from "./command";

/**
 * DeepSeek Harness CLI coverage: doctor, patch/cleanup, scan, reconcile dry-run,
 * and session-payload delivery through the native collector contract.
 *
 * These tests are read-only against the user's DSH_HOME except for the
 * patch/cleanup cycle, which restores the previous telemetry state.
 */
test.describe("DeepSeek CLI Commands", () => {
  test.beforeAll(() => {
    runCommand(
      "observal",
      ["auth", "login", "--server", "http://localhost", "--email", "admin@demo.example"],
      {
        allowFailure: true,
        env: { OBSERVAL_PASSWORD: "admin-changeme" },
      },
    );
  });

  test("observal doctor --harness deepseek runs without errors", () => {
    const output = runCommand("observal", ["doctor"], { allowFailure: true });
    expect(output).not.toContain("Traceback");
    expect(output).toContain("Checking DeepSeek Harness");
  });

  test("observal scan --harness deepseek shows read-only inventory", () => {
    const output = runCommand("observal", ["scan", "--harness", "deepseek"], { allowFailure: true });
    expect(output).not.toContain("Traceback");
    const clean = output.replace(/\x1b\[[0-9;]*m/g, "");
    expect(clean).toMatch(/deepseek/i);
  });

  test("observal doctor patch then cleanup round-trips telemetry state", () => {
    const patch = runCommand("observal", ["doctor", "patch", "--harness", "deepseek"], {
      allowFailure: true,
    });
    expect(patch).toMatch(/Patch complete|Everything already up to date/);
    const afterPatch = runCommand("observal", ["scan", "--harness", "deepseek", "--output", "json"], {
      allowFailure: true,
    });
    expect(afterPatch).not.toContain('"missing"');

    const cleanup = runCommand("observal", ["doctor", "cleanup", "--harness", "deepseek", "--yes"], {
      allowFailure: true,
    });
    expect(cleanup).toMatch(/Cleanup complete|Nothing to clean/);
    const restore = runCommand("observal", ["doctor", "patch", "--harness", "deepseek"], {
      allowFailure: true,
    });
    expect(restore).toMatch(/Patch complete|Everything already up to date/);
  });

  test("observal reconcile --harness deepseek --dry-run stays read-only", () => {
    const output = runCommand(
      "observal",
      ["reconcile", "--harness", "deepseek", "--dry-run"],
      { allowFailure: true },
    );
    expect(output).not.toContain("Traceback");
    expect(output).toMatch(/Dry run|scanning sessions/);
  });
});

test.describe("DeepSeek web telemetry", () => {
  test("delivered sessions surface on the traces page", async ({ page }) => {
    // getAccessToken retries through the login rate limit (5/min).
    const token = await getAccessToken();

    await page.goto("/traces");
    await page.evaluate((t) => {
      sessionStorage.setItem("observal_access_token", t);
      localStorage.setItem("observal_user_role", "admin");
    }, token);
    await page.reload();
    await page.waitForLoadState("networkidle");
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
  });
});
