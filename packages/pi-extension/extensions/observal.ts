// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

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
 * - Durable batches before network delivery
 * - Cursor advancement only after contiguous server acknowledgement
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
  user_id?: string;
  agent_id?: string;
  agent_version?: string;
}

export interface PendingBatch {
  session_id: string;
  destination: string;
  user_id?: string;
  payload: Record<string, unknown>;
  end_line: number;
  end_offset: number;
  final: boolean;
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
const OUTBOX_DIR = path.join(OBSERVAL_DIR, "pi_session_outbox");
const TIMEOUT_MS = 5_000;
const MAX_LINES_PER_CHUNK = 500;
const RECOVERY_MAX_SESSIONS = 5;
const RECOVERY_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000; // 7 days
const MAX_LAYER_FILE_SIZE = 512 * 1024;
const MAX_OUTBOX_BYTES = 256 * 1024 * 1024;

export function acknowledgementCovers(acknowledgement: unknown, pending: PendingBatch): boolean {
  if (!acknowledgement || typeof acknowledgement !== "object") return false;
  const acknowledgedLine = (acknowledgement as Record<string, unknown>).acknowledged_line;
  return Number.isInteger(acknowledgedLine) && Number(acknowledgedLine) >= pending.end_line;
}

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
      const accessToken = data.api_key || data.access_token;
      if (!data.server_url || !accessToken) return null;
      const config: ObservalConfig = {
        server_url: data.server_url,
        access_token: accessToken,
        user_id: data.user_id || undefined,
      };
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

  function writeCursor(sessionId: string, offset: number, lineCount: number, finalized = false): boolean {
    try {
      fs.mkdirSync(OBSERVAL_DIR, { recursive: true });
      let data: Record<string, CursorEntry> = {};
      if (fs.existsSync(SYNC_STATE_PATH)) {
        data = JSON.parse(fs.readFileSync(SYNC_STATE_PATH, "utf-8"));
      }
      data[sessionId] = { offset, line_count: lineCount, finalized, last_pushed_at: Date.now() };
      const temporary = `${SYNC_STATE_PATH}.${process.pid}.${Date.now()}.tmp`;
      fs.writeFileSync(temporary, JSON.stringify(data, null, 2), { mode: 0o600 });
      fs.renameSync(temporary, SYNC_STATE_PATH);
      return true;
    } catch {
      return false;
    }
  }

  function pendingPath(sessionId: string): string {
    return path.join(OUTBOX_DIR, `${sha256(Buffer.from(sessionId))}.json`);
  }

  function readPending(sessionId: string): PendingBatch | null {
    const file = pendingPath(sessionId);
    if (!fs.existsSync(file)) return null;
    const pending = JSON.parse(fs.readFileSync(file, "utf-8"));
    if (pending?.session_id !== sessionId || !pending?.payload) {
      throw new Error(`invalid Pi outbox entry: ${file}`);
    }
    return pending;
  }

  function outboxBytes(exclude: string): number {
    if (!fs.existsSync(OUTBOX_DIR)) return 0;
    let total = 0;
    for (const name of fs.readdirSync(OUTBOX_DIR)) {
      const file = path.join(OUTBOX_DIR, name);
      if (file === exclude || !name.endsWith(".json")) continue;
      try { total += fs.statSync(file).size; } catch { }
    }
    return total;
  }

  function writePending(pending: PendingBatch): boolean {
    try {
      fs.mkdirSync(OUTBOX_DIR, { recursive: true });
      const file = pendingPath(pending.session_id);
      const serialized = JSON.stringify(pending);
      if (outboxBytes(file) + Buffer.byteLength(serialized) > MAX_OUTBOX_BYTES) return false;
      const temporary = `${file}.${process.pid}.${Date.now()}.tmp`;
      fs.writeFileSync(temporary, serialized, { mode: 0o600 });
      fs.renameSync(temporary, file);
      return true;
    } catch {
      return false;
    }
  }

  function removePending(sessionId: string): void {
    try { fs.unlinkSync(pendingPath(sessionId)); } catch { }
  }

