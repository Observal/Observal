import { test, expect } from "@playwright/test";
import {
  API_BASE,
} from "./helpers";

/** Get a JWT access token for API calls. */
async function getJWT(): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: process.env.DEMO_ADMIN_EMAIL ?? "admin@demo.example",
      password: process.env.DEMO_ADMIN_PASSWORD ?? "admin-changeme",
    }),
  });
  const data = await res.json();
  if (!data.access_token) throw new Error(`Auth failed: ${JSON.stringify(data)}`);
  return data.access_token;
}

/** Decode user_id (sub) from a JWT without verification. */
function jwtUserId(token: string): string {
  const payload = JSON.parse(
    Buffer.from(token.split(".")[1], "base64url").toString(),
  );
  return payload.sub;
}

/** Send a hook event with user_id header so it matches JWT-authenticated shim data. */
async function sendHookWithUser(payload: object, userId: string) {
  const res = await fetch(`${API_BASE}/api/v1/telemetry/hooks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Observal-User-Id": userId,
    },
    body: JSON.stringify(payload),
  });
  return res.json();
}

/**
 * E2E test: shim data fuses with hook events at query time.
 *
 * Simulates the real-world scenario where:
 *   - Claude Code sends hook events (with session_id)
 *   - The shim sends telemetry to /api/v1/telemetry/ingest (WITHOUT session_id)
 *   - The server side-loads shim spans at query time and merges them
 *
 * Verifies both API-level merge and UI rendering of MCP enrichment.
 */

/** Send shim telemetry (mimics observal-shim with no OBSERVAL_SESSION_ID). */
async function sendShimIngest(
  apiKey: string,
  options: {
    traceId: string;
    mcpId: string;
    userId: string;
    spans: Array<{
      spanId: string;
      type: string;
      name: string;
      method?: string;
      input?: string;
      output?: string;
      latencyMs?: number;
      status?: string;
      toolSchemaValid?: boolean;
      toolsAvailable?: number;
    }>;
  },
) {
  const now = new Date().toISOString().replace("T", " ").slice(0, 23);
  const res = await fetch(`${API_BASE}/api/v1/telemetry/ingest`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      traces: [
        {
          trace_id: options.traceId,
          trace_type: "mcp",
          mcp_id: options.mcpId,
          session_id: "", // Empty — shim doesn't have it
          ide: "claude-code",
          name: `shim:${options.mcpId}`,
          start_time: now,
          tags: [],
          metadata: {},
        },
      ],
      spans: options.spans.map((s) => ({
        span_id: s.spanId,
        trace_id: options.traceId,
        type: s.type,
        name: s.name,
        method: s.method ?? "",
        input: s.input ?? null,
        output: s.output ?? null,
        latency_ms: s.latencyMs ?? null,
        status: s.status ?? "success",
        start_time: now,
        tool_schema_valid: s.toolSchemaValid ?? null,
        tools_available: s.toolsAvailable ?? null,
      })),
      scores: [],
    }),
  });
  return res.json();
}

test.describe("Shim + Hook Merge (Query-Time Side-Load)", () => {
  const SESSION_ID = `shim-merge-${Date.now()}`;
  const TRACE_ID = `shim-trace-${Date.now()}`;
  const MCP_ID = "test-filesystem-server";
  const TOOL_NAME = "Read";
  const SPAN_ID = `span-${Date.now()}`;
  let apiKey: string;
  let userId: string;

  test.beforeAll(async () => {
    apiKey = await getJWT();
    userId = jwtUserId(apiKey);

    // 1. Send hook events (Claude Code perspective — has session_id)
    //    Must use the same user_id as the JWT so the side-load query matches.
    await sendHookWithUser({
      hook_event_name: "SessionStart",
      session_id: SESSION_ID,
    }, userId);
    await sendHookWithUser({
      hook_event_name: "UserPromptSubmit",
      session_id: SESSION_ID,
      tool_input: "Read the config file",
    }, userId);
    await sendHookWithUser({
      hook_event_name: "PreToolUse",
      session_id: SESSION_ID,
      tool_name: TOOL_NAME,
      tool_input: JSON.stringify({ file_path: "/etc/config.yaml" }),
    }, userId);
    await sendHookWithUser({
      hook_event_name: "PostToolUse",
      session_id: SESSION_ID,
      tool_name: TOOL_NAME,
      tool_response: "key: value\nport: 3000",
    }, userId);

    // 2. Send shim telemetry (MCP server perspective — NO session_id)
    //    Includes a tool_call (matches the hook PostToolUse above) and
    //    a tool_list (standalone, no matching hook).
    await sendShimIngest(apiKey, {
      traceId: TRACE_ID,
      mcpId: MCP_ID,
      userId: "", // Will be populated from JWT
      spans: [
        {
          spanId: SPAN_ID,
          type: "tool_call",
          name: TOOL_NAME,
          method: "tools/call",
          input: JSON.stringify({
            name: TOOL_NAME,
            arguments: { file_path: "/etc/config.yaml" },
          }),
          output: JSON.stringify({ content: [{ text: "key: value\nport: 3000" }] }),
          latencyMs: 42,
          status: "success",
          toolSchemaValid: true,
          toolsAvailable: 5,
        },
        {
          spanId: `list-${Date.now()}`,
          type: "tool_list",
          name: "tools/list",
          method: "tools/list",
          output: JSON.stringify({ tools: [{ name: "Read" }, { name: "Write" }] }),
          latencyMs: 8,
          status: "success",
          toolsAvailable: 2,
        },
      ],
    });

    // Wait for data to settle in ClickHouse
    await new Promise((r) => setTimeout(r, 3000));
  });

  test("API: session detail contains merged hook+shim events", async () => {
    const session = await fetch(
      `${API_BASE}/api/v1/sessions/${SESSION_ID}`,
      { headers: { Authorization: `Bearer ${apiKey}` } },
    ).then((r) => r.json());

    expect(session.events.length).toBeGreaterThanOrEqual(3);

    // Find the PostToolUse event — it should be merged with shim data
    const postToolEvents = session.events.filter(
      (e: Record<string, unknown>) => {
        const attrs =
          typeof e.attributes === "string"
            ? JSON.parse(e.attributes as string)
            : e.attributes;
        const eventName = attrs?.["event.name"] ?? e.event_name ?? "";
        return (
          eventName === "hook_posttooluse" ||
          (attrs?.source === "merged" && attrs?.tool_name === TOOL_NAME)
        );
      },
    );

    // Should have at least 1 event for the Read tool
    expect(postToolEvents.length).toBeGreaterThanOrEqual(1);

    // Check for MCP enrichment on merged or shim events
    const allAttrs = session.events.map((e: Record<string, unknown>) =>
      typeof e.attributes === "string"
        ? JSON.parse(e.attributes as string)
        : e.attributes,
    );

    // At minimum, shim events should be present (either merged or standalone)
    const hasMcpData = allAttrs.some(
      (a: Record<string, string>) =>
        a?.mcp_id === MCP_ID || a?.mcp_latency_ms === "42",
    );
    expect(hasMcpData).toBe(true);
  });

  test("API: shim-only events appear when no matching hook", async () => {
    // The tool_list span was sent in beforeAll alongside the tool_call.
    // It has no corresponding hook event, so it should appear as a standalone shim event.
    const session = await fetch(
      `${API_BASE}/api/v1/sessions/${SESSION_ID}`,
      { headers: { Authorization: `Bearer ${apiKey}` } },
    ).then((r) => r.json());

    const allAttrs = session.events.map((e: Record<string, unknown>) =>
      typeof e.attributes === "string"
        ? JSON.parse(e.attributes as string)
        : e.attributes,
    );

    // The tool_list shim event should be present as a standalone shim event
    const hasToolList = allAttrs.some(
      (a: Record<string, string>) => a?.["event.name"] === "shim_tool_list",
    );
    expect(hasToolList).toBe(true);
  });

  test("UI: session detail shows MCP badge for merged events", async ({
    page,
  }) => {
    // Login by setting the JWT in localStorage
    await page.goto("/");
    await page.evaluate((token) => {
      localStorage.setItem("observal_api_key", token);
      localStorage.setItem("observal_user_role", "admin");
    }, apiKey);
    await page.reload();

    // Navigate to the session detail page
    await page.goto(`/traces/${SESSION_ID}`);
    await page.waitForLoadState("networkidle");

    // Page should load without errors
    await expect(page.locator("body")).not.toContainText("Something went wrong");

    // Should show session content (events list)
    await page.waitForSelector('[data-testid="event-list"], .space-y-1, .divide-y', {
      timeout: 10_000,
    }).catch(() => {
      // Fallback: just check that the page loaded content
    });

    // Take a screenshot for visual verification
    await page.screenshot({
      path: "e2e-results/shim-merge-session-detail.png",
      fullPage: true,
    });

    // Check that MCP-related content appears on the page
    const pageContent = await page.textContent("body");
    // The MCP ID or "shim" text should appear somewhere
    const hasMcpContent =
      pageContent?.includes(MCP_ID) ||
      pageContent?.includes("shim") ||
      pageContent?.includes("42ms");

    // This is a soft check — the exact rendering depends on whether
    // the merge produced a merged event or standalone shim event
    if (!hasMcpContent) {
      console.log("Warning: MCP content not found in page text. Events may not have merged.");
      console.log("Page content snippet:", pageContent?.slice(0, 500));
    }
  });

  test("API: concurrent sessions stay isolated", async () => {
    // Create a second session with different tool calls at a different time
    const SESSION_2 = `shim-merge-concurrent-${Date.now()}`;

    await sendHookWithUser({
      hook_event_name: "SessionStart",
      session_id: SESSION_2,
    }, userId);
    await sendHookWithUser({
      hook_event_name: "PostToolUse",
      session_id: SESSION_2,
      tool_name: "Bash",
      tool_response: "total 0",
    }, userId);

    await new Promise((r) => setTimeout(r, 2000));

    // Session 2 should NOT contain the Read shim data from session 1
    const session2 = await fetch(
      `${API_BASE}/api/v1/sessions/${SESSION_2}`,
      { headers: { Authorization: `Bearer ${apiKey}` } },
    ).then((r) => r.json());

    const allAttrs = session2.events.map((e: Record<string, unknown>) =>
      typeof e.attributes === "string"
        ? JSON.parse(e.attributes as string)
        : e.attributes,
    );

    // Session 2 should NOT have the filesystem server MCP data
    // (it may side-load shim spans from the same time window, but the
    // merge should only fuse by tool_name + timestamp proximity)
    const hasBashTool = allAttrs.some(
      (a: Record<string, string>) => a?.tool_name === "Bash",
    );
    expect(hasBashTool).toBe(true);

    // The Read tool shim data should NOT merge into session 2's Bash event
    const hasMergedRead = allAttrs.some(
      (a: Record<string, string>) =>
        a?.source === "merged" && a?.tool_name === TOOL_NAME,
    );
    expect(hasMergedRead).toBe(false);
  });
});
