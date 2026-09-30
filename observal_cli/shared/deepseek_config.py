# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Static Cordis patch inspection and lossless edits of Observal-owned plugin rows.

Never construct or evaluate YAML tags: ``!!js`` in a foreign plugin is opaque.
Only the literal ``insert`` plugin entries with known Observal IDs are edited.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

if TYPE_CHECKING:
    from pathlib import Path


HOOK_ID = "observal-hooks"
MCP_PREFIX = "observal-mcp-"
HOOK_NAME = "@deepseek-ai/dsh-hooks-claude-code"
TELEMETRY_ID = "observal-session-collector"
MCP_NAME = "@deepseek-ai/dsh-mcp-client"


def _mapping(node: Node) -> dict[str, Node]:
    if not isinstance(node, MappingNode):
        raise ValueError("expected a YAML mapping")
    fields: dict[str, Node] = {}
    for key, value in node.value:
        if not isinstance(key, ScalarNode) or key.tag != "tag:yaml.org,2002:str" or key.value in fields:
            raise ValueError("ambiguous YAML mapping key")
        fields[key.value] = value
    return fields


def _literal(node: Node | None) -> str | None:
    return node.value if isinstance(node, ScalarNode) and node.tag == "tag:yaml.org,2002:str" else None


def _static(node: Node) -> Any:
    """Project literal YAML fields only; dynamic tags remain unknown (None)."""
    if isinstance(node, ScalarNode):
        if node.tag == "tag:yaml.org,2002:str":
            return node.value
        if node.tag == "tag:yaml.org,2002:null":
            return None
        if node.tag == "tag:yaml.org,2002:bool":
            return node.value.lower() in ("true", "yes", "on")
        if node.tag == "tag:yaml.org,2002:int":
            try:
                return int(node.value)
            except ValueError:
                return None
        return None
    if isinstance(node, SequenceNode):
        return [_static(item) for item in node.value]
    if isinstance(node, MappingNode):
        return {key: _static(value) for key, value in _mapping(node).items()}
    return None


def _patches(text: str) -> SequenceNode:
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as error:
        raise ValueError("invalid Cordis patch YAML") from error
    if not isinstance(root, SequenceNode) or root.tag != "tag:yaml.org,2002:seq":
        raise ValueError("Cordis patch must be a top-level YAML sequence")
    return root


def _rows(root: SequenceNode, *, static_only: bool = False) -> list[tuple[Node, SequenceNode, Node, dict[str, Node]]]:
    rows = []
    for patch in root.value:
        fields = _mapping(patch)
        inserts = fields.get("insert")
        if inserts is None:
            continue
        if not isinstance(inserts, SequenceNode) or inserts.tag != "tag:yaml.org,2002:seq":
            if (
                static_only
                and isinstance(inserts, ScalarNode)
                and inserts.tag not in ("tag:yaml.org,2002:str", "tag:yaml.org,2002:seq")
            ):
                continue
            raise ValueError("Cordis insert must be a sequence")
        for row in inserts.value:
            rows.append((patch, inserts, row, _mapping(row)))
    return rows


def read_entries(path: Path) -> list[dict]:
    """Read static plugin entries from a patch list; never execute Cordis expressions.

    Missing paths return an empty list. Invalid YAML or ambiguous mappings raise
    ValueError so callers cannot mistake broken configuration for an empty file.
    """
    if not path.is_file():
        return []
    root = _patches(path.read_text(encoding="utf-8"))
    return [_static(row) for _, _, row, _ in _rows(root, static_only=True)]


def _owned(fields: dict[str, Node]) -> bool:
    identifier = _literal(fields.get("id"))
    name = _literal(fields.get("name"))
    if identifier == HOOK_ID:
        if name != HOOK_NAME:
            raise ValueError("Observal hook ID belongs to another plugin")
        return True
    if identifier == TELEMETRY_ID:
        # This is a local file, not an npm module. Refuse a foreign row that
        # happens to reuse the Observal ID rather than replacing its config.
        if not name or not name.endswith("/observal/collector.mjs"):
            raise ValueError("Observal collector ID belongs to another plugin")
        return True
    if identifier and identifier.startswith(MCP_PREFIX):
        if name != MCP_NAME:
            raise ValueError("Observal MCP ID belongs to another plugin")
        return True
    return False


