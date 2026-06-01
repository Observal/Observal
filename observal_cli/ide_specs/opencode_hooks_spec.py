# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Hook specification for OpenCode.

OpenCode uses in-process JS/TS plugins for session telemetry.
Plugins subscribe to events like session.idle, message.updated, etc.
This module provides metadata for `observal doctor patch` and the
plugin source that gets installed into .opencode/plugins/.

Bump HOOKS_SPEC_VERSION whenever the plugin definition changes.
"""

from __future__ import annotations

HOOKS_SPEC_VERSION = "2"

# OpenCode plugin events used for telemetry:
# - session.created: session started (initialization)
# - session.idle: session finished responding (push final data)
# - message.updated: a message was added/updated (incremental push)
OPENCODE_HOOK_EVENTS = ("session.created", "session.idle", "message.updated")


def build_hooks() -> dict:
    """Return hook metadata for OpenCode.

    OpenCode's hooks are delivered as a plugin file placed in
    .opencode/plugins/ or ~/.config/opencode/plugins/.
    The plugin subscribes to session lifecycle events and pushes
    message data to the Observal server.
    """
    return {
        "hook_type": "plugin",
        "install_method": "file",
        "plugin_path": ".opencode/plugins/observal-plugin.ts",
        "global_plugin_path": "~/.config/opencode/plugins/observal-plugin.ts",
        "events": list(OPENCODE_HOOK_EVENTS),
    }


def get_plugin_source() -> str:
    """Return the TypeScript plugin source for OpenCode telemetry.

    NOTE: The canonical plugin source lives in
    observal-server/services/ide/helpers.py (_OPENCODE_PLUGIN_SOURCE).
    The server delivers the plugin via the API during `observal pull`.
    This function exists only for offline/fallback use by `observal doctor patch`
    when the server is unreachable — it should NOT be maintained as a
    separate copy. If you need to update the plugin, update helpers.py.
    """
    try:
        from services.ide.helpers import _opencode_plugin_js

        return _opencode_plugin_js()
    except ImportError:
        pass
    # Fallback: minimal plugin that signals the need for a server-side refresh
    return """// Observal telemetry plugin for OpenCode (offline stub)
// Run `observal pull` to install the full plugin from the server.
export const ObservalPlugin = async () => ({ event: async () => {} });
"""
