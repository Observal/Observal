"""Non-destructive reconciler for Claude Code settings.

Implements a Terraform-style declarative reconciliation:
  1. Read current state from ~/.claude/settings.json
  2. Compare against desired state from claude_code_spec
  3. Apply minimal diff: add missing, update stale, preserve foreign

Never deletes non-Observal hooks or env vars.  Identifies Observal
hooks by script path pattern, not by position or event name.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

from observal_cli import config
from observal_cli.claude_code_spec import (
    HOOKS_SPEC_VERSION,
    MANAGED_ENV_KEYS,
    is_observal_matcher_group,
)

logger = logging.getLogger("observal.reconciler")

CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def _load_claude_settings() -> dict:
    """Load ~/.claude/settings.json, returning {} on missing/corrupt."""
    if not CLAUDE_SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(CLAUDE_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not parse %s: %s", CLAUDE_SETTINGS_PATH, exc)
        return {}


def _save_claude_settings(settings: dict) -> None:
    """Write settings.json atomically (parent dir created if needed)."""
    CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS_PATH.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )


def reconcile_hooks(
    current_hooks: dict[str, list],
    desired_hooks: dict[str, list],
) -> tuple[dict[str, list], list[str]]:
    """Merge desired Observal hooks into current hooks non-destructively.

    Returns (merged_hooks, changes) where changes is a list of
    human-readable strings describing what was modified.
    """
    merged = copy.deepcopy(current_hooks)
    changes: list[str] = []

    # 1. For each desired event, reconcile matcher groups
    for event, desired_groups in desired_hooks.items():
        if event not in merged:
            # New event — add entirely
            merged[event] = copy.deepcopy(desired_groups)
            changes.append(f"+ {event}: added ({len(desired_groups)} handler(s))")
            continue

        current_groups = merged[event]

        # Partition current groups into Observal-managed and foreign
        foreign_groups = [g for g in current_groups if not is_observal_matcher_group(g)]
        observal_groups = [g for g in current_groups if is_observal_matcher_group(g)]

        # Check if Observal groups match desired (by JSON equality)
        if _groups_equal(observal_groups, desired_groups):
            continue  # Already up to date

        # Replace Observal groups with desired, keep foreign ones
        merged[event] = foreign_groups + copy.deepcopy(desired_groups)

        if observal_groups:
            changes.append(f"~ {event}: updated Observal hooks")
        else:
            changes.append(f"+ {event}: added Observal hooks")

    # 2. Events in current but not in desired — leave them alone
    #    (they might be non-Observal hooks, or events we no longer manage)

    return merged, changes


def reconcile_env(
    current_env: dict[str, str],
    desired_env: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    """Merge desired Observal env vars into current env.

    Only touches keys in MANAGED_ENV_KEYS.  Foreign env vars are
    preserved untouched.
    """
    merged = dict(current_env)
    changes: list[str] = []

    for key, value in desired_env.items():
        if key not in MANAGED_ENV_KEYS:
            continue
        old = merged.get(key)
        # OTEL_RESOURCE_ATTRIBUTES is comma-separated; merge our attrs
        # into any existing user-defined attributes instead of overwriting.
        if key == "OTEL_RESOURCE_ATTRIBUTES" and old:
            existing_pairs = {p.split("=", 1)[0]: p for p in old.split(",") if "=" in p}
            for pair in value.split(","):
                k = pair.split("=", 1)[0] if "=" in pair else pair
                existing_pairs[k] = pair
            value = ",".join(existing_pairs.values())
        if old != value:
            merged[key] = value
            if old is None:
                changes.append(f"+ env.{key}")
            else:
                changes.append(f"~ env.{key}")

    return merged, changes


def reconcile(
    desired_hooks: dict[str, list],
    desired_env: dict[str, str],
    *,
    dry_run: bool = False,
) -> list[str]:
    """Full reconciliation: load settings, diff, write if changed.

    Returns list of change descriptions (empty = already up to date).
    If dry_run=True, computes changes but does not write.
    """
    settings = _load_claude_settings()
    all_changes: list[str] = []

    # Reconcile hooks
    current_hooks = settings.get("hooks", {})
    merged_hooks, hook_changes = reconcile_hooks(current_hooks, desired_hooks)
    all_changes.extend(hook_changes)

    # Reconcile env
    current_env = settings.get("env", {})
    merged_env, env_changes = reconcile_env(current_env, desired_env)
    all_changes.extend(env_changes)

    if all_changes and not dry_run:
        settings["hooks"] = merged_hooks
        settings["env"] = merged_env
        _save_claude_settings(settings)

        # Record applied spec version
        config.save({"hooks_spec_version": HOOKS_SPEC_VERSION})

    return all_changes


def needs_upgrade() -> bool:
    """Check if the applied hooks spec is older than the current version."""
    cfg = config.load()
    applied = cfg.get("hooks_spec_version", "0")
    return applied != HOOKS_SPEC_VERSION


def get_applied_version() -> str:
    """Return the hooks spec version currently applied."""
    cfg = config.load()
    return cfg.get("hooks_spec_version", "0")


def _groups_equal(a: list[dict], b: list[dict]) -> bool:
    """Compare two lists of matcher groups by normalized JSON."""
    return _normalize(a) == _normalize(b)


def _normalize(obj: object) -> object:
    """Recursively sort dicts for stable comparison."""
    if isinstance(obj, dict):
        return tuple(sorted((k, _normalize(v)) for k, v in obj.items()))
    if isinstance(obj, list):
        return tuple(_normalize(item) for item in obj)
    return obj