def _line_span(text: str, node: Node) -> tuple[int, int]:
    """Span includes only the item's physical lines, not adjacent comments."""
    lines = text.splitlines(keepends=True)
    start = sum(map(len, lines[: node.start_mark.line]))
    # PyYAML often places end_mark at the indentation of the next item.
    # Including that line would erase a foreign plugin alongside ours.
    end_line = node.end_mark.line
    if end_line < len(lines) and lines[end_line][: node.end_mark.column].strip():
        end_line += 1
    while end_line > node.start_mark.line + 1 and (
        not lines[end_line - 1].strip() or lines[end_line - 1].lstrip().startswith("#")
    ):
        end_line -= 1
    end = sum(map(len, lines[:end_line]))
    return start, end


def edit_owned_rows(
    text: str, incoming: list[dict], *, remove_all: bool = False, target_ids: set[str] | None = None
) -> str:
    """Replace owned rows without serializing foreign source, comments or ``!!js``.

    The input and output are top-level Cordis patch sequences. Fail closed on
    duplicate IDs and composite actions containing owned entries. Callers write
    the returned text atomically only after validation succeeds.
    """
    root = _patches(text) if text.strip() else _patches("[]\n")
    if root.flow_style and root.value:
        raise ValueError("cannot edit a nonempty flow-style Cordis patch sequence")
    rows = _rows(root)
    requested = {row.get("id") for patch in incoming for row in patch.get("insert", []) if isinstance(row, dict)}
    requested.update(target_ids or ())
    identifiers: set[str] = set()
    spans: list[tuple[int, int]] = []
    for patch, inserts, row, fields in rows:
        identifier = _literal(fields.get("id"))
        if identifier:
            if identifier in identifiers:
                raise ValueError(f"duplicate Cordis plugin ID: {identifier}")
            identifiers.add(identifier)
        if not _owned(fields) or not (remove_all or identifier in requested):
            continue
        if set(_mapping(patch)) != {"insert"}:
            raise ValueError("cannot edit an Observal plugin in a composite Cordis patch")
        patch_ids = [_literal(_mapping(item).get("id")) for item in inserts.value]
        if all(
            item_id in requested
            or (remove_all and (item_id in (HOOK_ID, TELEMETRY_ID) or bool(item_id and item_id.startswith(MCP_PREFIX))))
            for item_id in patch_ids
        ):
            spans.append(_line_span(text, patch))
        else:
            if row.start_mark.line == row.end_mark.line or patch.start_mark.line == patch.end_mark.line:
                raise ValueError("cannot edit inline mixed Cordis insert")
            spans.append(_line_span(text, row))

    incoming_ids: set[str] = set()
    for patch in incoming:
        if not isinstance(patch, dict) or set(patch) != {"insert"} or not isinstance(patch["insert"], list):
            raise ValueError("invalid generated Cordis patch")
        for row in patch["insert"]:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise ValueError("invalid generated Cordis plugin")
            identifier = row["id"]
            if identifier in incoming_ids or (
                not identifier.startswith(MCP_PREFIX) and identifier not in (HOOK_ID, TELEMETRY_ID)
            ):
                raise ValueError("duplicate or foreign generated plugin ID")
            incoming_ids.add(identifier)
            expected = HOOK_NAME if identifier == HOOK_ID else MCP_NAME
            if identifier == TELEMETRY_ID:
                if not isinstance(row.get("name"), str) or not row["name"].endswith("/observal/collector.mjs"):
                    raise ValueError("invalid generated collector path")
            elif row.get("name") != expected:
                raise ValueError("generated plugin name does not match its ID")
            if identifier in identifiers and not any(
                _literal(fields.get("id")) == identifier and _owned(fields) for _, _, _, fields in rows
            ):
                raise ValueError(f"generated ID conflicts with foreign plugin: {identifier}")

    # A row can occupy the entire patch; do not delete the same patch twice.
    for start, end in sorted(set(spans), reverse=True):
        text = text[:start] + text[end:]
    if remove_all or not incoming:
        if not text.strip() and not spans:
            return text
        if all(not line.strip() or line.lstrip().startswith("#") for line in text.splitlines()):
            text += ("" if not text or text.endswith("\n") else "\n") + "[]\n"
        _patches(text)
        return text
    rendered = yaml.safe_dump(incoming, sort_keys=False, allow_unicode=True)
    if not text.strip():
        result = rendered
    elif not root.value:
        if root.start_mark.column or root.end_mark.column != root.start_mark.column + 2:
            raise ValueError("cannot replace inline empty Cordis patch sequence")
        result = text[: root.start_mark.index] + rendered.rstrip("\n") + text[root.end_mark.index :]
    else:
        result = text + ("" if text.endswith("\n") else "\n") + rendered
    _patches(result)
    return result
