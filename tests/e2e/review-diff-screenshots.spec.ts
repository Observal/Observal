// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

/**
 * Screenshots for the review diff dialog.
 * Creates an agent, submits v1 (pending), screenshots the review dialog,
 * then creates v2 (pending) with changes and screenshots the diff view.
 *
 * Run: npx playwright test e2e/review-diff-screenshots.spec.ts --project=chromium
 */
import { expect, test } from "@playwright/test";
import { loginToWebUI, API_BASE, getAccessToken } from "./helpers";

const SCREENSHOT_DIR = "e2e/screenshots";

test.describe("Review Diff Dialog Screenshots", () => {
  let agentId: string;
  let token: string;

  test.beforeAll(async () => {
    token = await getAccessToken();

    // Create a test agent (starts as draft)
    const createRes = await fetch(`${API_BASE}/api/v1/agents`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: `review-diff-test-${Date.now()}`,
        version: "1.0.0",
        description: "A security-focused code review agent that scans PRs for OWASP Top 10 vulnerabilities.",
        owner: "platform-team",
        model_name: "claude-sonnet-4-20250514",
        prompt: "## Security Review Agent\n\nYou are a security-focused code reviewer. Your job is to analyze code changes for vulnerabilities.\n\n## Focus Areas\n- SQL injection (A03)\n- Broken authentication (A07)\n- Sensitive data exposure (A02)\n\n## Output Format\nProvide findings as a structured report with severity levels.",
        components: [],
      }),
    });

    if (!createRes.ok) {
      const body = await createRes.text();
      throw new Error(`Failed to create agent: ${createRes.status} ${body}`);
    }

    const agent = await createRes.json();
    agentId = agent.id;
    // Agent creation already creates v1.0.0 as pending — it shows in the review queue
  });

  test.afterAll(async () => {
    if (!agentId) return;
    await fetch(`${API_BASE}/api/v1/agents/${agentId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
  });

  test("1 - Review dialog first release (no diff, shows snapshot)", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/review");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);

    // Select the agent, then open its full diff from the detail pane.
    const agentCard = page.locator(`[data-review-item="${agentId}"]`);
    await agentCard.click();
    await page.getByRole("button", { name: "View full diff", exact: true }).click();
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/07-review-dialog-first-release.png`,
      fullPage: false,
    });
  });

  test("2 - Review dialog with diff (v1 approved, v2 pending)", async ({ page }) => {
    // Approve v1 via the review router so we have a previous approved version
    const approveRes = await fetch(
      `${API_BASE}/api/v1/review/agents/${agentId}/approve`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      },
    );

    if (!approveRes.ok) {
      const body = await approveRes.text();
      throw new Error(`Failed to approve v1: ${approveRes.status} ${body}`);
    }

    // Create v2 with changes (pending, shows up in review queue)
    const v2Res = await fetch(`${API_BASE}/api/v1/agents/${agentId}/versions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        version: "1.1.0",
        description: "Added XSS detection and improved output format with CVSS scoring",
        model_name: "claude-sonnet-4-20250514",
        prompt: "## Security Review Agent\n\nYou are a security-focused code reviewer. Your job is to analyze code changes for vulnerabilities and compliance issues.\n\n## Focus Areas\n- SQL injection (A03)\n- Cross-site scripting / XSS (A07)\n- Broken authentication (A07)\n- Sensitive data exposure (A02)\n- Server-side request forgery (A10)\n\n## Output Format\nProvide findings as a structured report with:\n- Severity (critical/high/medium/low)\n- CVSS score\n- Remediation steps\n- Code references",
        supported_harnesses: ["claude_code", "copilot_cli", "kiro"],
        components: [],
      }),
    });

    if (!v2Res.ok) {
      const body = await v2Res.text();
      throw new Error(`Failed to create v2: ${v2Res.status} ${body}`);
    }

    await loginToWebUI(page);
    await page.goto("/review");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);

    // Select the agent, then open its full diff from the detail pane.
    const agentCard = page.locator(`[data-review-item="${agentId}"]`);
    await agentCard.click();
    await page.getByRole("button", { name: "View full diff", exact: true }).click();
    await page.waitForTimeout(1500);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/08-review-dialog-diff-view.png`,
      fullPage: false,
    });
  });

  test("3 - Inline rejection", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/review");
    await page.waitForLoadState("networkidle");

    const agentCard = page.locator(`[data-review-item="${agentId}"]`);
    await agentCard.click();
    await page.getByLabel(/Review note/).fill(
      "Missing CSRF detection in focus areas. Please add A05 coverage before approval.",
    );

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/09-review-inline-rejection.png`,
      fullPage: false,
    });

    await page.getByRole("button", { name: "Reject", exact: true }).click();
    await expect(agentCard).toHaveCount(0);
  });
});
