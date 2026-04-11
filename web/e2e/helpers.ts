import { Page } from "@playwright/test";

/** Base URL for the Observal API */
export const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

/** Get the API key from the Observal config */
export async function getApiKey(): Promise<string> {
  const { execSync } = await import("child_process");
  const config = JSON.parse(
    execSync("cat ~/.observal/config.json", { encoding: "utf-8" }),
  );
  return config.api_key;
}

/** Login to the web UI by setting localStorage */
export async function loginToWebUI(page: Page) {
  const apiKey = await getApiKey();
  await page.goto("/");
  await page.evaluate((key) => {
    localStorage.setItem("observal_api_key", key);
    localStorage.setItem("observal_user_role", "admin");
  }, apiKey);
  await page.reload();
}

/** Wait for API to be healthy */
export async function waitForAPI() {
  const { execSync } = await import("child_process");
  for (let i = 0; i < 30; i++) {
    try {
      execSync(`curl -sf ${API_BASE}/health`, { timeout: 5000 });
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  throw new Error("API not healthy after 60s");
}

/** Send a raw OTLP trace payload to simulate Kiro telemetry */
export async function sendKiroOTLPTrace(payload: object) {
  const res = await fetch(`${API_BASE}/v1/traces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

/** Send a raw OTLP log payload to simulate Kiro telemetry */
export async function sendKiroOTLPLog(payload: object) {
  const res = await fetch(`${API_BASE}/v1/logs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

/** Send a hook event payload to simulate Kiro hook firing */
export async function sendKiroHookEvent(payload: object) {
  const apiKey = await getApiKey();
  const res = await fetch(`${API_BASE}/api/v1/telemetry/hooks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
    },
    body: JSON.stringify(payload),
  });
  return res.json();
}

/** Build a realistic Kiro OTLP resourceSpans payload */
export function buildKiroOTLPTracePayload(options: {
  traceId: string;
  spanId: string;
  sessionId?: string;
  spanName: string;
  model?: string;
  inputTokens?: number;
  outputTokens?: number;
}) {
  return {
    resourceSpans: [
      {
        resource: {
          attributes: [
            { key: "service.name", value: { stringValue: "kiro" } },
            {
              key: "telemetry.sdk.name",
              value: { stringValue: "kiro-cli" },
            },
            ...(options.sessionId
              ? [
                  {
                    key: "session.id",
                    value: { stringValue: options.sessionId },
                  },
                ]
              : []),
          ],
        },
        scopeSpans: [
          {
            scope: { name: "kiro.telemetry" },
            spans: [
              {
                traceId: options.traceId,
                spanId: options.spanId,
                name: options.spanName,
                kind: 3, // CLIENT
                startTimeUnixNano: String(Date.now() * 1_000_000),
                endTimeUnixNano: String((Date.now() + 500) * 1_000_000),
                status: { code: 1 },
                attributes: [
                  ...(options.model
                    ? [
                        {
                          key: "gen_ai.request.model",
                          value: { stringValue: options.model },
                        },
                      ]
                    : []),
                  ...(options.inputTokens != null
                    ? [
                        {
                          key: "gen_ai.usage.input_tokens",
                          value: { intValue: String(options.inputTokens) },
                        },
                      ]
                    : []),
                  ...(options.outputTokens != null
                    ? [
                        {
                          key: "gen_ai.usage.output_tokens",
                          value: { intValue: String(options.outputTokens) },
                        },
                      ]
                    : []),
                ],
                events: [],
              },
            ],
          },
        ],
      },
    ],
  };
}

/** Build a realistic Kiro OTLP resourceLogs payload */
export function buildKiroOTLPLogPayload(options: {
  sessionId: string;
  promptId: string;
  eventName: string;
  body?: string;
  attributes?: Record<string, string>;
}) {
  const attrs = Object.entries(options.attributes ?? {}).map(([key, val]) => ({
    key,
    value: { stringValue: val },
  }));

  return {
    resourceLogs: [
      {
        resource: {
          attributes: [
            { key: "service.name", value: { stringValue: "kiro" } },
            {
              key: "session.id",
              value: { stringValue: options.sessionId },
            },
          ],
        },
        scopeLogs: [
          {
            scope: { name: "kiro.telemetry" },
            logRecords: [
              {
                timeUnixNano: String(Date.now() * 1_000_000),
                severityNumber: 9,
                body: { stringValue: options.body ?? "" },
                attributes: [
                  {
                    key: "event.name",
                    value: { stringValue: options.eventName },
                  },
                  {
                    key: "session.id",
                    value: { stringValue: options.sessionId },
                  },
                  {
                    key: "prompt.id",
                    value: { stringValue: options.promptId },
                  },
                  ...attrs,
                ],
              },
            ],
          },
        ],
      },
    ],
  };
}
