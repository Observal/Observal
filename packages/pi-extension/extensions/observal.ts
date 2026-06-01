// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

/**
 * Observal session telemetry extension for Pi.
 *
 * Reads the session JSONL file incrementally on lifecycle events and POSTs
 * raw lines to the Observal ingest API. Zero runtime dependencies - uses
 * only node:* built-ins.
 *
 * Design principles:
 * - Fail-open: never throw, never crash pi
 * - 5s timeout on all HTTP calls
 * - Generation counter for async safety
 * - Byte offset tracking (same model as CLI hooks)
 * - Chunk at 500 lines per POST to avoid 413
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import * as fs from "node:fs";
import * as http from "node:http";
import * as https from "node:https";
import * as os from "node:os";
import * as path from "node:path";

// ─── Types ───────────────────────────────────────────────────────────────────

interface ObservalConfig {
  server_url: string;
  access_token: string;
  agent_id?: string;
  agent_version?: string;
}

interface CursorEntry {
  offset: number;
  line_count: number;
  finalized?: boolean;
  last_pushed_at?: number;
}

interface ObservalState {
  config: ObservalConfig | null;
  sessionFile: string | null;
  sessionId: string;
  byteOffset: number;
  lineCount: number;
  generation: number;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const OBSERVAL_DIR = path.join(os.homedir(), ".observal");
const CONFIG_PATH = path.join(OBSERVAL_DIR, "config.json");
const SYNC_STATE_PATH = path.join(OBSERVAL_DIR, "sync_state.json");
const TIMEOUT_MS = 5_000;
const MAX_LINES_PER_CHUNK = 500;
const RECOVERY_MAX_SESSIONS = 5;
const RECOVERY_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

// ─── Extension Entry ─────────────────────────────────────────────────────────

export default function (pi: ExtensionAPI) {
  let state: ObservalState | null = null;

  pi.on("session_start", async (event, ctx) => {
    state = initState(ctx);

    // On fresh startup, attempt crash recovery (fire-and-forget)
    if (event.reason === "startup" && state.config) {
      recoverStaleSessions(state, ctx).catch(() => {});
    }

    if (state.config && ctx.hasUI) {
      const theme = ctx.ui.theme;
      ctx.ui.setStatus("observal", theme.fg("dim", "● observal"));
    }
  });

  pi.on("agent_end", async (_event, _ctx) => {
    if (!state?.config || !state.sessionFile) return;
    await pushNewLines(state, { final: false });
  });

  pi.on("session_shutdown", async (_event, _ctx) => {
    if (!state?.config || !state.sessionFile) return;
    await pushNewLines(state, { final: true });
    state = null;
  });

  // ─── /obs-sync command ─────────────────────────────────────────────────

  pi.registerCommand("obs-sync", {
    description: "Observal telemetry sync status",
    handler: async (args, ctx) => {
      const sub = args.trim();
      if (sub === "flush") {
        if (!state?.config || !state.sessionFile) {
          ctx.ui.notify("No active session or config", "warning");
          return;
        }
        await pushNewLines(state, { final: false });
        ctx.ui.notify(`Flushed (${state.lineCount} lines total)`, "info");
      } else if (sub === "config") {
        ctx.ui.notify(
          `Config: ${CONFIG_PATH}\nServer: ${state?.config?.server_url ?? "not configured"}`,
          "info",
        );
      } else {
        const synced = state?.lineCount ?? 0;
        const server = state?.config?.server_url ?? "not configured";
        ctx.ui.notify(`Observal: ${synced} lines pushed\nServer: ${server}`, "info");
      }
    },
  });

  // ─── Helpers ─────────────────────────────────────────────────────────────

  function initState(ctx: ExtensionContext): ObservalState {
    const config = loadConfig();
    const sessionFile = ctx.sessionManager.getSessionFile() ?? null;
    const sessionId = ctx.sessionManager.getSessionId();

    let byteOffset = 0;
    let lineCount = 0;

    if (sessionId) {
      const cursor = readCursor(sessionId);
      byteOffset = cursor.offset;
      lineCount = cursor.line_count;
    }

    return { config, sessionFile, sessionId, byteOffset, lineCount, generation: 0 };
  }

  function loadConfig(): ObservalConfig | null {
    try {
      if (!fs.existsSync(CONFIG_PATH)) return null;
      const raw = fs.readFileSync(CONFIG_PATH, "utf-8");
      const data = JSON.parse(raw);
      if (!data.server_url || !data.access_token) return null;
      const config: ObservalConfig = { server_url: data.server_url, access_token: data.access_token };
      if (data.active_agent?.id) config.agent_id = data.active_agent.id;
      if (data.active_agent?.version) config.agent_version = data.active_agent.version;
      return config;
    } catch {
      return null;
    }
  }

  function readCursor(sessionId: string): CursorEntry {
    try {
      if (!fs.existsSync(SYNC_STATE_PATH)) return { offset: 0, line_count: 0 };
      const data = JSON.parse(fs.readFileSync(SYNC_STATE_PATH, "utf-8"));
      return data[sessionId] ?? { offset: 0, line_count: 0 };
    } catch {
      return { offset: 0, line_count: 0 };
    }
  }

  function writeCursor(sessionId: string, offset: number, lineCount: number, finalized = false): void {
    try {
      fs.mkdirSync(OBSERVAL_DIR, { recursive: true });
      let data: Record<string, CursorEntry> = {};
      if (fs.existsSync(SYNC_STATE_PATH)) {
        data = JSON.parse(fs.readFileSync(SYNC_STATE_PATH, "utf-8"));
      }
      data[sessionId] = { offset, line_count: lineCount, finalized, last_pushed_at: Date.now() };
      fs.writeFileSync(SYNC_STATE_PATH, JSON.stringify(data, null, 2));
    } catch {
      // Fail-open
    }
  }

  async function pushNewLines(s: ObservalState, opts: { final: boolean }): Promise<void> {
    if (!s.config || !s.sessionFile) return;

    const gen = ++s.generation;

    try {
      const stat = fs.statSync(s.sessionFile);
      const newBytes = stat.size - s.byteOffset;

      if (newBytes <= 0) {
        if (opts.final) writeCursor(s.sessionId, s.byteOffset, s.lineCount, true);
        return;
      }

      const buffer = Buffer.alloc(newBytes);
      const fd = fs.openSync(s.sessionFile, "r");
      fs.readSync(fd, buffer, 0, newBytes, s.byteOffset);
      fs.closeSync(fd);

      if (s.generation !== gen) return; // stale

      const text = buffer.toString("utf-8");
      const rawLines = text.split("\n");

      // Only consume complete lines (discard partial last line)
      const lines: string[] = [];
      let consumedBytes = 0;
      for (let i = 0; i < rawLines.length; i++) {
        const line = rawLines[i]!;
        if (i === rawLines.length - 1) {
          // Last element after split: either empty (file ended with \n)
          // or an incomplete line (file didn't end with \n). Either way, stop.
          break;
        }
        if (line.trim()) {
          lines.push(line);
        }
        consumedBytes += Buffer.byteLength(line, "utf-8") + 1; // +1 for \n
      }

      if (lines.length === 0 && !opts.final) return;

      // Chunk large batches
      for (let offset = 0; offset < lines.length; offset += MAX_LINES_PER_CHUNK) {
        if (s.generation !== gen) return; // stale

        const chunk = lines.slice(offset, offset + MAX_LINES_PER_CHUNK);
        const isLastChunk = offset + MAX_LINES_PER_CHUNK >= lines.length;

        const payload = JSON.stringify({
          session_id: s.sessionId,
          ide: "pi",
          agent_id: s.config!.agent_id ?? null,
          agent_version: s.config!.agent_version ?? null,
          lines: chunk,
          start_offset: s.lineCount + offset,
          hook_event: opts.final && isLastChunk ? "SessionShutdown" : "AgentEnd",
          final: opts.final && isLastChunk,
          ...(opts.final && isLastChunk
            ? {
                total_line_count: s.lineCount + lines.length,
                total_offset: s.byteOffset + consumedBytes,
              }
            : {}),
        });

        const ok = await postWithTimeout(s.config!, "/api/v1/ingest/session", payload);
        if (!ok) break; // stop chunking on failure, retry next time
      }

      if (s.generation !== gen) return; // stale

      // Update state
      s.byteOffset += consumedBytes;
      s.lineCount += lines.length;
      writeCursor(s.sessionId, s.byteOffset, s.lineCount, opts.final);
    } catch {
      // Fail-open
    }
  }

  function postWithTimeout(config: ObservalConfig, urlPath: string, body: string): Promise<boolean> {
    return new Promise((resolve) => {
      try {
        const url = new URL(urlPath, config.server_url);
        const mod = url.protocol === "https:" ? https : http;
        const timer = setTimeout(() => {
          req.destroy();
          resolve(false);
        }, TIMEOUT_MS);

        const req = mod.request(
          url,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${config.access_token}`,
              "Content-Length": String(Buffer.byteLength(body)),
            },
          },
          (res) => {
            clearTimeout(timer);
            res.resume(); // drain response
            resolve(res.statusCode! >= 200 && res.statusCode! < 300);
          },
        );

        req.on("error", () => {
          clearTimeout(timer);
          resolve(false);
        });

        req.write(body);
        req.end();
      } catch {
        resolve(false);
      }
    });
  }

  async function recoverStaleSessions(s: ObservalState, ctx: ExtensionContext): Promise<void> {
    try {
      if (!fs.existsSync(SYNC_STATE_PATH) || !s.config) return;
      const data: Record<string, CursorEntry> = JSON.parse(
        fs.readFileSync(SYNC_STATE_PATH, "utf-8"),
      );

      // Use sessionManager to resolve session directory when available,
      // falling back to the conventional path layout.
      const sessionsDir = ctx.sessionManager.getSessionsDir?.()
        ?? path.join(os.homedir(), ".pi", "agent", "sessions");
      const cwd = ctx.cwd;
      const projectKey = cwd.replace(/\//g, "-");
      const fullDir = path.join(sessionsDir, `-${projectKey}-`);

      if (!fs.existsSync(fullDir)) return;

      let recovered = 0;
      const now = Date.now();

      for (const [sessionId, entry] of Object.entries(data)) {
        if (entry.finalized) continue;
        if (sessionId === s.sessionId) continue; // current session
        if (recovered >= RECOVERY_MAX_SESSIONS) break;

        // Find the JSONL file for this session
        const files = fs.readdirSync(fullDir).filter((f) => f.includes(sessionId));
        if (files.length === 0) continue;

        const filePath = path.join(fullDir, files[0]!);
        if (!fs.existsSync(filePath)) continue;

        // Skip sessions older than 7 days
        const fileStat = fs.statSync(filePath);
        if (now - fileStat.mtimeMs > RECOVERY_MAX_AGE_MS) {
          writeCursor(sessionId, entry.offset, entry.line_count, true);
          continue;
        }

        if (fileStat.size <= entry.offset) {
          writeCursor(sessionId, entry.offset, entry.line_count, true);
          continue;
        }

        const fd = fs.openSync(filePath, "r");
        const buffer = Buffer.alloc(fileStat.size - entry.offset);
        fs.readSync(fd, buffer, 0, buffer.length, entry.offset);
        fs.closeSync(fd);

        const lines = buffer
          .toString("utf-8")
          .split("\n")
          .filter((l) => l.trim());

        if (lines.length > 0) {
          let pushOk = true;
          for (let offset = 0; offset < lines.length; offset += MAX_LINES_PER_CHUNK) {
            const chunk = lines.slice(offset, offset + MAX_LINES_PER_CHUNK);
            const isLastChunk = offset + MAX_LINES_PER_CHUNK >= lines.length;
            const payload = JSON.stringify({
              session_id: sessionId,
              ide: "pi",
              agent_id: s.config?.agent_id ?? null,
              agent_version: s.config?.agent_version ?? null,
              lines: chunk,
              start_offset: entry.line_count + offset,
              hook_event: "CrashRecovery",
              final: isLastChunk,
              ...(isLastChunk
                ? {
                    total_line_count: entry.line_count + lines.length,
                    total_offset: fileStat.size,
                  }
                : {}),
            });
            const ok = await postWithTimeout(s.config!, "/api/v1/ingest/session", payload);
            if (!ok) { pushOk = false; break; }
          }
          if (!pushOk) continue; // skip finalization, retry next startup
        }

        writeCursor(sessionId, fileStat.size, entry.line_count + lines.length, true);
        recovered++;
      }

      // Prune old finalized entries from sync_state.json
      pruneSyncState();
    } catch {
      // Fail-open
    }
  }

  function pruneSyncState(): void {
    try {
      if (!fs.existsSync(SYNC_STATE_PATH)) return;
      const data: Record<string, CursorEntry> = JSON.parse(
        fs.readFileSync(SYNC_STATE_PATH, "utf-8"),
      );
      const entries = Object.entries(data);
      if (entries.length <= 50) return; // No pruning needed

      // Keep only the 50 most recent entries (by last push time, falling back to offset)
      const sorted = entries.sort((a, b) => (b[1].last_pushed_at ?? 0) - (a[1].last_pushed_at ?? 0));
      const pruned: Record<string, CursorEntry> = {};
      for (const [key, value] of sorted.slice(0, 50)) {
        pruned[key] = value;
      }
      fs.writeFileSync(SYNC_STATE_PATH, JSON.stringify(pruned, null, 2));
    } catch {
      // Fail-open
    }
  }
}