  async function deliverPending(config: ObservalConfig, pending: PendingBatch): Promise<boolean> {
    if (pending.destination.replace(/\/$/, "") !== config.server_url.replace(/\/$/, "")) return false;
    if (pending.user_id && pending.user_id !== config.user_id) return false;

    const acknowledgement = await postJsonWithTimeout(
      config,
      "/api/v1/ingest/session",
      JSON.stringify(pending.payload),
      TIMEOUT_MS,
    );
    if (!acknowledgementCovers(acknowledgement, pending)) return false;
    if (!writeCursor(pending.session_id, pending.end_offset, pending.end_line + 1, pending.final)) return false;
    removePending(pending.session_id);
    return true;
  }

  async function pushNewLines(s: ObservalState, opts: { final: boolean }): Promise<void> {
    if (!s.config || !s.sessionFile) return;

    const gen = ++s.generation;

    try {
      let cursor = readCursor(s.sessionId);
      const storedPending = readPending(s.sessionId);
      if (storedPending) {
        if (!(await deliverPending(s.config, storedPending))) return;
        if (s.generation !== gen) return;
        cursor = readCursor(s.sessionId);
      }
      s.byteOffset = cursor.offset;
      s.lineCount = cursor.line_count;

      const stat = fs.statSync(s.sessionFile);
      const newBytes = stat.size - s.byteOffset;
      if (newBytes < 0) return;

      let lines: string[] = [];
      let endByteOffsets: number[] = [];
      let consumedBytes = 0;

      if (newBytes > 0) {
        const buffer = Buffer.alloc(newBytes);
        const fd = fs.openSync(s.sessionFile, "r");
        try {
          fs.readSync(fd, buffer, 0, newBytes, s.byteOffset);
        } finally {
          fs.closeSync(fd);
        }

        if (s.generation !== gen) return;
        const rawLines = buffer.toString("utf-8").split("\n");
        for (let i = 0; i < rawLines.length - 1; i++) {
          const line = rawLines[i]!;
          consumedBytes += Buffer.byteLength(line, "utf-8") + 1;
          if (line.trim()) {
            lines.push(line);
            endByteOffsets.push(s.byteOffset + consumedBytes);
          }
        }
        if (endByteOffsets.length > 0) {
          endByteOffsets[endByteOffsets.length - 1] = s.byteOffset + consumedBytes;
        }
      }

      if (lines.length === 0) {
        if (consumedBytes > 0) {
          s.byteOffset += consumedBytes;
          if (!writeCursor(s.sessionId, s.byteOffset, s.lineCount, false)) return;
        }
        if (!opts.final) return;

        const payload: Record<string, unknown> = {
          session_id: s.sessionId,
          harness: "pi",
          agent_id: s.config.agent_id ?? null,
          agent_version: s.config.agent_version ?? null,
          layer_hash: s.layerHash,
          lines: [],
          end_byte_offsets: [],
          start_offset: s.lineCount,
          hook_event: "SessionShutdown",
          final: true,
          total_line_count: s.lineCount,
          total_offset: s.byteOffset,
        };
        const pending: PendingBatch = {
          session_id: s.sessionId,
          destination: s.config.server_url,
          user_id: s.config.user_id,
          payload,
          end_line: s.lineCount - 1,
          end_offset: s.byteOffset,
          final: true,
        };
        if (!writePending(pending)) return;
        await deliverPending(s.config, pending);
        return;
      }

      const initialLineCount = s.lineCount;
      const finalOffset = s.byteOffset + consumedBytes;
      for (let offset = 0; offset < lines.length; offset += MAX_LINES_PER_CHUNK) {
        if (s.generation !== gen) return;
        const chunk = lines.slice(offset, offset + MAX_LINES_PER_CHUNK);
        const chunkEndOffsets = endByteOffsets.slice(offset, offset + MAX_LINES_PER_CHUNK);
        const isLastChunk = offset + MAX_LINES_PER_CHUNK >= lines.length;
        const endLine = initialLineCount + offset + chunk.length - 1;
        const endOffset = chunkEndOffsets[chunkEndOffsets.length - 1]!;
        const payload: Record<string, unknown> = {
          session_id: s.sessionId,
          harness: "pi",
          agent_id: s.config.agent_id ?? null,
          agent_version: s.config.agent_version ?? null,
          layer_hash: s.layerHash,
          lines: chunk,
          end_byte_offsets: chunkEndOffsets,
          start_offset: initialLineCount + offset,
          hook_event: opts.final && isLastChunk ? "SessionShutdown" : "AgentEnd",
          final: opts.final && isLastChunk,
          ...(opts.final && isLastChunk
            ? { total_line_count: initialLineCount + lines.length, total_offset: finalOffset }
            : {}),
        };
        const pending: PendingBatch = {
          session_id: s.sessionId,
          destination: s.config.server_url,
          user_id: s.config.user_id,
          payload,
          end_line: endLine,
          end_offset: endOffset,
          final: opts.final && isLastChunk,
        };
        if (!writePending(pending)) return;
        if (!(await deliverPending(s.config, pending))) return;
        if (s.generation !== gen) return;
        s.byteOffset = endOffset;
        s.lineCount = endLine + 1;
      }
    } catch {
      // Fail-open
    }
  }

