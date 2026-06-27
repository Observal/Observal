// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { execSync } from "child_process";

const CLI_TIMEOUT = 30_000;
const CWD = execSync("git rev-parse --show-toplevel", {
  encoding: "utf-8",
}).trim();

function run(cmd: string): string {
  return execSync(cmd, { encoding: "utf-8", timeout: CLI_TIMEOUT, cwd: CWD });
}

test.describe("Kiro CLI Commands", () => {
  test.beforeAll(() => {
    try {
      execSync(
        'observal auth login --server http://localhost --email admin@demo.example --password admin-changeme 2>&1',
        { encoding: "utf-8", timeout: CLI_TIMEOUT, cwd: CWD },
      );
    } catch {
      // login may fail if already configured — that's fine
    }
  });

  test("observal doctor --harness kiro runs without errors", () => {
    const output = run("observal doctor --harness kiro 2>&1 || true");
    // Doctor should run and produce output (may have warnings, but shouldn't crash)
    expect(output).toBeTruthy();
    expect(output).not.toContain("Traceback");
    expect(output).not.toContain("TypeError");
  });

  test("observal scan --harness kiro shows read-only inventory", () => {
    const output = run("observal scan --harness kiro 2>&1 || true");
    expect(output).not.toContain("Traceback");
    // Should discover Kiro agents from ~/.kiro/agents/
    expect(output).toMatch(/Agents/);
    expect(output).toMatch(/coder|backend|frontend/i);
  });

  test("observal scan shows components from multiple harnesses", () => {
    const output = run("observal scan 2>&1 || true");
    expect(output).not.toContain("Traceback");
    const clean = output.replace(/\x1b\[[0-9;]*m/g, "");
    expect(clean).toMatch(/\d+ components discovered/);
    expect(clean).toMatch(/kiro/i);
  });

  test("observal doctor patch --hook --harness kiro --dry-run previews changes", () => {
    const output = run("observal doctor patch --hook --harness kiro --dry-run 2>&1 || true");
    expect(output).not.toContain("Traceback");
    expect(output).toMatch(/Dry run|Would/i);
  });

  test("observal pull --harness kiro --dry-run generates Kiro config", () => {
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
      `observal pull ${agentId} --harness kiro --dir /tmp/kiro-e2e-pull --dry-run 2>&1 || true`,
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
