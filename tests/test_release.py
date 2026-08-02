# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import sys
import tomllib
from types import ModuleType

import pytest
from tools.release import (
    Change,
    Commit,
    Contributor,
    ReleaseError,
    all_contributors,
    bump_version,
    choose_release,
    prepend_changelog,
    render_changelog_section,
    render_release_notes,
    set_version,
    validate_version_channel,
    write_manifest,
)


def _change(**overrides):
    values = {
        "commits": ["a" * 40],
        "title": "feat(cli): add safe releases",
        "author_name": "Hari",
        "author_email": "hari@example.com",
        "pr": 42,
        "url": "https://github.com/Observal/Observal/pull/42",
        "category": "Features",
    }
    values.update(overrides)
    return Change(**values)


def test_bump_version():
    assert bump_version("1.10.7", "patch") == "1.10.8"
    assert bump_version("1.10.7", "feature") == "1.11.0"
    assert bump_version("1.10.7", "major") == "2.0.0"


def test_cutoff_picker_defaults_to_last_choice(monkeypatch):
    questionary = ModuleType("questionary")

    class Choice:
        def __init__(self, title, value, checked=False):
            self.title = title
            self.value = value
            self.checked = checked

    class Prompt:
        def __init__(self, answer):
            self.answer = answer

        def ask(self):
            return self.answer

    def select(question, *, choices, default):
        if question.startswith("Release through"):
            assert default is choices[-1]
            return Prompt(0)
        if question == "Version bump:":
            return Prompt("patch")
        return Prompt("stable")

    questionary.Choice = Choice
    questionary.select = select
    questionary.checkbox = lambda *args, **kwargs: Prompt([0])
    questionary.confirm = lambda *args, **kwargs: Prompt(False)
    monkeypatch.setitem(sys.modules, "questionary", questionary)

    included, version, channel = choose_release([_change()], "1.10.7", set())

    assert included == [_change()]
    assert (version, channel) == ("1.10.8", "stable")


def test_changelog_prepends_without_rewriting_history():
    history = (
        "<!-- custom header -->\n\n# Changelog\n\n"
        "All notable changes to this project will be documented in this file.\n\n"
        "## [1.10.7] - hand-edited history\n\nKeep this text exactly.\n"
    )
    section = "## [1.10.8] - 2026-07-28\n\n### Fixes\n\n- Fixed it"

    updated = prepend_changelog(history, section, "1.10.8")

    assert updated.endswith("## [1.10.7] - hand-edited history\n\nKeep this text exactly.\n")
    assert section in updated


def test_changelog_rejects_duplicate_version():
    history = "# Changelog\n\nAll notable changes to this project will be documented in this file.\n\n## [1.0.0]\n"

    with pytest.raises(ReleaseError, match="already contains"):
        prepend_changelog(history, "## [1.0.0]", "1.0.0")


def test_changelog_requires_introduction():
    with pytest.raises(ReleaseError, match="introduction was not found"):
        prepend_changelog("# Changelog\n", "## [1.0.0]", "1.0.0")


def test_set_version_updates_project_toml_and_top_level_json(tmp_path):
    toml_path = tmp_path / "pyproject.toml"
    toml_path.write_text('[tool.example]\nversion = "keep"\n\n[project]\nname = "demo"\nversion = "1.0.0"\n')
    json_path = tmp_path / "package.json"
    json_path.write_text('{\n  "name": "demo",\n  "version": "1.0.0",\n  "nested": {\n    "version": "keep"\n  }\n}\n')

    set_version(toml_path, "1.1.0")
    set_version(json_path, "1.1.0")

    assert '[tool.example]\nversion = "keep"' in toml_path.read_text()
    assert '[project]\nname = "demo"\nversion = "1.1.0"' in toml_path.read_text()
    assert '  "version": "1.1.0"' in json_path.read_text()
    assert '    "version": "keep"' in json_path.read_text()


def test_set_version_rejects_missing_version(tmp_path):
    path = tmp_path / "package.json"
    path.write_text('{\n  "name": "demo"\n}\n')

    with pytest.raises(ReleaseError, match="top-level version"):
        set_version(path, "1.1.0")


def test_write_manifest_supports_no_pull_requests(tmp_path):
    path = tmp_path / ".release.toml"

    write_manifest(path, "1.1.0", "stable", "v1.0.0", "a" * 40, [_change(pr=None)])

    manifest = tomllib.loads(path.read_text())
    assert manifest["version"] == "1.1.0"
    assert manifest["cutoff"] == "a" * 40
    assert manifest["included_prs"] == []


def test_version_must_match_release_channel():
    validate_version_channel("1.1.0", "stable")
    validate_version_channel("1.1.0-rc.1", "rc")

    with pytest.raises(ReleaseError, match="does not match"):
        validate_version_channel("1.1.0-rc.1", "stable")
    with pytest.raises(ReleaseError, match="does not match"):
        validate_version_channel("1.1.0-beta.1", "rc")


def test_commit_authors_are_included_as_contributors():
    contributors = all_contributors(
        [_change(contributor=Contributor("owner", "owner"))],
        [Commit("a" * 40, "Coauthor", "123+coauthor@users.noreply.github.com", "feat: work", "feat: work")],
    )

    assert [contributor.label for contributor in contributors] == ["@coauthor", "@owner"]


def test_human_names_ending_in_bot_are_not_filtered():
    contributors = all_contributors(
        [
            _change(contributor=Contributor("Talbot", "talbot")),
            _change(contributor=Contributor("dependabot", "dependabot[bot]")),
        ],
        [],
    )

    assert [contributor.label for contributor in contributors] == ["@talbot"]


def test_release_notes_include_all_contributors_and_first_time_marker():
    notes = render_release_notes(
        "1.10.8",
        "v1.10.7",
        "a" * 40,
        [_change()],
        [Contributor("Hari", "hari"), Contributor("New Person", "new-person", first_time=True)],
    )

    assert "@hari" in notes
    assert "@new-person (first contribution)" in notes
    assert "v1.10.7...v1.10.8" in notes


def test_changelog_uses_only_selected_public_notes():
    section = render_changelog_section(
        "1.10.8",
        "2026-07-28",
        [_change(), _change(title="ci: internal work", category="Maintenance", include_in_notes=False)],
    )

    assert "add safe releases" in section
    assert "internal work" not in section