  function postJsonWithTimeout(
    config: ObservalConfig,
    urlPath: string,
    body: string,
    timeoutMs = TIMEOUT_MS * 2,
  ): Promise<any | null> {
    return new Promise((resolve) => {
      try {
        const url = new URL(urlPath, config.server_url);
        const mod = url.protocol === "https:" ? https : http;
        const timer = setTimeout(() => {
          req.destroy();
          resolve(null);
        }, timeoutMs);

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


  async function drainStoredOutbox(config: ObservalConfig): Promise<void> {
    if (!fs.existsSync(OUTBOX_DIR)) return;
    for (const name of fs.readdirSync(OUTBOX_DIR)) {
      if (!name.endsWith(".json")) continue;
      try {
        const pending = JSON.parse(fs.readFileSync(path.join(OUTBOX_DIR, name), "utf-8"));
        if (!pending?.session_id || !pending?.payload) continue;
        await deliverPending(config, pending);
      } catch {
        // Keep corrupt or unreachable entries for manual recovery.
      }
    }
  }

  async function recoverStaleSessions(s: ObservalState, ctx: ExtensionContext): Promise<void> {
    try {
      if (!s.config) return;
      await drainStoredOutbox(s.config);
      if (!fs.existsSync(SYNC_STATE_PATH)) return;
      const data: Record<string, CursorEntry> = JSON.parse(
        fs.readFileSync(SYNC_STATE_PATH, "utf-8"),
      );

      const sessionsDir = (ctx.sessionManager as any).getSessionDir?.()
        ?? path.join(os.homedir(), ".pi", "agent", "sessions");
      const projectKey = ctx.cwd.replace(/\//g, "-");
      const fullDir = path.join(sessionsDir, `-${projectKey}-`);
      let recovered = 0;
      const now = Date.now();

      for (const [sessionId, storedEntry] of Object.entries(data)) {
        if (sessionId === s.sessionId || recovered >= RECOVERY_MAX_SESSIONS) continue;
        const entry = storedEntry;
        if (entry.finalized) continue;
        if (!fs.existsSync(fullDir)) continue;

        const files = fs.readdirSync(fullDir).filter((f) => f.includes(sessionId));
        if (files.length === 0) continue;
        const filePath = path.join(fullDir, files[0]!);
        if (!fs.existsSync(filePath)) continue;
        const fileStat = fs.statSync(filePath);
        if (now - fileStat.mtimeMs > RECOVERY_MAX_AGE_MS) continue;

        const recoveryState: ObservalState = {
          ...s,
          sessionFile: filePath,
          sessionId,
          byteOffset: entry.offset,
          lineCount: entry.line_count,
          generation: 0,
        };
        await pushNewLines(recoveryState, { final: true });
        if (readCursor(sessionId).finalized) recovered++;
      }

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
      if (entries.length <= 50) return;

      const required = entries.filter(([, value]) => !value.finalized);
      const recentFinalized = entries
        .filter(([, value]) => value.finalized)
        .sort((a, b) => (b[1].last_pushed_at ?? 0) - (a[1].last_pushed_at ?? 0))
        .slice(0, Math.max(0, 50 - required.length));
      const pruned: Record<string, CursorEntry> = {};
      for (const [key, value] of [...required, ...recentFinalized]) {
        pruned[key] = value;
      }
      const temporary = `${SYNC_STATE_PATH}.${process.pid}.${Date.now()}.tmp`;
      fs.writeFileSync(temporary, JSON.stringify(pruned, null, 2), { mode: 0o600 });
      fs.renameSync(temporary, SYNC_STATE_PATH);
    } catch {
      // Fail-open
    }
  }
}
