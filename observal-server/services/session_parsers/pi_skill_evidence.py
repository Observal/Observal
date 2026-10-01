# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Pi skill evidence from canonical session JSONL source records only.

Observed in Pi 0.99.2 sessions (``tests/fixtures/component_insights/pi``):

* **available**: the ``system`` message's ``sections.skills`` lists each
  advertised skill as ``<skill><name/><description/><location/></skill>``
  inside ``<available_skills>``. ``location`` is the absolute SKILL.md path.
* **loaded**: an assistant ``toolCall`` named ``read`` whose
  ``arguments.path`` is an advertised location, linked to its ``toolResult``
  by tool-call id.
* **invoked**: ``/skill:name`` becomes a user message containing
  ``<skill name="..." location="...">``.

A location identifies an Observal install only in Pi's own layout:
``<home>/.pi/agent/skills/<alias>/SKILL.md`` (user scope) or
``<session cwd>/.pi/skills/<alias>/SKILL.md`` (project scope). Anything else,
such as ``~/.agents/skills``, yields no evidence. Only the scope and alias
leave this module; locations, descriptions and skill text do not.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from .base import load_line, str_field
from .skill_evidence import SkillEvidence, SkillEvidenceExtraction

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_ALIAS = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TOOL_ID = re.compile(r"[\x21-\x7e]{1,256}\Z")
_ADVERTISED = re.compile(r"<skill>\s*<name>.*?</name>.*?<location>(.*?)</location>\s*</skill>", re.S)
_INVOKED = re.compile(r'<skill\s+name="[^"]*"\s+location="([^"]+)"\s*>')
_USER_LAYOUT = re.compile(r"/\.pi/agent/skills/([^/]+)/SKILL\.md\Z")
_MAX_LOCATIONS = 512


def _event_time(record: dict, row: Mapping[str, object]) -> datetime | None:
    for value in (record.get("timestamp"), row.get("timestamp")):
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
        else:
            continue
        if parsed.year == 1970:
            continue
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _install(location: str, cwd: str) -> tuple[Literal["user", "project"], str] | None:
    """The (scope, alias) an advertised SKILL.md location belongs to, if any."""
    if not isinstance(location, str) or len(location) > 4096:
        return None
    match = _USER_LAYOUT.search(location)
    if match:
        scope: Literal["user", "project"] = "user"
        alias = match.group(1)
    elif cwd and location.startswith(cwd.rstrip("/") + "/.pi/skills/"):
        rest = location[len(cwd.rstrip("/") + "/.pi/skills/") :]
        alias, _, tail = rest.partition("/")
        if tail != "SKILL.md":
            return None
        scope = "project"
    else:
        return None
    return (scope, alias) if _ALIAS.fullmatch(alias) else None


def _text_blocks(message: dict) -> list[str]:
    content = message.get("content")
    if isinstance(content, str):
        return [content]
    return (
        [b.get("text", "") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]
        if (isinstance(content, list))
        else []
    )


class PiSkillEvidenceExtractor:
    def extract(self, rows: Sequence[Mapping[str, object]]) -> SkillEvidenceExtraction:
        records: list[tuple[int, dict, Mapping[str, object]]] = []
        malformed = 0
        for row in rows:
            if row.get("is_source_record") != 1:
                continue
            offset, raw_line = row.get("line_offset"), row.get("raw_line")
            if type(offset) is not int or offset < 0 or not isinstance(raw_line, str):
                malformed += 1
                continue
            record = load_line(raw_line)
            if record is None:
                malformed += 1
                continue
            records.append((offset, record, row))
        records.sort(key=lambda item: item[0])

        cwd = next((str_field(r, "cwd") for _, r, _ in records if str_field(r, "type") == "session"), "")
        evidence: list[SkillEvidence] = []
        advertised: dict[str, tuple[Literal["user", "project"], str]] = {}
        reads: list[tuple[int, int, str, str, datetime | None]] = []  # offset, index, call id, location, time
        results: dict[str, list[tuple[int, Literal["unknown", "success", "error"]]]] = {}

        for offset, record, row in records:
            if str_field(record, "type") != "message":
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                malformed += 1
                continue
            role, time = message.get("role"), _event_time(record, row)
            if role == "system":
                sections = message.get("sections")
                skills = sections.get("skills") if isinstance(sections, dict) else None
                if not isinstance(skills, str):
                    continue
                # A later system record (e.g. after /reload) replaces what is advertised.
                advertised = {}
                for location in _ADVERTISED.findall(skills)[:_MAX_LOCATIONS]:
                    install = _install(location.strip(), cwd)
                    if install and install not in advertised.values():
                        advertised[location.strip()] = install
                        evidence.append(SkillEvidence("available", *install, offset, "system", time))
            elif role == "user":
                for index, text in enumerate(_text_blocks(message)):
                    for location in _INVOKED.findall(text):
                        install = _install(location, cwd)
                        if install:
                            evidence.append(SkillEvidence("invoked", *install, offset, f"skill:{index}", time))
            elif role == "assistant":
                for index, block in enumerate(message.get("content") or []):
                    if not isinstance(block, dict) or block.get("type") != "toolCall" or block.get("name") != "read":
                        continue
                    arguments = block.get("arguments")
                    location = arguments.get("path") if isinstance(arguments, dict) else None
                    if isinstance(location, str) and location in advertised:
                        call_id = block.get("id") if isinstance(block.get("id"), str) else ""
                        call_id = call_id if _TOOL_ID.fullmatch(call_id or "") else ""
                        reads.append((offset, index, call_id, location, time))
            elif role == "toolResult":
                call_id = message.get("toolCallId")
                if isinstance(call_id, str) and _TOOL_ID.fullmatch(call_id):
                    flag = message.get("isError")
                    state: Literal["unknown", "success", "error"] = (
                        ("error" if flag else "success") if type(flag) is bool else "unknown"
                    )
                    results.setdefault(call_id, []).append((offset, state))

        call_counts = Counter(call_id for _, _, call_id, _, _ in reads if call_id)
        for offset, index, call_id, location, time in reads:
            unique = bool(call_id) and call_counts[call_id] == 1
            linked = results.get(call_id, ()) if unique else ()
            state = linked[0][1] if len(linked) == 1 and linked[0][0] > offset else "unknown"
            key = f"id:{call_id}" if unique else f"index:{index}"
            evidence.append(SkillEvidence("loaded", *advertised[location], offset, key, time, state))
        return SkillEvidenceExtraction(status="supported", evidence=tuple(evidence), malformed_source_records=malformed)
