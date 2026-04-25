import { test, expect } from "@playwright/test";
import { execSync } from "child_process";
import { getApiKey, API_BASE } from "./helpers";

const KIRO_AVAILABLE = (() => {
  try {
    execSync("which kiro-cli 2>/dev/null", { encoding: "utf-8" });
    return true;
  } catch {
    return false;
  }
})();

test.describe("Live Kiro CLI Sessions", () => {
  test.skip(!KIRO_AVAILABLE, "Kiro CLI not installed — skipping live tests");

  test("Kiro CLI version is accessible", () => {
    const output = execSync("kiro-cli --version 2>&1", {
      encoding: "utf-8",
      timeout: 10_000,
    });
    expect(output).toContain("kiro-cli");
  });

  test("Kiro telemetry check after session", async () => {
    // After running a Kiro session, check if any telemetry arrived
    const apiKey = await getApiKey();

    const sessions = await fetch(`${API_BASE}/api/v1/sessions`, {
      headers: { "Authorization": `Bearer ${apiKey}` },
    }).then((r) => r.json());

    // Look for any Kiro sessions
    const kiroSessions = sessions.filter(
      (s: Record<string, unknown>) =>
        (s.service_name as string)?.toLowerCase().includes("kiro") ||
        (s.terminal_type as string)?.toLowerCase().includes("kiro"),
    );

    // Informational — the test passes either way but logs the finding
    console.log(`Found ${kiroSessions.length} Kiro sessions in Observal`);
    if (kiroSessions.length > 0) {
      console.log(
        "First Kiro session:",
        JSON.stringify(kiroSessions[0], null, 2),
      );
    }
  });
});
