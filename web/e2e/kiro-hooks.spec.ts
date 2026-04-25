import { test, expect } from "@playwright/test";
import { sendKiroHookEvent, getAccessToken, API_BASE } from "./helpers";

test.describe("Kiro Hook Event Ingestion", () => {
  test("accepts PostToolUse hook event from Kiro", async () => {
    const result = await sendKiroHookEvent({
      hook_event_name: "PostToolUse",
      session_id: `kiro-hook-${Date.now()}`,
      tool_name: "Read",
      tool_input: JSON.stringify({ file_path: "/tmp/test.txt" }),
      tool_response: "file contents here",
    });
    expect(result.ingested).toBe(1);
  });

  test("accepts SessionStart hook event from Kiro", async () => {
    const result = await sendKiroHookEvent({
      hook_event_name: "SessionStart",
      session_id: `kiro-session-${Date.now()}`,
    });
    expect(result.ingested).toBe(1);
  });

  test("accepts Kiro camelCase hook event names", async () => {
    const sessionId = `kiro-camel-${Date.now()}`;
    const result = await sendKiroHookEvent({
      hook_event_name: "agentSpawn",
      session_id: sessionId,
    });
    expect(result.ingested).toBe(1);
    // Server either normalizes agentSpawn → SessionStart or passes through
    expect(["agentSpawn", "SessionStart"]).toContain(result.event);
  });

  test("accepts Kiro camelCase field names", async () => {
    const result = await sendKiroHookEvent({
      hookEventName: "postToolUse",
      sessionId: `kiro-camel-fields-${Date.now()}`,
      toolName: "Bash",
      toolInput: JSON.stringify({ command: "ls -la" }),
      toolResponse: "total 0",
    });
    expect(result.ingested).toBe(1);
    // Server normalizes camelCase fields and events; older server may not
    expect(["postToolUse", "PostToolUse", "unknown"]).toContain(result.event);
  });

  test("accepts PreToolUse hook event from Kiro", async () => {
    const result = await sendKiroHookEvent({
      hook_event_name: "PreToolUse",
      session_id: `kiro-pretool-${Date.now()}`,
      tool_name: "Bash",
      tool_input: JSON.stringify({ command: "ls -la" }),
    });
    expect(result.ingested).toBe(1);
  });

  test("handles multiple hook events in sequence", async () => {
    const sessionId = `kiro-multi-hook-${Date.now()}`;

    const events = [
      { hook_event_name: "SessionStart", session_id: sessionId },
      {
        hook_event_name: "PreToolUse",
        session_id: sessionId,
        tool_name: "Read",
      },
      {
        hook_event_name: "PostToolUse",
        session_id: sessionId,
        tool_name: "Read",
        tool_response: "file data",
      },
      {
        hook_event_name: "PreToolUse",
        session_id: sessionId,
        tool_name: "Edit",
      },
      {
        hook_event_name: "PostToolUse",
        session_id: sessionId,
        tool_name: "Edit",
        tool_response: "edited",
      },
    ];

    for (const event of events) {
      const result = await sendKiroHookEvent(event);
      expect(result.ingested).toBe(1);
    }
  });

  test("Kiro session appears in sessions list after hook events", async () => {
    const sessionId = `kiro-visible-${Date.now()}`;

    // Send a full Kiro session lifecycle
    await sendKiroHookEvent({
      hook_event_name: "agentSpawn",
      session_id: sessionId,
      service_name: "kiro",
      cwd: "/tmp",
      prompt: "test prompt",
    });
    await sendKiroHookEvent({
      hook_event_name: "userPromptSubmit",
      session_id: sessionId,
      service_name: "kiro",
      cwd: "/tmp",
      prompt: "test prompt",
    });
    await sendKiroHookEvent({
      hook_event_name: "stop",
      session_id: sessionId,
      service_name: "kiro",
      cwd: "/tmp",
      assistant_response: "test response",
    });

    // Check sessions list (requires auth)
    const token = await getAccessToken();
    const sessions = await fetch(`${API_BASE}/api/v1/sessions`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then((r) => r.json());
    const kiroSession = sessions.find(
      (s: Record<string, unknown>) => s.session_id === sessionId,
    );
    expect(kiroSession).toBeTruthy();
    // 3 events total: sessionstart (hook), user_prompt (prompt), assistant_response (hook)
    const totalEvents =
      (kiroSession.hook_event_count ?? 0) + (kiroSession.prompt_count ?? 0);
    expect(totalEvents).toBeGreaterThanOrEqual(3);
  });
});
