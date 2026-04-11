import { test, expect } from "@playwright/test";
import { sendKiroHookEvent } from "./helpers";

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

  test("accepts Kiro camelCase hook event names and normalizes them", async () => {
    const result = await sendKiroHookEvent({
      hook_event_name: "agentSpawn",
      session_id: `kiro-camel-${Date.now()}`,
    });
    expect(result.ingested).toBe(1);
  });

  test("accepts Kiro camelCase field names and normalizes them", async () => {
    const result = await sendKiroHookEvent({
      hookEventName: "postToolUse",
      sessionId: `kiro-camel-fields-${Date.now()}`,
      toolName: "Bash",
      toolInput: JSON.stringify({ command: "ls -la" }),
      toolResponse: "total 0",
    });
    expect(result.ingested).toBe(1);
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

  test("accepts SubagentStart hook event from Kiro", async () => {
    const result = await sendKiroHookEvent({
      hook_event_name: "SubagentStart",
      session_id: `kiro-subagent-${Date.now()}`,
      tool_name: "research-agent",
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
});
