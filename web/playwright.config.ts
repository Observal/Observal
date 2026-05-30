// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { defineConfig } from "@playwright/test";

const isCI = !!process.env.CI;

export default defineConfig({
  testDir: "../tests/e2e",
  timeout: 60_000,
  retries: 1,
  use: {
    // CI: Docker stack serves on port 80 via lb
    // Local: Vite dev server on port 5173
    baseURL: isCI ? "http://localhost:80" : "http://localhost:5173",
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  // Only start dev server locally; CI uses Docker stack
  webServer: isCI
    ? undefined
    : {
        command: "pnpm dev",
        port: 5173,
        reuseExistingServer: true,
        timeout: 120_000,
      },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
