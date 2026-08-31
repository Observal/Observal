// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { test, expect } from "@playwright/test";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
} from "node:fs";
import { getApiKey, API_BASE } from "./helpers";
import { runCommand } from "./command";

const KIRO_PULL_DIR = "/tmp/kiro-compat-pull";
const CLAUDE_PULL_DIR = "/tmp/cc-compat-pull";

function resetDirectory(path: string): void {
  rmSync(path, { recursive: true, force: true });
  mkdirSync(path, { recursive: true });
}

function listFiles(path: string): string {
  return existsSync(path)
    ? readdirSync(path, { recursive: true })
        .map(String)
        .sort()
        .join("\n")
    : "";
}

test.describe("Kiro Agent Cross-Compatibility", () => {
  let agentId: string;

  test.beforeAll(async () => {
    const apiKey = await getApiKey();
    const agents = await fetch(`${API_BASE}/api/v1/agents`, {
      headers: { "Authorization": `Bearer ${apiKey}` },
    }).then((response) => response.json());

    if (agents.length > 0) {
      agentId = agents[0].id;
    }
  });

  test("agent install endpoint returns valid Kiro config", async () => {
    test.skip(!agentId, "No agents available");

    const apiKey = await getApiKey();
    const config = await fetch(
      `${API_BASE}/api/v1/agents/${agentId}/install?ide=kiro`,
      { headers: { "Authorization": `Bearer ${apiKey}` } },
    ).then((response) => response.json());

    expect(config).toBeTruthy();
    const snippet = config.config_snippet ?? config;
    expect(snippet).toBeTruthy();
  });

  test("agent install endpoint returns valid Claude Code config", async () => {
    test.skip(!agentId, "No agents available");

    const apiKey = await getApiKey();
    const config = await fetch(
      `${API_BASE}/api/v1/agents/${agentId}/install?ide=claude-code`,
      { headers: { "Authorization": `Bearer ${apiKey}` } },
    ).then((response) => response.json());

    expect(config).toBeTruthy();
  });

  test("pull for Kiro writes .kiro/ directory structure", () => {
    test.skip(!agentId, "No agents available");
    resetDirectory(KIRO_PULL_DIR);

    try {
      runCommand("observal", [
        "agent",
        "pull",
        agentId,
        "--harness",
        "kiro",
        "--dir",
        KIRO_PULL_DIR,
        "--no-prompt",
      ]);

      const files = listFiles(KIRO_PULL_DIR);
      expect(files).toBeTruthy();
      console.log("Kiro pull created files:", files);

      const mcpPath = `${KIRO_PULL_DIR}/.kiro/settings/mcp.json`;
      if (existsSync(mcpPath)) {
        JSON.parse(readFileSync(mcpPath, "utf-8"));
      }
    } finally {
      rmSync(KIRO_PULL_DIR, { recursive: true, force: true });
    }
  });

  test("pull for Claude Code writes .claude/ directory structure", () => {
    test.skip(!agentId, "No agents available");
    resetDirectory(CLAUDE_PULL_DIR);

    try {
      runCommand("observal", [
        "agent",
        "pull",
        agentId,
        "--harness",
        "claude-code",
        "--dir",
        CLAUDE_PULL_DIR,
        "--no-prompt",
      ]);

      const files = listFiles(CLAUDE_PULL_DIR);
      expect(files).toBeTruthy();
      console.log("Claude Code pull created files:", files);
    } finally {
      rmSync(CLAUDE_PULL_DIR, { recursive: true, force: true });
    }
  });
});
