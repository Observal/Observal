# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import sys
import tomllib
from types import ModuleType

import pytest
import tools.release as release
from tools.release import (
    Change,
    Commit,
    Contributor,
    ReleaseError,
    all_contributors,
    bump_version,
    choose_release,
    discover_changes,
    latest_tag,
    pr_body,
    prepend_changelog,
    release_cutoff,
    render_changelog_section,
    render_release_notes,
    resolve_release_push,
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


def test_latest_tag_chooses_highest_stable_even_when_detached(monkeypatch):
    monkeypatch.setattr(release, "run", lambda *args, **kwargs: "v1.10.7\nv1.11.0-rc.1\nv1.10.9\n")

    assert latest_tag() == "v1.10.9"


def test_release_cutoff_uses_manifest_with_old_tag_fallback(monkeypatch):
    cutoff = "b" * 40
    old_tag_sha = "a" * 40

    def fake_run(*args, **kwargs):
        if args[:3] == ("git", "show", "v1.10.8:.release.toml"):
            return f'cutoff = "{cutoff}"\n'
        if args[:3] == ("git", "show", "v1.10.7:.release.toml"):
            raise ReleaseError("missing manifest")
        # No .release.toml at the tag: the fallback resolves the tag to a
        # commit SHA so later git log ranges don't depend on the tag ref.
        if args[:3] == ("git", "rev-parse", "v1.10.7^{commit}"):
            return old_tag_sha
        if args[:3] == ("git", "cat-file", "-e"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(release, "run", fake_run)

    assert release_cutoff("v1.10.8") == cutoff
    assert release_cutoff("v1.10.7") == old_tag_sha


def test_release_discovery_skips_prior_release_metadata(monkeypatch):
    release_commit = Commit("a" * 40, "Maintainer", "m@example.com", "chore(release): v1.10.8", "")
    feature_commit = Commit("b" * 40, "Contributor", "c@example.com", "feat: next change", "")
    monkeypatch.setattr(release, "commit_log", lambda revision_range: [release_commit, feature_commit])
    monkeypatch.setattr(
        release,
        "gh_json",
        lambda repo, endpoint: (
            [{"number": 1, "merged_at": "2026-08-01", "base": {"ref": "main"}, "title": release_commit.title}]
            if release_commit.sha in endpoint
            else []
        ),
    )

    changes = discover_changes("Observal/Observal", "c" * 40, "upstream/main")

    assert [change.title for change in changes] == ["feat: next change"]


def test_resolve_release_push_uses_exact_merged_pr_head(monkeypatch):
    normal = Commit("a" * 40, "A", "a@example.com", "fix: normal", "")
    merged = Commit("b" * 40, "B", "b@example.com", "chore(release): v1.10.8", "")
    head = "c" * 40
    monkeypatch.setattr(release, "commit_log", lambda revision_range: [normal, merged])

    def fake_run(*args, **kwargs):
        if args[:4] == ("git", "log", "--format=%H", "0" * 40 + ".." + "f" * 40):
            return merged.sha
        if args[:3] == ("git", "fetch", "--no-tags"):
            return ""
        if args[:3] == ("git", "rev-parse", "FETCH_HEAD^{commit}"):
            return head
        raise AssertionError(args)

    def fake_gh_json(repo, endpoint):
        if endpoint == f"commits/{merged.sha}/pulls":
            return [
                {
                    "number": 42,
                    "merged_at": "2026-08-02T00:00:00Z",
                    "base": {"ref": "main"},
                    "title": merged.title,
                }
            ]
        if endpoint == "pulls/42":
            return {
                "merged_at": "2026-08-02T00:00:00Z",
                "merge_commit_sha": merged.sha,
                "title": merged.title,
                "base": {"ref": "main"},
                "head": {"sha": head},
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(release, "run", fake_run)
    monkeypatch.setattr(release, "gh_json", fake_gh_json)

    assert resolve_release_push("0" * 40, "f" * 40, "Observal/Observal") == (head, 42)


def test_resolve_release_push_rejects_manifest_without_release_commit(monkeypatch):
    normal = Commit("a" * 40, "A", "a@example.com", "fix: normal", "")
    monkeypatch.setattr(release, "commit_log", lambda revision_range: [normal])
    monkeypatch.setattr(release, "run", lambda *args, **kwargs: normal.sha)

    with pytest.raises(ReleaseError, match="ambiguous or malformed"):
        resolve_release_push("0" * 40, "f" * 40, "Observal/Observal")


def test_release_pr_instructions_allow_linear_merges():
    body = pr_body("1.10.8", "v1.10.7", "a" * 40, [_change()], "preview")

    assert "squash, rebase, or the merge queue" in body
    assert "merge commit" not in body


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


def test_release_notes_include_version_and_comparison_link():
    notes = render_release_notes(
        "1.10.8",
        "v1.10.7",
        "a" * 40,
        [_change()],
        [Contributor("Hari", "hari"), Contributor("New Person", "new-person", first_time=True)],
    )

    assert "v1.10.7...v1.10.8" in notes
    assert "add safe releases" in notes


def test_changelog_uses_only_selected_public_notes():
    section = render_changelog_section(
        "1.10.8",
        "2026-07-28",
        [_change(), _change(title="ci: internal work", category="Maintenance", include_in_notes=False)],
    )

    assert "add safe releases" in section
    assert "internal work" not in section
