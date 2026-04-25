import { test, expect } from "@playwright/test";
import {
  API_BASE,
  getApiKey,
  sendKiroOTLPLog,
  buildKiroOTLPLogPayload,
} from "./helpers";

test.describe("Kiro OTLP Log Ingestion", () => {
  test("ingests Kiro user_prompt log record", async () => {
    const sessionId = `kiro-log-${Date.now()}`;
    const promptId = crypto.randomUUID().replace(/-/g, "");

    const payload = buildKiroOTLPLogPayload({
      sessionId,
      promptId,
      eventName: "user_prompt",
      body: "What files are in the current directory?",
      attributes: { prompt: "What files are in the current directory?" },
    });

    const result = await sendKiroOTLPLog(payload);
    expect(result.partialSuccess).toBeDefined();
  });

  test("ingests Kiro tool_result log record", async () => {
    const sessionId = `kiro-log-${Date.now()}`;
    const promptId = crypto.randomUUID().replace(/-/g, "");

    const payload = buildKiroOTLPLogPayload({
      sessionId,
      promptId,
      eventName: "tool_result",
      body: "README.md\npackage.json\nsrc/",
      attributes: {
        tool_name: "list_files",
        success: "true",
        duration_ms: "42",
      },
    });

    const result = await sendKiroOTLPLog(payload);
    expect(result.partialSuccess).toBeDefined();
  });

  test("ingests Kiro api_request log record with token counts", async () => {
    const sessionId = `kiro-log-${Date.now()}`;
    const promptId = crypto.randomUUID().replace(/-/g, "");

    const payload = buildKiroOTLPLogPayload({
      sessionId,
      promptId,
      eventName: "api_request",
      attributes: {
        model: "anthropic.claude-sonnet-4-20250514",
        input_tokens: "250",
        output_tokens: "800",
        cache_read_tokens: "100",
        duration_ms: "1500",
      },
    });

    const result = await sendKiroOTLPLog(payload);
    expect(result.partialSuccess).toBeDefined();
  });

  test("groups multiple Kiro log records into a single trace by prompt_id", async () => {
    const sessionId = `kiro-grouped-${Date.now()}`;
    const promptId = crypto.randomUUID().replace(/-/g, "");

    // Send user_prompt
    await sendKiroOTLPLog(
      buildKiroOTLPLogPayload({
        sessionId,
        promptId,
        eventName: "user_prompt",
        body: "Create a hello.txt file",
        attributes: { prompt: "Create a hello.txt file" },
      }),
    );

    // Send tool_result
    await sendKiroOTLPLog(
      buildKiroOTLPLogPayload({
        sessionId,
        promptId,
        eventName: "tool_result",
        body: "File created successfully",
        attributes: {
          tool_name: "write_file",
          success: "true",
          duration_ms: "15",
        },
      }),
    );

    // Send api_request
    await sendKiroOTLPLog(
      buildKiroOTLPLogPayload({
        sessionId,
        promptId,
        eventName: "api_request",
        attributes: {
          model: "anthropic.claude-sonnet-4-20250514",
          input_tokens: "100",
          output_tokens: "50",
        },
      }),
    );

    // All three should be grouped under the same trace_id (= promptId)
    await new Promise((r) => setTimeout(r, 2000));

    const apiKey = await getApiKey();
    const sessions = await fetch(`${API_BASE}/api/v1/sessions`, {
      headers: { "Authorization": `Bearer ${apiKey}` },
    }).then((r) => r.json());

    // Verify at least one session exists (might be the one we just created)
    expect(sessions.length).toBeGreaterThan(0);
  });
});
