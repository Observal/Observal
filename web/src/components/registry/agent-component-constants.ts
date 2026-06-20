// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import type { RegistryType } from "@/lib/api";

export const COMPONENT_TYPES: { value: RegistryType; label: string; singular: string }[] = [
  { value: "mcps", label: "MCPs", singular: "MCP" },
  { value: "skills", label: "Skills", singular: "Skill" },
  { value: "hooks", label: "Hooks", singular: "Hook" },
  { value: "prompts", label: "Prompts", singular: "Prompt" },
  { value: "sandboxes", label: "Sandboxes", singular: "Sandbox" },
];

export const TYPE_MAP: Record<string, string> = {
  mcps: "mcp",
  skills: "skill",
  hooks: "hook",
  prompts: "prompt",
  sandboxes: "sandbox",
};

export const REVERSE_TYPE_MAP: Record<string, string> = {
  mcp: "mcps",
  skill: "skills",
  hook: "hooks",
  prompt: "prompts",
  sandbox: "sandboxes",
};
