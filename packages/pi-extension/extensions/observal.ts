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
import * as crypto from "node:crypto";
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

interface LayerFileEntry {
  path: string;
  hash: string;
  size: number;
  source: string;
  content?: string;
}

interface LayerSnapshot {
  hash: string;
  harnesses: Record<string, LayerFileEntry[]>;
  lockfile_hash: string;
  pinned_versions: Record<string, unknown>;
  drift: Record<string, unknown>;
}

interface ObservalState {
  config: ObservalConfig | null;
  sessionFile: string | null;
  sessionId: string;
  byteOffset: number;
  lineCount: number;
  generation: number;
  layerHash: string | null;
  layerSnapshot: LayerSnapshot | null;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const OBSERVAL_DIR = path.join(os.homedir(), ".observal");
const CONFIG_PATH = path.join(OBSERVAL_DIR, "config.json");
const SYNC_STATE_PATH = path.join(OBSERVAL_DIR, "sync_state.json");
const LAYER_SNAPSHOT_PATH = path.join(OBSERVAL_DIR, "layer_snapshot.json");
const LOCKFILE_PATH = path.join(OBSERVAL_DIR, "lockfile.json");
const TIMEOUT_MS = 5_000;
const MAX_LINES_PER_CHUNK = 500;
const RECOVERY_MAX_SESSIONS = 5;
const RECOVERY_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000; // 7 days
const MAX_LAYER_FILE_SIZE = 512 * 1024;

// ─── Extension Entry ─────────────────────────────────────────────────────────

export default function (pi: ExtensionAPI) {
  let state: ObservalState | null = null;

  pi.on("session_start", async (event, ctx) => {
    state = initState(ctx);

    if (state.config && state.layerSnapshot) {
      uploadLayerSnapshot(state.config, state.layerSnapshot)
        .then((ok) => {
          if (!ok && ctx.hasUI) ctx.ui.notify("Layer snapshot upload failed", "warning");
        })
        .catch((err) => {
          if (ctx.hasUI) ctx.ui.notify(`Layer snapshot upload failed: ${err.message}`, "warning");
        });
    }

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

  pi.registerCommand("agent", {
    description: "Manage and swap active Observal agents",
    handler: async (args, ctx) => {
      const agentId = args.trim();
      const PI_HOME = path.join(os.homedir(), ".pi", "agent");
      const AGENTS_DIR = path.join(PI_HOME, "agents");

      function backupDefault() {
        if (!fs.existsSync(AGENTS_DIR)) fs.mkdirSync(AGENTS_DIR, { recursive: true });
        const defaultDir = path.join(AGENTS_DIR, "default");
        if (fs.existsSync(defaultDir)) return; // already backed up
        
        fs.mkdirSync(defaultDir, { recursive: true });
        
        const filesToCopy = [
          { name: "AGENTS.md", isDir: false },
          { name: "SYSTEM.md", isDir: false },
          { name: "mcp.json", isDir: false },
          { name: "skills", isDir: true },
          { name: "sandboxes", isDir: true }
        ];
        
        for (const f of filesToCopy) {
          const src = path.join(PI_HOME, f.name);
          const dest = path.join(defaultDir, f.name);
          if (fs.existsSync(src)) {
            fs.cpSync(src, dest, { recursive: true });
          }
        }
      }

      function applyProfile(name: string) {
        const profileDir = path.join(AGENTS_DIR, name);
        if (!fs.existsSync(profileDir)) throw new Error(`Profile ${name} not found`);

        const activeItems = ["AGENTS.md", "SYSTEM.md", "mcp.json", "skills", "sandboxes"];
        for (const f of activeItems) {
          const target = path.join(PI_HOME, f);
          if (fs.existsSync(target)) {
            fs.rmSync(target, { recursive: true, force: true });
          }
        }

        for (const f of activeItems) {
          const src = path.join(profileDir, f);
          const dest = path.join(PI_HOME, f);
          if (fs.existsSync(src)) {
            fs.cpSync(src, dest, { recursive: true });
          }
        }
      }

      if (!fs.existsSync(AGENTS_DIR)) {
        fs.mkdirSync(AGENTS_DIR, { recursive: true });
      }

      // Automatically populate AGENTS_DIR from normal .pi/agent files if it's currently holding an active agent but no profile exists for it
      // but primarily we rely on observal agent pull populating agents/.
      backupDefault();

      let choice = agentId;

      if (!choice) {
        const profiles = fs.readdirSync(AGENTS_DIR).filter(d => fs.statSync(path.join(AGENTS_DIR, d)).isDirectory());
        if (profiles.length === 0) {
          ctx.ui.notify("No agents installed yet. Use the Observal skill or 'observal agent pull <agent> --harness pi' to install one.", "info");
          return;
        }

        const selected = await ctx.ui.select("Select agent to swap to:", profiles);
        if (!selected) return;
        choice = selected;
      }

      try {
        applyProfile(choice);
        
        if (state?.config) {
          const binding = resolvePiAgentBinding(choice);
          state.config.agent_id = choice === "default" ? undefined : binding.id;
          state.config.agent_version = choice === "default" ? undefined : binding.version;
          try {
            const configRaw = fs.readFileSync(CONFIG_PATH, "utf-8");
            const configJson = JSON.parse(configRaw);
            if (choice === "default") {
              delete configJson.active_agent;
            } else {
              configJson.active_agent = {
                id: binding.id,
                name: binding.name,
                ...(binding.version ? { version: binding.version } : {}),
              };
            }
            fs.writeFileSync(CONFIG_PATH, JSON.stringify(configJson, null, 2));
          } catch (err) {
            // ignore
          }

          state.layerSnapshot = buildPiLayerSnapshot(true);
          state.layerHash = state.layerSnapshot.hash;
          if (!(await uploadLayerSnapshot(state.config, state.layerSnapshot))) {
            ctx.ui.notify("Layer snapshot upload failed", "warning");
          }
        }

        const ok = await ctx.ui.confirm("Agent Swapped", `Swapped to ${choice}. Reload session now?`);
        if (ok) {
          await ctx.reload();
        }
      } catch (e: any) {
        ctx.ui.notify(`Error swapping agent: ${e.message}`, "error");
      }
    },
  });

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

    const layerSnapshot = buildPiLayerSnapshot(true);
    const layerHash = layerSnapshot.hash;

    return { config, sessionFile, sessionId, byteOffset, lineCount, generation: 0, layerHash, layerSnapshot };
  }

  function loadConfig(): ObservalConfig | null {
    try {
      if (!fs.existsSync(CONFIG_PATH)) return null;
      const raw = fs.readFileSync(CONFIG_PATH, "utf-8");
      const data = JSON.parse(raw);
      if (!data.server_url || !data.access_token) return null;
      const config: ObservalConfig = { server_url: data.server_url, access_token: data.access_token };
      if (data.active_agent?.id) {
        const binding = resolvePiAgentBinding(String(data.active_agent.id), data.active_agent.name, data.active_agent.version);
        config.agent_id = binding.id;
        if (binding.version) config.agent_version = binding.version;
      }
      return config;
    } catch {
      return null;
    }
  }

  function resolvePiAgentBinding(agent: string, rawName?: unknown, rawVersion?: unknown): { id: string; name: string; version?: string } {
    const name = typeof rawName === "string" && rawName.trim() ? rawName.trim() : agent;
    const entry = findPiLockfileAgent(agent, name);
    return {
      id: typeof entry?.id === "string" && entry.id.trim() ? entry.id : agent,
      name: typeof entry?.name === "string" && entry.name.trim() ? entry.name : name,
      version: normalizeAgentVersion(entry?.version) ?? normalizeAgentVersion(rawVersion),
    };
  }

  function findPiLockfileAgent(agent: string, name: string): Record<string, any> | null {
    try {
      if (!fs.existsSync(LOCKFILE_PATH)) return null;
      const data = JSON.parse(fs.readFileSync(LOCKFILE_PATH, "utf-8"));
      const agents = data.harnesses?.pi?.agents;
      if (!Array.isArray(agents)) return null;
      const keys = new Set([agent, name, safeAgentName(agent), safeAgentName(name)].filter(Boolean));
      return agents.find((item) => keys.has(String(item?.id ?? "")))
        ?? agents.find((item) => keys.has(String(item?.name ?? "")) || keys.has(safeAgentName(String(item?.name ?? ""))))
        ?? null;
    } catch {
      return null;
    }
  }

  function normalizeAgentVersion(version: unknown): string | undefined {
    if (typeof version !== "string") return undefined;
    const trimmed = version.trim();
    return trimmed && trimmed !== "latest" ? trimmed : undefined;
  }

  function safeAgentName(name: string): string {
    return name.replace(/[^a-zA-Z0-9_-]/g, "-");
  }

  function buildPiLayerSnapshot(includeContent: boolean): LayerSnapshot {
    const piHome = path.join(os.homedir(), ".pi", "agent");
    const files = discoverPiLayerFiles(piHome);
    const manifest: LayerFileEntry[] = [];

    for (const file of files) {
      try {
        const rel = path.relative(piHome, file).split(path.sep).join("/");
        const content = fs.readFileSync(file);
        const entry: LayerFileEntry = {
          path: `user:${rel}`,
          hash: `sha256-${sha256(content)}`,
          size: content.length,
          source: "user",
        };
        if (includeContent) {
          entry.content = content.toString("utf-8");
        }
        manifest.push(entry);
      } catch {
        continue;
      }
    }

    manifest.sort((a, b) => a.path.localeCompare(b.path));
    const hashEntries = manifest.map((entry) => [`pi/${entry.path}`, entry.hash] as [string, string]);
    const layerHash = hashEntries.length === 0 ? "0".repeat(16) : sha256(Buffer.from(pyJsonPairs(hashEntries))).slice(0, 16);

    return {
      hash: layerHash,
      harnesses: { pi: manifest },
      lockfile_hash: computeLockfileHash(),
      pinned_versions: readPinnedVersions(),
      drift: { is_canonical: true, drifted_files: [] },
    };
  }

  function discoverPiLayerFiles(root: string): string[] {
    if (!fs.existsSync(root)) return [];
    let rootReal: string;
    try {
      rootReal = fs.realpathSync(root);
    } catch {
      return [];
    }
    const found: string[] = [];
    const skipDirs = new Set([".git", "node_modules", "sessions"]);

    function walk(dir: string): void {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory() && skipDirs.has(entry.name)) continue;
        const abs = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(abs);
          continue;
        }
        if (!entry.isFile()) continue;

        const rel = path.relative(root, abs).split(path.sep).join("/");
        if (!isPiLayerFile(rel)) continue;

        try {
          const stat = fs.statSync(abs);
          if (stat.size > MAX_LAYER_FILE_SIZE) continue;
          const real = fs.realpathSync(abs);
          if (real !== rootReal && !real.startsWith(`${rootReal}${path.sep}`)) continue;
          found.push(abs);
        } catch {
          continue;
        }
      }
    }

