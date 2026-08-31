// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { test, expect } from "@playwright/test";
import { mkdirSync, rmSync } from "node:fs";
import { runCommand } from "./command";

const PULL_DIR = "/tmp/kiro-e2e-pull";

test.describe("Kiro CLI Commands", () => {
  test.beforeAll(() => {
    runCommand(
      "observal",
      [
        "auth",
        "login",
        "--server",
        "http://localhost",
        "--email",
        "admin@demo.example",
      ],
      {
        allowFailure: true,
        env: { OBSERVAL_PASSWORD: "admin-changeme" },
      },
    );
  });

  test("observal doctor --harness kiro runs without errors", () => {
    const output = runCommand(
      "observal",
      ["doctor", "--harness", "kiro"],
      { allowFailure: true },
    );
    expect(output).toBeTruthy();
    expect(output).not.toContain("Traceback");
    expect(output).not.toContain("TypeError");
  });

  test("observal scan --harness kiro shows read-only inventory", () => {
    const output = runCommand(
      "observal",
      ["scan", "--harness", "kiro"],
      { allowFailure: true },
    );
    expect(output).not.toContain("Traceback");
    expect(output).toMatch(/Agents/);
    expect(output).toMatch(/coder|backend|frontend/i);
  });

  test("observal scan shows components from multiple harnesses", () => {
    const output = runCommand("observal", ["scan"], { allowFailure: true });
    expect(output).not.toContain("Traceback");
    const clean = output.replace(/\x1b\[[0-9;]*m/g, "");
    expect(clean).toMatch(/\d+ components discovered/);
    expect(clean).toMatch(/kiro/i);
  });

  test("observal doctor patch --harness kiro --dry-run previews changes", () => {
    const output = runCommand(
      "observal",
      ["doctor", "patch", "--harness", "kiro", "--dry-run"],
      { allowFailure: true },
    );
    expect(output).not.toContain("Traceback");
    expect(output).toMatch(/Dry run|Would/i);
  });

  test("observal agent pull --harness kiro --dry-run generates Kiro config", () => {
    let agents: { id?: string; name?: string }[];
    try {
      const payload = JSON.parse(
        runCommand("observal", ["agent", "list", "--output", "json"]),
      );
      agents = payload.items;
    } catch {
      test.skip();
      return;
    }
    if (!agents || agents.length === 0) {
      test.skip();
      return;
    }

    const agentId = agents[0].id ?? agents[0].name;
    if (!agentId) {
      test.skip();
      return;
    }
    rmSync(PULL_DIR, { recursive: true, force: true });
    mkdirSync(PULL_DIR, { recursive: true });

    try {
      const output = runCommand(
        "observal",
        [
          "agent",
          "pull",
          agentId,
          "--harness",
          "kiro",
          "--dir",
          PULL_DIR,
          "--dry-run",
          "--no-prompt",
        ],
        { allowFailure: true },
      );
      expect(output).not.toContain("Traceback");
    } finally {
      rmSync(PULL_DIR, { recursive: true, force: true });
    }
  });

  test("observal auth status reports healthy server", () => {
    const output = runCommand("observal", ["auth", "status"]);
    expect(output.toLowerCase()).toMatch(/ok|healthy/);
  });

  test("observal auth whoami returns current user", () => {
    const output = runCommand("observal", ["auth", "whoami"]);
    expect(output).toBeTruthy();
    expect(output).not.toContain("401");
    expect(output).not.toContain("Unauthorized");
  });
});
