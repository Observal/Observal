# SPDX-License-Identifier: Apache-2.0
"""Virtual files, redaction, real hunks and comment re-anchoring."""

from types import SimpleNamespace

import pytest

from services.review.anchors import reanchor
from services.review.checks import snapshot_checks
from services.review.diff import diff_files
from services.review.files import FIELDS, render_component


def version(kind, **kwargs):
    data = dict.fromkeys(FIELDS[kind])
    data.update(
        {
            "skill_md_content": "# Readme\n",
            "script_content": None,
            "script_filename": None,
            "tools_schema": None,
            "setup_instructions": None,
            "template": "Hi\n",
        }
    )
    data.update(kwargs)
    return SimpleNamespace(**data)


@pytest.mark.parametrize("kind", ["mcp", "skill", "hook", "prompt", "sandbox"])
def test_all_component_renderers(kind):
    assert f"{kind}.yaml" in render_component(kind, version(kind))


def test_redaction_nested_and_untrusted_script_path():
    files = render_component(
        "skill",
        version(
            "skill",
            mcp_server_config={"env": {"MY_TOKEN": "shh"}},
            script_filename="../../etc/passwd",
            script_content="echo hello",
        ),
    )
    assert "shh" not in str(files)
    assert "<redacted>" in files["skill.yaml"]["content"]
    assert "scripts/script.sh" in files
    assert all(".." not in key for key in files)
    mcp = render_component(
        "mcp",
        version(
            "mcp",
            environment_variables=[{"name": "API_KEY", "value": "secret"}],
            headers=[{"name": "Authorization", "value": "bearer secret"}],
        ),
    )
    assert "secret" not in str(mcp)
    assert "API_KEY" in mcp["mcp.yaml"]["content"]


def test_diff_tracks_insertions_without_repainting_remaining_lines():
    base = {"x.md": {"content": "one\ntwo\nthree\n", "lang": "markdown"}}
    head = {"x.md": {"content": "one\nNEW\ntwo\nthree\n", "lang": "markdown"}}
    diff = diff_files(base, head)[0]
    assert diff["additions"] == 1 and diff["deletions"] == 0
    assert [(line["t"], line.get("h")) for line in diff["hunks"][0]["lines"]] == [
        ("ctx", 1),
        ("add", 2),
        ("ctx", 3),
        ("ctx", 4),
    ]
    assert diff_files({}, head)[0]["status"] == "added"
    assert diff_files(base, {})[0]["status"] == "removed"


def test_large_file_requires_explicit_load():
    head = {"big": {"content": "x" * 400_001, "lang": "text"}}
    assert diff_files({}, head)[0]["too_large"]
    assert diff_files({}, head, full=True)[0]["additions"] == 1


def test_anchors_move_and_become_outdated():
    old = {"a.md": {"content": "one\ntwo\nthree\n"}}
    new = {"a.md": {"content": "first\none\ntwo\nreplaced\n"}}
    moved = SimpleNamespace(path="a.md", side="head", start_line=2, end_line=2, outdated=False)
    outdated = SimpleNamespace(path="a.md", side="head", start_line=3, end_line=3, outdated=False)
    assert reanchor([moved, outdated], old, new) == (1, 1)
    assert (moved.start_line, moved.end_line) == (3, 3)
    assert outdated.outdated


def test_secret_check_in_free_text():
    assert snapshot_checks({"x": {"content": "ghp_" + "a" * 36}})[0]["status"] == "fail"