    try {
      walk(root);
    } catch {
      return [];
    }

    return found.sort().slice(0, 200);
  }

  function isPiLayerFile(rel: string): boolean {
    return ["AGENTS.md", "SYSTEM.md", "APPEND_SYSTEM.md", "mcp.json", "settings.json"].includes(rel)
      || /^skills\/[^/]+\/SKILL\.md$/.test(rel)
      || rel.startsWith("sandboxes/")
      || /^agents\/[^/]+\/(AGENTS\.md|SYSTEM\.md|APPEND_SYSTEM\.md|mcp\.json)$/.test(rel)
      || /^agents\/[^/]+\/skills\/[^/]+\/SKILL\.md$/.test(rel)
      || /^agents\/[^/]+\/sandboxes\//.test(rel);
  }

  function sha256(content: Buffer): string {
    return crypto.createHash("sha256").update(content).digest("hex");
  }

  function pyJsonPairs(entries: [string, string][]): string {
    return `[${entries.map(([left, right]) => `[${JSON.stringify(left)}, ${JSON.stringify(right)}]`).join(", ")}]`;
  }

  function computeLockfileHash(): string {
    try {
      if (!fs.existsSync(LOCKFILE_PATH)) return "0".repeat(16);
      return sha256(fs.readFileSync(LOCKFILE_PATH)).slice(0, 16);
    } catch {
      return "0".repeat(16);
    }
  }

  function readPinnedVersions(): Record<string, unknown> {
    try {
      if (!fs.existsSync(LOCKFILE_PATH)) return { agents: [], standalone: [] };
      const data = JSON.parse(fs.readFileSync(LOCKFILE_PATH, "utf-8"));
      const agents: Record<string, unknown>[] = [];
      const standalone: Record<string, unknown>[] = [];
      for (const [harness, section] of Object.entries((data.harnesses ?? {}) as Record<string, any>)) {
        for (const agent of section.agents ?? []) {
          agents.push({ ...agent, harness });
        }
        for (const item of section.standalone ?? []) {
          standalone.push({ ...item, harness });
        }
      }
      return { agents, standalone };
    } catch {
      return { agents: [], standalone: [] };
    }
  }

  function needsLayerUpload(hash: string): boolean {
    try {
      if (!fs.existsSync(LAYER_SNAPSHOT_PATH)) return true;
      const data = JSON.parse(fs.readFileSync(LAYER_SNAPSHOT_PATH, "utf-8"));
      return data.hash !== hash;
    } catch {
      return true;
    }
  }

  function saveLayerSnapshot(snapshot: LayerSnapshot): void {
    try {
      const serialized = JSON.stringify(snapshot, null, 2);
      if (serialized.length > 5 * 1024 * 1024) return;
      fs.mkdirSync(OBSERVAL_DIR, { recursive: true });
      fs.writeFileSync(LAYER_SNAPSHOT_PATH, `${serialized}\n`);
    } catch {
      return;
    }
  }

  async function uploadLayerSnapshot(config: ObservalConfig, snapshot: LayerSnapshot): Promise<boolean> {
    if (!needsLayerUpload(snapshot.hash)) return true;
    const result = await postJsonWithTimeout(config, "/api/v1/layer-snapshots", JSON.stringify(snapshot));
    if (result?.hash !== snapshot.hash) return false;
    saveLayerSnapshot(snapshot);
    return true;
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
          harness: "pi",
          agent_id: s.config!.agent_id ?? null,
          agent_version: s.config!.agent_version ?? null,
          layer_hash: s.layerHash,
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

  function postJsonWithTimeout(config: ObservalConfig, urlPath: string, body: string): Promise<any | null> {
    return new Promise((resolve) => {
      try {
        const url = new URL(urlPath, config.server_url);
        const mod = url.protocol === "https:" ? https : http;
        const timer = setTimeout(() => {
          req.destroy();
          resolve(null);
        }, TIMEOUT_MS * 2);

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
            const chunks: Buffer[] = [];
            res.on("data", (c) => chunks.push(c));
            res.on("end", () => {
              if (res.statusCode! >= 200 && res.statusCode! < 300) {
                try {
                  resolve(JSON.parse(Buffer.concat(chunks).toString("utf-8")));
                } catch {
                  resolve(null);
                }
              } else {
                resolve(null);
              }
            });
          },
        );

        req.on("error", () => {
          clearTimeout(timer);
          resolve(null);
        });

        req.write(body);
        req.end();
      } catch {
        resolve(null);
      }
    });
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
      const sessionsDir = (ctx.sessionManager as any).getSessionDir?.()
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
              harness: "pi",
              agent_id: s.config?.agent_id ?? null,
              agent_version: s.config?.agent_version ?? null,
              layer_hash: s.layerHash,
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
