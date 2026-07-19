# SPDX-FileCopyrightText: 2026 Solaris-star <820622658@qq.com>
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for pure helpers in observal_cli.cmd_skill (Part of #898)."""

from __future__ import annotations

from pathlib import Path

from observal_cli.cmd_skill import _is_path_safe, _parse_frontmatter


class TestIsPathSafe:
    def test_accepts_path_inside_base(self, tmp_path: Path) -> None:
        base = tmp_path / "skills"
        base.mkdir()
        child = base / "nested" / "skill.md"
        child.parent.mkdir(parents=True)
        child.write_text("x", encoding="utf-8")
        assert _is_path_safe(child, base) is True

    def test_rejects_path_outside_base(self, tmp_path: Path) -> None:
        base = tmp_path / "skills"
        base.mkdir()
        outside = tmp_path / "other" / "file.md"
        outside.parent.mkdir()
        outside.write_text("x", encoding="utf-8")
        assert _is_path_safe(outside, base) is False

    def test_rejects_traversal_via_parent_segments(self, tmp_path: Path) -> None:
        base = tmp_path / "skills"
        base.mkdir()
        # unresolved path that would escape if not resolve()'d carefully
        attacker = base / ".." / "escape.md"
        attacker.write_text("nope", encoding="utf-8")
        assert _is_path_safe(attacker, base) is False


class TestParseFrontmatter:
    def test_parses_simple_yaml_frontmatter(self) -> None:
        content = "---\nname: demo\ndescription: hello\n---\n\n# Body\n"
        assert _parse_frontmatter(content) == {"name": "demo", "description": "hello"}

    def test_returns_empty_when_missing_frontmatter(self) -> None:
        assert _parse_frontmatter("# just markdown\n") == {}

    def test_returns_empty_on_invalid_yaml(self) -> None:
        content = "---\n: bad: [unclosed\n---\nbody\n"
        assert _parse_frontmatter(content) == {}

    def test_returns_empty_when_frontmatter_not_a_mapping(self) -> None:
        content = "---\n- only\n- a\n- list\n---\nbody\n"
        assert _parse_frontmatter(content) == {}

    def test_supports_crlf_frontmatter_delimiters(self) -> None:
        content = "---\r\nname: crlf\r\n---\r\nbody\n"
        assert _parse_frontmatter(content) == {"name": "crlf"}
