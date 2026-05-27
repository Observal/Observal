// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

/**
 * IDE feature capability matrix — TypeScript mirror of
 * observal-server/schemas/ide_registry.py (IDE_REGISTRY).
 *
 * When adding or changing IDE entries, update IDE_REGISTRY in
 * observal-server/schemas/ide_registry.py first, then mirror here.
 */

export const VALID_IDES = [
  "claude-code",
  "codex",
  "copilot",
  "copilot-cli",
  "cursor",
  "gemini-cli",
  "kiro",
  "opencode",
  "pi",
] as const;

export type IdeName = (typeof VALID_IDES)[number];

export const IDE_FEATURES = [
  "skills",
  "superpowers",
  "hook_bridge",
  "mcp_servers",
  "rules",
  "steering_files",
  "otlp_telemetry",
] as const;

export type IdeFeature = (typeof IDE_FEATURES)[number];

export const IDE_FEATURE_MATRIX: Record<IdeName, ReadonlySet<IdeFeature>> = {
  "claude-code": new Set(["skills", "hook_bridge", "mcp_servers", "rules", "otlp_telemetry"]),
  kiro: new Set(["superpowers", "hook_bridge", "mcp_servers", "rules", "steering_files", "otlp_telemetry"]),
  cursor: new Set(["hook_bridge", "mcp_servers", "rules"]),
  "gemini-cli": new Set(["hook_bridge", "mcp_servers", "rules", "otlp_telemetry"]),
  codex: new Set(["rules"]),
  copilot: new Set(["mcp_servers", "rules"]),
  "copilot-cli": new Set(["mcp_servers", "rules", "hook_bridge", "skills"]),
  opencode: new Set(["mcp_servers", "rules"]),
  pi: new Set(["skills", "hook_bridge", "mcp_servers", "rules"]),
};

export const IDE_DISPLAY_NAMES: Record<IdeName, string> = {
  "claude-code": "Claude Code",
  kiro: "Kiro",
  cursor: "Cursor",
  "gemini-cli": "Gemini CLI",
  codex: "Codex",
  copilot: "Copilot",
  "copilot-cli": "Copilot CLI",
  opencode: "OpenCode",
  pi: "Pi",
};

export const FEATURE_LABELS: Record<IdeFeature, string> = {
  skills: "Slash-command skills",
  superpowers: "Kiro superpowers",
  hook_bridge: "Hook bridge",
  mcp_servers: "MCP servers",
  rules: "Rules / system prompt",
  steering_files: "Steering files",
  otlp_telemetry: "OTLP telemetry",
};

/**
 * Whether each IDE accepts an explicit model choice.
 * Mirror of `accepts_model_choice` in IDE_REGISTRY (server) /
 * observal_cli/ide_registry.py (CLI).
 */
export const IDE_ACCEPTS_MODEL_CHOICE: Record<IdeName, boolean> = {
  "claude-code": true,
  kiro: true,
  "gemini-cli": true,
  codex: true,
  opencode: true,
  pi: true,
  cursor: false,
  copilot: false,
  "copilot-cli": false,
};

export function ideAcceptsModelChoice(ide: string): boolean {
  return IDE_ACCEPTS_MODEL_CHOICE[ide as IdeName] === true;
}

export function getModelChoiceIdes(): IdeName[] {
  return (Object.keys(IDE_ACCEPTS_MODEL_CHOICE) as IdeName[]).filter(
    (ide) => IDE_ACCEPTS_MODEL_CHOICE[ide],
  );
}
