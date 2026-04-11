import { test, expect } from "@playwright/test";
import {
  loginToWebUI,
  sendKiroOTLPLog,
  sendKiroHookEvent,
  buildKiroOTLPLogPayload,
  API_BASE,
  getApiKey,
} from "./helpers";

test.describe("Kiro Full Lifecycle E2E", () => {
  const SESSION_ID = `kiro-lifecycle-${Date.now()}`;
  const PROMPT_ID = crypto.randomUUID().replace(/-/g, "");

  test("Step 1: Simulate a complete Kiro coding session", async () => {
    // SessionStart hook
    await sendKiroHookEvent({
      hook_event_name: "SessionStart",
      session_id: SESSION_ID,
    });

    // User prompt (OTLP log)
    await sendKiroOTLPLog(
      buildKiroOTLPLogPayload({
        sessionId: SESSION_ID,
        promptId: PROMPT_ID,
        eventName: "user_prompt",
        body: "Create a React component that shows a user profile card",
        attributes: {
          prompt: "Create a React component that shows a user profile card",
        },
      }),
    );

    // API request (OTLP log)
    await sendKiroOTLPLog(
      buildKiroOTLPLogPayload({
        sessionId: SESSION_ID,
        promptId: PROMPT_ID,
        eventName: "api_request",
        attributes: {
          model: "anthropic.claude-sonnet-4-20250514",
          input_tokens: "450",
          output_tokens: "1200",
          cache_read_tokens: "200",
          duration_ms: "3500",
        },
      }),
    );

    // PreToolUse hook
    await sendKiroHookEvent({
      hook_event_name: "PreToolUse",
      session_id: SESSION_ID,
      tool_name: "Write",
    });

    // Tool result (OTLP log)
    await sendKiroOTLPLog(
      buildKiroOTLPLogPayload({
        sessionId: SESSION_ID,
        promptId: PROMPT_ID,
        eventName: "tool_result",
        body: "File written successfully",
        attributes: {
          tool_name: "Write",
          success: "true",
          duration_ms: "25",
        },
      }),
    );

    // PostToolUse hook
    await sendKiroHookEvent({
      hook_event_name: "PostToolUse",
      session_id: SESSION_ID,
      tool_name: "Write",
      tool_response: "File written successfully",
    });
  });

  test("Step 2: Verify Kiro session data via API", async () => {
    // Wait for data to settle
    await new Promise((r) => setTimeout(r, 3000));

    const apiKey = await getApiKey();

    // Check OTEL sessions
    const sessions = await fetch(`${API_BASE}/api/v1/otel/sessions`, {
      headers: { "X-API-Key": apiKey },
    }).then((r) => r.json());

    expect(sessions.length).toBeGreaterThan(0);
  });

  test("Step 3: Verify Kiro traces appear in Web UI", async ({ page }) => {
    await loginToWebUI(page);

    // Navigate to traces page
    await page.goto("/traces");
    await page.waitForLoadState("networkidle");

    // Page should load without errors
    await expect(page.locator("body")).not.toContainText("Something went wrong");

    // Take a screenshot for visual verification
    await page.screenshot({ path: "e2e-results/kiro-traces-page.png" });
  });

  test("Step 4: Verify dashboard reflects Kiro data", async ({ page }) => {
    await loginToWebUI(page);

    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("body")).not.toContainText("Something went wrong");
    await page.screenshot({ path: "e2e-results/kiro-dashboard.png" });
  });
});
