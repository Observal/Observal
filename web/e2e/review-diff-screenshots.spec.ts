/**
 * Screenshots for the review diff dialog.
 * Creates an agent, submits v1 (pending), screenshots the review dialog,
 * then creates v2 (pending) with changes and screenshots the diff view.
 *
 * Run: npx playwright test e2e/review-diff-screenshots.spec.ts --project=chromium
 */
import { test } from "@playwright/test";
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
        goal_template: {
          description: "Review code for security issues",
          sections: [
            { name: "Scan", description: "Scan for vulnerabilities" },
            { name: "Report", description: "Generate findings report" },
          ],
        },
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

    // Click the agent name in the review list to open the diff dialog
    const agentCard = page.locator("button:has-text('review-diff-test')").first();
    await agentCard.click();
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
        supported_ides: ["claude_code", "copilot_cli", "kiro"],
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

    // Click the agent to open the diff dialog
    const agentCard = page.locator("button:has-text('review-diff-test')").first();
    await agentCard.click();
    await page.waitForTimeout(1500);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/08-review-dialog-diff-view.png`,
      fullPage: false,
    });
  });

  test("3 - Reject dialog", async ({ page }) => {
    await loginToWebUI(page);
    await page.goto("/review");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);

    // Click our specific agent (the v2 pending from test 2)
    const agentCard = page.locator("button:has-text('review-diff-test')").first();
    await agentCard.click();

    // Wait for the main review dialog to open
    const mainDialog = page.locator("[role='dialog']").first();
    await mainDialog.waitFor({ state: "visible", timeout: 5000 });
    await page.waitForTimeout(1000);

    // Click Reject inside the main dialog footer
    const rejectBtn = mainDialog.locator("button", { hasText: "Reject" });
    await rejectBtn.click();

    // Wait for the nested reject-reason dialog to appear
    // It will be the second [role='dialog'] on the page
    const rejectDialog = page.locator("[role='dialog']").nth(1);
    await rejectDialog.waitFor({ state: "visible", timeout: 5000 });
    await page.waitForTimeout(300);

    // Type a reason
    const textarea = rejectDialog.locator("textarea");
    await textarea.fill("Missing CSRF detection in focus areas. Please add A05 (Security Misconfiguration) coverage before approval.");
    await page.waitForTimeout(300);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/09-review-reject-dialog.png`,
      fullPage: false,
    });
  });
});
