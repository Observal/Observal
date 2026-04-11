import { test, expect } from "@playwright/test";
import { execSync } from "child_process";

const CLI_TIMEOUT = 30_000;
const CWD = "/home/haz3/code/blazeup/Observal";

function run(cmd: string): string {
  return execSync(cmd, { encoding: "utf-8", timeout: CLI_TIMEOUT, cwd: CWD });
}

test.describe("Kiro CLI Commands", () => {
  test("observal doctor --ide kiro runs without errors", () => {
    const output = run("observal doctor --ide kiro 2>&1 || true");
    // Doctor should run and produce output (may have warnings, but shouldn't crash)
    expect(output).toBeTruthy();
    expect(output).not.toContain("Traceback");
    expect(output).not.toContain("TypeError");
  });

  test("observal scan --ide kiro --dry-run works on a mock project", () => {
    // Create a temporary Kiro project
    run("mkdir -p /tmp/kiro-e2e-scan/.kiro/settings");
    run(
      `echo '{"mcpServers": {"test-mcp": {"command": "echo", "args": ["hello"]}}}' > /tmp/kiro-e2e-scan/.kiro/settings/mcp.json`,
    );

    const output = run(
      "cd /tmp/kiro-e2e-scan && observal scan --ide kiro --dry-run 2>&1 || true",
    );
    expect(output).not.toContain("Traceback");

    // Cleanup
    run("rm -rf /tmp/kiro-e2e-scan");
  });

  test("observal pull --ide kiro --dry-run generates Kiro config", () => {
    // Get an agent to pull
    let agents: { id?: string; name?: string }[];
    try {
      agents = JSON.parse(run("observal agent list --output json 2>/dev/null"));
    } catch {
      test.skip();
      return;
    }
    if (!agents || agents.length === 0) {
      test.skip();
      return;
    }

    const agentId = agents[0].id ?? agents[0].name;
    run("mkdir -p /tmp/kiro-e2e-pull");

    const output = run(
      `observal pull ${agentId} --ide kiro --dir /tmp/kiro-e2e-pull --dry-run 2>&1 || true`,
    );
    expect(output).not.toContain("Traceback");

    // Cleanup
    run("rm -rf /tmp/kiro-e2e-pull");
  });

  test("observal auth status reports healthy server", () => {
    const output = run("observal auth status 2>&1");
    expect(output.toLowerCase()).toMatch(/ok|healthy/);
  });

  test("observal auth whoami returns current user", () => {
    const output = run("observal auth whoami 2>&1");
    expect(output).toBeTruthy();
    expect(output).not.toContain("401");
    expect(output).not.toContain("Unauthorized");
  });
});
