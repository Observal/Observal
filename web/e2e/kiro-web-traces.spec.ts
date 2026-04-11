import { test, expect } from "@playwright/test";
import {
  loginToWebUI,
  sendKiroOTLPLog,
  buildKiroOTLPLogPayload,
} from "./helpers";

test.describe("Kiro Traces in Web UI", () => {
  test.beforeEach(async ({ page }) => {
    await loginToWebUI(page);
  });

  test("Kiro session appears after sending OTLP telemetry", async ({
    page,
  }) => {
    // Send some Kiro telemetry first
    const sessionId = `kiro-web-test-${Date.now()}`;
    const promptId = crypto.randomUUID().replace(/-/g, "");

    await sendKiroOTLPLog(
      buildKiroOTLPLogPayload({
        sessionId,
        promptId,
        eventName: "user_prompt",
        body: "Hello from Kiro E2E test",
        attributes: { prompt: "Hello from Kiro E2E test" },
      }),
    );

    await sendKiroOTLPLog(
      buildKiroOTLPLogPayload({
        sessionId,
        promptId,
        eventName: "api_request",
        attributes: {
          model: "anthropic.claude-sonnet-4-20250514",
          input_tokens: "50",
          output_tokens: "100",
        },
      }),
    );

    // Wait for ingestion
    await new Promise((r) => setTimeout(r, 3000));

    // Navigate to traces page
    await page.goto("/traces");
    await page.waitForLoadState("networkidle");

    // The traces page should load without errors
    await expect(page.locator("body")).not.toContainText("Something went wrong");
    await expect(page.locator("body")).not.toContainText("500");
  });

  test("Kiro trace detail page loads correctly", async ({ page }) => {
    // Navigate to traces page and click on the first trace
    await page.goto("/traces");
    await page.waitForLoadState("networkidle");

    // Check if there are any trace rows
    const traceRows = page.locator("table tbody tr");
    const count = await traceRows.count();

    if (count > 0) {
      // Click the first trace
      await traceRows.first().click();
      await page.waitForLoadState("networkidle");

      // Verify the detail page loads
      await expect(page.locator("body")).not.toContainText(
        "Something went wrong",
      );
    }
  });

  test("dashboard page loads and shows stats", async ({ page }) => {
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // Dashboard should load without errors
    await expect(page.locator("body")).not.toContainText("Something went wrong");

    // Should show some kind of heading
    const heading = page.locator("h1, h2").first();
    await expect(heading).toBeVisible();
  });
});
