/**
 * Screenshot script for the component edit form and detail page.
 * Run: npx playwright test e2e/component-edit-screenshots.spec.ts --project=chromium
 */
import { test } from "@playwright/test";
import { loginToWebUI, API_BASE, getAccessToken } from "./helpers";

const SCREENSHOT_DIR = "e2e/screenshots/component-edit";

test.describe("Component Edit Form Screenshots", () => {
  let hookId: string;
  let skillId: string;
  let promptId: string;
  let mcpId: string;

  test.beforeAll(async () => {
    const token = await getAccessToken();
    const headers = {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    };

    // Create a test hook
    const hookRes = await fetch(`${API_BASE}/api/v1/hooks/submit`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        name: `screenshot-hook-${Date.now()}`,
        version: "1.0.0",
        owner: "platform-team",
        description: "Pre-tool validation hook that blocks dangerous shell commands",
        event: "PreToolUse",
        handler_type: "command",
        execution_mode: "blocking",
        priority: 10,
        scope: "agent",
        handler_config: { command: "./scripts/validate-tool.sh" },
        tool_filter: ["bash", "shell"],
        file_pattern: ["*.sh", "*.bash"],
      }),
    });
    if (hookRes.ok) hookId = (await hookRes.json()).id;

    // Create a test skill
    const skillRes = await fetch(`${API_BASE}/api/v1/skills/submit`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        name: `screenshot-skill-${Date.now()}`,
        version: "1.0.0",
        owner: "platform-team",
        description: "Code review skill that evaluates PRs for quality",
        task_type: "code-review",
        skill_path: "/review",
        slash_command: "review",
        has_scripts: true,
        has_templates: false,
        is_power: true,
        power_md: "# Code Review\n\nAnalyze the diff for issues.\n\n## Checklist\n- Security vulnerabilities\n- Performance issues\n- Code style violations",
        activation_keywords: ["review", "check", "audit"],
      }),
    });
    if (skillRes.ok) skillId = (await skillRes.json()).id;

    // Create a test prompt
    const promptRes = await fetch(`${API_BASE}/api/v1/prompts/submit`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        name: `screenshot-prompt-${Date.now()}`,
        version: "1.0.0",
        owner: "platform-team",
        description: "System prompt for a documentation writer agent",
        category: "system-prompt",
        template: "You are a documentation writer. Write clear, concise documentation.\n\nFormat: {{format}}\nAudience: {{audience}}\nTone: {{tone}}",
        variables: [
          { name: "format", type: "string", default: "markdown" },
          { name: "audience", type: "string", default: "developers" },
          { name: "tone", type: "string", default: "professional" },
        ],
        tags: ["documentation", "writing", "technical"],
        model_hints: { preferred_model: "claude-sonnet-4-20250514" },
      }),
    });
    if (promptRes.ok) promptId = (await promptRes.json()).id;

    // Publish two additional versions and approve them so the dropdown renders
    if (hookId) {
      // Publish v1.0.1
      await fetch(`${API_BASE}/api/v1/hooks/${hookId}/versions`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          version: "1.0.1",
          description: "Patch fix for edge case in tool validation",
          extra: { event: "PreToolUse", handler_type: "command" },
        }),
      });
      // Publish v1.1.0
      await fetch(`${API_BASE}/api/v1/hooks/${hookId}/versions`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          version: "1.1.0",
          description: "Added timeout configuration and retry logic",
          changelog: "New timeout and retry options for shell commands",
          extra: {
            event: "PreToolUse",
            handler_type: "command",
            execution_mode: "blocking",
            priority: 5,
            scope: "agent",
          },
        }),
      });
      // Approve both
      await fetch(`${API_BASE}/api/v1/hooks/${hookId}/versions/1.0.1/review`, {
        method: "POST",
        headers,
        body: JSON.stringify({ action: "approve" }),
      });
      await fetch(`${API_BASE}/api/v1/hooks/${hookId}/versions/1.1.0/review`, {
        method: "POST",
        headers,
        body: JSON.stringify({ action: "approve" }),
      });
    }

    // Create a test MCP
    const mcpRes = await fetch(`${API_BASE}/api/v1/mcps/submit`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        name: `screenshot-mcp-${Date.now()}`,
        version: "1.0.0",
        owner: "platform-team",
        description: "GitHub integration MCP server",
        category: "developer-tools",
        transport: "stdio",
        command: "npx",
        args: ["-y", "@modelcontextprotocol/server-github"],
      }),
    });
    if (mcpRes.ok) mcpId = (await mcpRes.json()).id;
  });

  test.afterAll(async () => {
    const token = await getAccessToken();
    const headers = { Authorization: `Bearer ${token}` };
    if (hookId) await fetch(`${API_BASE}/api/v1/hooks/${hookId}`, { method: "DELETE", headers });
    if (skillId) await fetch(`${API_BASE}/api/v1/skills/${skillId}`, { method: "DELETE", headers });
    if (promptId) await fetch(`${API_BASE}/api/v1/prompts/${promptId}`, { method: "DELETE", headers });
    if (mcpId) await fetch(`${API_BASE}/api/v1/mcps/${mcpId}`, { method: "DELETE", headers });
  });

  test("1 - Hook edit form", async ({ page }) => {
    test.skip(!hookId, "Hook not created");
    await page.setViewportSize({ width: 1280, height: 1600 });
    await loginToWebUI(page);
    await page.goto(`/components/${hookId}?type=hooks`);
    await page.waitForLoadState("networkidle");
    await page.getByRole("tab", { name: "Edit" }).click();
    await page.waitForTimeout(500);
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/01-hook-edit-form.png`,
      fullPage: true,
    });
  });

  test("2 - Skill edit form", async ({ page }) => {
    test.skip(!skillId, "Skill not created");
    await page.setViewportSize({ width: 1280, height: 1600 });
    await loginToWebUI(page);
    await page.goto(`/components/${skillId}?type=skills`);
    await page.waitForLoadState("networkidle");
    await page.getByRole("tab", { name: "Edit" }).click();
    await page.waitForTimeout(500);
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/02-skill-edit-form.png`,
      fullPage: true,
    });
  });

  test("3 - Prompt edit form", async ({ page }) => {
    test.skip(!promptId, "Prompt not created");
    await page.setViewportSize({ width: 1280, height: 1600 });
    await loginToWebUI(page);
    await page.goto(`/components/${promptId}?type=prompts`);
    await page.waitForLoadState("networkidle");
    await page.getByRole("tab", { name: "Edit" }).click();
    await page.waitForTimeout(500);
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/03-prompt-edit-form.png`,
      fullPage: true,
    });
  });

  test("4 - MCP WIP stub", async ({ page }) => {
    test.skip(!mcpId, "MCP not created");
    await loginToWebUI(page);
    await page.goto(`/components/${mcpId}?type=mcps`);
    await page.waitForLoadState("networkidle");
    await page.getByRole("tab", { name: "Edit" }).click();
    await page.waitForTimeout(500);
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/04-mcp-wip-stub.png`,
      fullPage: true,
    });
  });

  test("5 - Versions tab", async ({ page }) => {
    test.skip(!hookId, "Hook not created");
    await loginToWebUI(page);
    await page.goto(`/components/${hookId}?type=hooks`);
    await page.waitForLoadState("networkidle");
    await page.getByRole("tab", { name: "Versions" }).click();
    await page.waitForTimeout(500);
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/05-versions-tab.png`,
      fullPage: true,
    });
  });

  test("6 - Component detail header with version dropdown", async ({ page }) => {
    test.skip(!hookId, "Hook not created");
    await loginToWebUI(page);
    await page.goto(`/components/${hookId}?type=hooks`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    // Take the closed state first
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/06-version-dropdown-closed.png`,
      fullPage: false,
    });
    // Click the Select trigger to open the dropdown
    const trigger = page.locator("button[role='combobox']");
    if (await trigger.isVisible()) {
      await trigger.click();
      await page.waitForTimeout(300);
    }
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/07-version-dropdown-open.png`,
      fullPage: false,
    });
  });
});
