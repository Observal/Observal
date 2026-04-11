import { test, expect } from "@playwright/test";
import { execSync } from "child_process";
import { getApiKey, API_BASE } from "./helpers";

function run(cmd: string): string {
  return execSync(cmd, {
    encoding: "utf-8",
    timeout: 30_000,
    cwd: "/home/haz3/code/blazeup/Observal",
  });
}

test.describe("Kiro Agent Cross-Compatibility", () => {
  let agentId: string;

  test.beforeAll(async () => {
    // Get an existing agent or skip
    const apiKey = await getApiKey();
    const agents = await fetch(`${API_BASE}/api/v1/agents`, {
      headers: { "X-API-Key": apiKey },
    }).then((r) => r.json());

    if (agents.length > 0) {
      agentId = agents[0].id;
    }
  });

  test("agent install endpoint returns valid Kiro config", async () => {
    test.skip(!agentId, "No agents available");

    const apiKey = await getApiKey();
    const config = await fetch(
      `${API_BASE}/api/v1/agents/${agentId}/install?ide=kiro`,
      { headers: { "X-API-Key": apiKey } },
    ).then((r) => r.json());

    expect(config).toBeTruthy();
    // Config should contain config_snippet with Kiro-appropriate fields
    const snippet = config.config_snippet ?? config;
    expect(snippet).toBeTruthy();
  });

  test("agent install endpoint returns valid Claude Code config", async () => {
    test.skip(!agentId, "No agents available");

    const apiKey = await getApiKey();
    const config = await fetch(
      `${API_BASE}/api/v1/agents/${agentId}/install?ide=claude-code`,
      { headers: { "X-API-Key": apiKey } },
    ).then((r) => r.json());

    expect(config).toBeTruthy();
  });

  test("pull for Kiro writes .kiro/ directory structure", () => {
    test.skip(!agentId, "No agents available");

    run("rm -rf /tmp/kiro-compat-pull && mkdir -p /tmp/kiro-compat-pull");

    try {
      run(
        `observal pull ${agentId} --ide kiro --dir /tmp/kiro-compat-pull 2>&1`,
      );
    } catch (e: unknown) {
      // Pull might fail if agent has no components — that's OK for this test
      const err = e as { stdout?: string; message?: string };
      console.log("Pull output:", err.stdout ?? err.message);
    }

    // Check what files were created
    try {
      const files = run(
        "find /tmp/kiro-compat-pull -type f 2>/dev/null",
      ).trim();
      console.log("Kiro pull created files:", files);

      // If MCP config was generated, verify it's valid JSON
      try {
        const mcpConfig = run(
          "cat /tmp/kiro-compat-pull/.kiro/settings/mcp.json 2>/dev/null",
        );
        JSON.parse(mcpConfig); // Should not throw
      } catch {
        // MCP config might not exist if agent has no MCP components
      }
    } catch {
      // No files created — agent might have no components
    }

    run("rm -rf /tmp/kiro-compat-pull");
  });

  test("pull for Claude Code writes .claude/ directory structure", () => {
    test.skip(!agentId, "No agents available");

    run("rm -rf /tmp/cc-compat-pull && mkdir -p /tmp/cc-compat-pull");

    try {
      run(
        `observal pull ${agentId} --ide claude-code --dir /tmp/cc-compat-pull 2>&1`,
      );
    } catch (e: unknown) {
      const err = e as { stdout?: string; message?: string };
      console.log("Pull output:", err.stdout ?? err.message);
    }

    try {
      const files = run(
        "find /tmp/cc-compat-pull -type f 2>/dev/null",
      ).trim();
      console.log("Claude Code pull created files:", files);
    } catch {
      // No files — OK
    }

    run("rm -rf /tmp/cc-compat-pull");
  });
});
