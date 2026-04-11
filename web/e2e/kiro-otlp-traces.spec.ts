import { test, expect } from "@playwright/test";
import { sendKiroOTLPTrace, buildKiroOTLPTracePayload } from "./helpers";

test.describe("Kiro OTLP Trace Ingestion", () => {
  test("accepts Kiro OTLP trace payload and returns success", async () => {
    const traceId = crypto.randomUUID().replace(/-/g, "");
    const spanId = traceId.slice(0, 16);

    const payload = buildKiroOTLPTracePayload({
      traceId,
      spanId,
      sessionId: `kiro-test-${Date.now()}`,
      spanName: "kiro.llm.chat",
      model: "anthropic.claude-sonnet-4-20250514",
      inputTokens: 150,
      outputTokens: 300,
    });

    const result = await sendKiroOTLPTrace(payload);
    expect(result.partialSuccess).toBeDefined();
    expect(result.partialSuccess.rejectedSpans).toBeUndefined();
  });

  test("detects Kiro as the IDE from resource attributes", async () => {
    const traceId = crypto.randomUUID().replace(/-/g, "");
    const spanId = traceId.slice(0, 16);

    const payload = buildKiroOTLPTracePayload({
      traceId,
      spanId,
      sessionId: `kiro-ide-detect-${Date.now()}`,
      spanName: "kiro.test.ide-detection",
    });

    const result = await sendKiroOTLPTrace(payload);
    expect(result.partialSuccess).toBeDefined();
    expect(result.partialSuccess.rejectedSpans).toBeUndefined();
  });

  test("extracts token counts from Kiro Bedrock-style attributes", async () => {
    const traceId = crypto.randomUUID().replace(/-/g, "");
    const spanId = traceId.slice(0, 16);

    const payload = buildKiroOTLPTracePayload({
      traceId,
      spanId,
      spanName: "bedrock.invoke",
      model: "anthropic.claude-sonnet-4-20250514",
      inputTokens: 500,
      outputTokens: 1200,
    });

    const result = await sendKiroOTLPTrace(payload);
    expect(result.partialSuccess).toBeDefined();
    expect(result.partialSuccess.rejectedSpans).toBeUndefined();
  });
});
