// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { test, expect } from "@playwright/test";
import { getApiKey, API_BASE } from "./helpers";
import { runCommand } from "./command";

const KIRO_AVAILABLE = (() => {
  try {
    runCommand("which", ["kiro-cli"]);
    return true;
  } catch {
    return false;
  }
})();

test.describe("Live Kiro CLI Sessions", () => {
  test.skip(!KIRO_AVAILABLE, "Kiro CLI not installed, skipping live tests");

  test("Kiro CLI version is accessible", () => {
    const output = runCommand("kiro-cli", ["--version"], { timeout: 10_000 });
    expect(output).toContain("kiro-cli");
  });

  test("Kiro telemetry check after session", async () => {
    const apiKey = await getApiKey();

    const sessions = await fetch(`${API_BASE}/api/v1/sessions`, {
      headers: { "Authorization": `Bearer ${apiKey}` },
    }).then((response) => response.json());

    const kiroSessions = sessions.filter(
      (session: Record<string, unknown>) =>
        (session.service_name as string)?.toLowerCase().includes("kiro") ||
        (session.terminal_type as string)?.toLowerCase().includes("kiro"),
    );

    console.log(`Found ${kiroSessions.length} Kiro sessions in Observal`);
    if (kiroSessions.length > 0) {
      console.log(
        "First Kiro session:",
        JSON.stringify(kiroSessions[0], null, 2),
      );
    }
  });
});
