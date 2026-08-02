# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Prepare a curated Observal release from a safe, contiguous main-branch cutoff."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_ANCHOR = "All notable changes to this project will be documented in this file.\n\n"
CATEGORIES = (
    "Security",
    "Features",
    "Fixes",
    "Performance",
    "Documentation",
    "Maintenance",
)
VERSION_FILES = (
    "pyproject.toml",
    "observal-server/pyproject.toml",
    "web/package.json",
    "packages/pi-extension/package.json",
)
RELEASE_FILES = (
    *VERSION_FILES,
    "uv.lock",
    "observal-server/uv.lock",
    "CHANGELOG.md",
    ".release.toml",
    ".github/release-notes.md",
)


class ReleaseError(RuntimeError):
    pass


@dataclass
class Contributor:
    name: str
    login: str | None = None
    first_time: bool = False

    @property
    def label(self) -> str:
        return f"@{self.login}" if self.login else self.name


@dataclass
class Change:
    commits: list[str]
    title: str
    author_name: str
    author_email: str
    pr: int | None = None
    url: str | None = None
    body: str = ""
    labels: list[str] = field(default_factory=list)
    contributor: Contributor | None = None
    category: str = "Maintenance"
    include_in_notes: bool = True
    highlight: bool = False
    breaking: bool = False

    @property
    def reference(self) -> str:
        if self.pr and self.url:
            return f"[#{self.pr}]({self.url})"
        sha = self.commits[-1]
        return f"[{sha[:7]}](https://github.com/Observal/Observal/commit/{sha})"


@dataclass(frozen=True)
class Commit:
    sha: str
    author_name: str
    author_email: str
    title: str
    message: str


def run(*args: str, cwd: Path = ROOT, capture: bool = True) -> str:
    result = subprocess.run(args, cwd=cwd, check=False, text=True, capture_output=capture)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise ReleaseError(f"{' '.join(args)} failed: {detail}")
    return result.stdout.strip() if capture else ""


def require(command: str) -> None:
    try:
        run(command, "--version")
    except (FileNotFoundError, ReleaseError) as exc:
        raise ReleaseError(f"Required command not available: {command}") from exc


def repository(remote: str) -> tuple[str, str]:
    url = run("git", "remote", "get-url", remote)
    match = re.search(r"github\.com(?::|/)([^/]+)/([^/]+?)(?:\.git)?$", url)
    if not match:
        raise ReleaseError(f"Cannot determine GitHub repository from remote {remote}: {url}")
    return match.group(1), match.group(2)


def gh_json(repo: str, endpoint: str) -> object:
    output = run("gh", "api", f"repos/{repo}/{endpoint}")
    return json.loads(output)


def parse_version(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise ReleaseError(f"Latest stable tag is not semantic: v{version}")
    return tuple(map(int, match.groups()))


def bump_version(version: str, bump: str) -> str:
    major, minor, patch = parse_version(version)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "feature":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def validate_version_channel(version: str, channel: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?", version):
        raise ReleaseError(f"Invalid cross-registry version: {version}")
    if (channel == "stable") != ("-" not in version) or (channel != "stable" and f"-{channel}." not in version):
        raise ReleaseError(f"Version {version} does not match the {channel} channel")


def infer_category(title: str, labels: list[str]) -> str:
    normalized = {label.lower() for label in labels}
    if normalized & {"security", "area: security", "type: security"}:
        return "Security"
    if normalized & {"performance", "area: performance", "type: performance"}:
        return "Performance"
    if normalized & {"documentation", "docs", "type: docs"}:
        return "Documentation"
    commit_type = re.match(r"([a-z]+)(?:\([^)]*\))?!?:", title.lower())
    kind = commit_type.group(1) if commit_type else ""
    return {
        "feat": "Features",
        "fix": "Fixes",
        "perf": "Performance",
        "docs": "Documentation",
    }.get(kind, "Maintenance")


def clean_title(title: str) -> str:
    return re.sub(r"^[a-z]+(?:\([^)]*\))?!?:\s*", "", title, flags=re.IGNORECASE).strip().rstrip(".")


def is_breaking(title: str, labels: list[str], body: str = "") -> bool:
    return bool(
        re.match(r"^[a-z]+(?:\([^)]*\))?!:", title, flags=re.IGNORECASE)
        or any("breaking" in label.lower() for label in labels)
        or "BREAKING CHANGE:" in body
    )


def commit_log(revision_range: str) -> list[Commit]:
    raw = run("git", "log", "--reverse", "--format=%H%x1f%an%x1f%ae%x1f%s%x1f%B%x1e", revision_range)
    commits = []
    for record in raw.split("\x1e"):
        fields = record.strip().split("\x1f", 4)
        if len(fields) == 5:
            commits.append(Commit(*fields))
    return commits


def discover_changes(repo: str, previous_tag: str, branch: str) -> list[Change]:
    changes: list[Change] = []
    seen_prs: set[int] = set()
    for commit in commit_log(f"{previous_tag}..{branch}"):
        pulls = gh_json(repo, f"commits/{commit.sha}/pulls")
        matching = [pr for pr in pulls if pr.get("merged_at") and pr.get("base", {}).get("ref") == "main"]
        pr = max(matching, key=lambda item: item["merged_at"]) if matching else None
        pr_number = pr["number"] if pr else None
        if changes and pr_number is not None and changes[-1].pr == pr_number:
            changes[-1].commits.append(commit.sha)
            continue
        if pr_number in seen_prs:
            raise ReleaseError(f"PR #{pr_number} is not contiguous in git history")
        if pr_number:
            seen_prs.add(pr_number)
        labels = [label["name"] for label in pr.get("labels", [])] if pr else []
        title = pr["title"] if pr else commit.title
        user = pr.get("user") if pr else None
        login = user.get("login") if user else None
        association = pr.get("author_association", "") if pr else ""
        change = Change(
            commits=[commit.sha],
            title=title,
            author_name=commit.author_name,
            author_email=commit.author_email,
            pr=pr_number,
            url=pr.get("html_url") if pr else None,
            body=pr.get("body") or "" if pr else commit.message,
            labels=labels,
            contributor=Contributor(
                name=user.get("login", commit.author_name) if user else commit.author_name,
                login=login,
                first_time=association == "FIRST_TIME_CONTRIBUTOR",
            ),
        )
        change.category = infer_category(title, labels)
        change.include_in_notes = change.category != "Maintenance"
        change.breaking = is_breaking(title, labels, change.body)
        changes.append(change)
    return changes


def coauthors(commits: list[Commit]) -> list[Contributor]:
    contributors: list[Contributor] = []
    pattern = re.compile(r"^Co-authored-by:\s*(.+?)\s*<([^>]+)>$", re.IGNORECASE | re.MULTILINE)
    for commit in commits:
        for name, email in pattern.findall(commit.message):
            login_match = re.search(r"(?:\d+\+)?([^@+]+)@users\.noreply\.github\.com$", email)
            contributors.append(Contributor(name=name.strip(), login=login_match.group(1) if login_match else None))
    return contributors


def all_contributors(changes: list[Change], commits: list[Commit]) -> list[Contributor]:
    result: dict[str, Contributor] = {}
    commit_authors = []
    for commit in commits:
        login_match = re.search(r"(?:\d+\+)?([^@+]+)@users\.noreply\.github\.com$", commit.author_email)
        commit_authors.append(Contributor(name=commit.author_name, login=login_match.group(1) if login_match else None))
    candidates = [*(change.contributor for change in changes), *commit_authors, *coauthors(commits)]
    for contributor in candidates:
        if not contributor:
            continue
        raw = contributor.login or contributor.name
        key = re.sub(r"[^a-z0-9]", "", raw, flags=re.IGNORECASE).lower()
        if raw.lower().endswith("[bot]") or key in {"dependabot", "githubactions"}:
            continue
        existing = result.get(key)
        if existing:
            existing.first_time |= contributor.first_time
            if contributor.login:
                existing.login = contributor.login
        else:
            result[key] = contributor
    return sorted(result.values(), key=lambda item: item.label.lower())


def migration_changes(changes: list[Change]) -> list[Change]:
    result = []
    for change in changes:
        paths = set()
        for sha in change.commits:
            paths.update(run("git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines())
        if any(
            path.startswith("observal-server/alembic/versions/")
            or path.startswith("observal-server/clickhouse/migrations/")
            for path in paths
        ):
            result.append(change)
    return result


def grouped(changes: list[Change]) -> dict[str, list[Change]]:
    return {
        category: [change for change in changes if change.include_in_notes and change.category == category]
        for category in CATEGORIES
    }


def render_entries(changes: list[Change]) -> str:
    return "\n".join(f"- {clean_title(change.title)} ({change.reference})" for change in changes)


def render_changelog_section(version: str, date: str, changes: list[Change]) -> str:
    lines = [f"## [{version}] - {date}"]
    selected = [change for change in changes if change.include_in_notes]
    if not selected:
        return "\n".join([*lines, "", "No user-facing changes."])
    for category, items in grouped(changes).items():
        if items:
            lines.extend(("", f"### {category}", "", render_entries(items)))
    return "\n".join(lines)


def render_release_notes(
    version: str,
    previous_tag: str,
    cutoff: str,
    changes: list[Change],
    contributors: list[Contributor],
) -> str:
    selected = [change for change in changes if change.include_in_notes]
    highlights = [change for change in selected if change.highlight]
    breaking = [change for change in selected if change.breaking]
    lines = [
        "<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->",
        # REUSE-IgnoreStart
        "<!-- SPDX-License-Identifier: Apache-2.0 -->",
        # REUSE-IgnoreEnd
        "",
        f"# Observal v{version}",
        "",
        f"This release includes {len(changes)} change groups through `{cutoff[:7]}`.",
    ]
    if highlights:
        lines.extend(("", "## Highlights", "", render_entries(highlights)))
    if breaking:
        lines.extend(("", "## Breaking changes", "", render_entries(breaking)))
    for category, items in grouped(changes).items():
        regular = [item for item in items if item not in highlights and item not in breaking]
        if regular:
            lines.extend(("", f"## {category}", "", render_entries(regular)))
    lines.extend(("", "## Contributors", ""))
    if contributors:
        for contributor in contributors:
            suffix = " (first contribution)" if contributor.first_time else ""
            lines.append(f"- {contributor.label}{suffix}")
    else:
        lines.append("- No human contributors detected")
    lines.extend(
        (
            "",
            "## Full comparison",
            "",
            f"[{previous_tag}...v{version}](https://github.com/Observal/Observal/compare/{previous_tag}...v{version})",
            "",
        )
    )
    return "\n".join(lines)


def prepend_changelog(existing: str, section: str, version: str) -> str:
    if re.search(rf"^## \[{re.escape(version)}\]", existing, re.MULTILINE):
        raise ReleaseError(f"CHANGELOG.md already contains version {version}")
    position = existing.find(CHANGELOG_ANCHOR)
    if position < 0:
        raise ReleaseError("CHANGELOG.md introduction was not found")
    position += len(CHANGELOG_ANCHOR)
    return existing[:position] + section.rstrip() + "\n\n" + existing[position:]


def set_version(path: Path, version: str) -> None:
    text = path.read_text()
    if path.suffix == ".toml":
        project = re.search(r"(?ms)^\[project\]\s*$.*?(?=^\[|\Z)", text)
        if not project:
            raise ReleaseError(f"Could not find [project] in {path}")
        block, count = re.subn(
            r'^(version\s*=\s*")[^"]+("\s*)$', rf"\g<1>{version}\2", project.group(), flags=re.MULTILINE
        )
        updated = text[: project.start()] + block + text[project.end() :]
    else:
        data = json.loads(text)
        if not isinstance(data, dict) or "version" not in data:
            raise ReleaseError(f"Could not find a top-level version in {path}")
        updated, count = re.subn(
            r'^( {2}"version"\s*:\s*")[^"]+("\s*,?)$', rf"\g<1>{version}\2", text, flags=re.MULTILINE
        )
    if count != 1:
        raise ReleaseError(f"Could not update exactly one version in {path}")
    path.write_text(updated)


def write_manifest(
    path: Path,
    version: str,
    channel: str,
    previous_tag: str,
    cutoff: str,
    changes: list[Change],
) -> None:
    prs = ", ".join(str(change.pr) for change in changes if change.pr)
    path.write_text(
        "# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>\n"
        # REUSE-IgnoreStart
        "# SPDX-License-Identifier: Apache-2.0\n\n"
        # REUSE-IgnoreEnd
        f'version = "{version}"\n'
        f'channel = "{channel}"\n'
        f'previous_tag = "{previous_tag}"\n'
        f'cutoff = "{cutoff}"\n'
        f'created_at = "{datetime.now(UTC).isoformat()}"\n'
        f"commit_count = {sum(len(change.commits) for change in changes)}\n"
        f"included_prs = [{prs}]\n"
    )


def pr_body(version: str, previous_tag: str, cutoff: str, changes: list[Change], preview: str) -> str:
    return f"""## Purpose / Description
Prepare Observal v{version} from the contiguous release range `{previous_tag}..{cutoff[:7]}`.

## Fixes
No linked issue. This is a release preparation change.

## Approach
The release contains {len(changes)} PR or commit groups. This PR updates version metadata, lockfiles, the curated release notes, and prepends one new changelog section without rewriting existing changelog history.

Merge this PR with a merge commit. Squash and rebase merges are rejected by the release workflow.

## How Has This Been Tested?

The release tool validated ancestry, tag state, version consistency, allowed changed files, changelog preservation, and release-note generation. The release workflow will build and verify every artifact before publishing.

## Learning (optional, can help others)
Not applicable. The implementation uses existing Git, GitHub CLI, uv, and repository build tooling.

## Release preview

{preview}

## Checklist

- [x] You have a descriptive commit message with a short title (first line, max 50 chars).
- [ ] You have commented your code, particularly in hard-to-understand areas. Not applicable, this PR contains generated release metadata.
- [x] You have performed a self-review of your own code.
- [ ] UI changes: include screenshots of all affected screens. Not applicable, this PR has no UI changes.

## AI Assistance

- [ ] Yes (Please Specify the tool): Not applicable to generated release metadata.
- [ ] Was the generated code manually reviewed and tested? Not applicable.
"""


def ensure_preflight(upstream: str) -> None:
    for command in ("git", "gh", "uv"):
        require(command)
    if run("git", "status", "--porcelain"):
        raise ReleaseError("Working tree is dirty. Commit or stash changes first.")
    if run("git", "branch", "--show-current") != "main":
        raise ReleaseError("Releases must be prepared from main")
    run("gh", "auth", "status")
    run("git", "fetch", upstream, "main", "--tags")
    if run("git", "rev-parse", "HEAD") != run("git", "rev-parse", f"{upstream}/main"):
        raise ReleaseError(f"Local main must exactly match {upstream}/main")


def latest_tag(branch: str) -> str:
    tags = run("git", "tag", "--merged", branch, "--list", "v[0-9]*").splitlines()
    stable = [tag for tag in tags if re.fullmatch(r"v\d+\.\d+\.\d+", tag)]
    if not stable:
        raise ReleaseError(f"No stable release tag is reachable from {branch}")
    return max(stable, key=lambda tag: parse_version(tag[1:]))


def _ask(prompt):
    answer = prompt.ask()
    if answer is None:
        raise ReleaseError("Release cancelled")
    return answer


def choose_release(changes: list[Change], previous_version: str, tags: set[str]):
    import questionary
    from questionary import Choice

    cutoff_choices = [
        Choice(
            f"{index + 1:>3}. {('#' + str(change.pr)) if change.pr else change.commits[-1][:7]}  "
            f"{clean_title(change.title)}  ({len(change.commits)} commit{'s' if len(change.commits) != 1 else ''})",
            value=index,
        )
        for index, change in enumerate(changes)
    ]
    cutoff_index = _ask(
        questionary.select(
            "Release through which pull request or commit?",
            choices=cutoff_choices,
            default=cutoff_choices[-1],
        )
    )
    included = changes[: cutoff_index + 1]
    selected_notes = _ask(
        questionary.checkbox(
            "Which included changes belong in public release notes?",
            choices=[
                Choice(
                    f"{change.category}: {clean_title(change.title)}",
                    value=index,
                    checked=change.include_in_notes,
                )
                for index, change in enumerate(included)
            ],
        )
    )
    selected_set = set(selected_notes)
    for index, change in enumerate(included):
        change.include_in_notes = index in selected_set
    if selected_notes and _ask(questionary.confirm("Edit selected note titles and categories?", default=False)):
        for index in selected_notes:
            change = included[index]
            change.title = _ask(
                questionary.text("Release-note title:", default=clean_title(change.title))
            ) or clean_title(change.title)
            change.category = _ask(questionary.select("Category:", choices=CATEGORIES, default=change.category))
            change.highlight = _ask(questionary.confirm("Highlight this change?", default=False))
            change.breaking = _ask(questionary.confirm("Breaking change?", default=change.breaking))
    suggested = (
        "major"
        if any(change.breaking for change in included)
        else (
            "feature"
            if any(change.category == "Features" for change in included if change.include_in_notes)
            else "patch"
        )
    )
    bump = _ask(
        questionary.select(
            "Version bump:",
            choices=[suggested, *[item for item in ("patch", "feature", "major", "custom") if item != suggested]],
            default=suggested,
        )
    )
    version = _ask(questionary.text("Version:")) if bump == "custom" else bump_version(previous_version, bump)
    channel = _ask(questionary.select("Release channel:", choices=("stable", "rc", "beta", "alpha"), default="stable"))
    if channel != "stable" and "-" not in version:
        serial = 1
        while f"v{version}-{channel}.{serial}" in tags:
            serial += 1
        version = f"{version}-{channel}.{serial}"
    validate_version_channel(version, channel)
    return included, version, channel


def prepare(preview_only: bool, upstream: str = "upstream", fork: str = "origin") -> None:
    import questionary

    ensure_preflight(upstream)
    owner, name = repository(upstream)
    repo = f"{owner}/{name}"
    fork_owner, _ = repository(fork)
    branch = f"{upstream}/main"
    previous_tag = latest_tag(branch)
    changes = discover_changes(repo, previous_tag, branch)
    if not changes:
        raise ReleaseError(f"No commits exist after {previous_tag}")
    included, version, channel = choose_release(
        changes, previous_tag[1:], set(run("git", "tag", "--list").splitlines())
    )
    undocumented_migrations = [change for change in migration_changes(included) if not change.include_in_notes]
    if undocumented_migrations:
        names = ", ".join(
            f"#{change.pr}" if change.pr else change.commits[-1][:7] for change in undocumented_migrations
        )
        raise ReleaseError(f"Database migrations must be included in release notes: {names}")
    cutoff = included[-1].commits[-1]
    commits = commit_log(f"{previous_tag}..{cutoff}")
    contributors = all_contributors(included, commits)
    date = datetime.now(UTC).date().isoformat()
    changelog_section = render_changelog_section(version, date, included)
    notes = render_release_notes(version, previous_tag, cutoff, included, contributors)
    print("\nIncluded:")
    print(f"  {len(included)} change groups, {len(commits)} commits, {len(contributors)} contributors")
    print(f"Deferred: {len(changes) - len(included)} change groups")
    print(f"Version:  {version} ({channel})")
    print("\nRelease notes preview:\n")
    print(notes)
    if preview_only:
        return
    if not _ask(questionary.confirm("Create and push this release PR?", default=False)):
        raise ReleaseError("Release cancelled")

    release_branch = f"release/v{version}"
    worktree = ROOT / ".worktrees" / f"release-v{version}"
    if worktree.exists() or run("git", "branch", "--list", release_branch):
        raise ReleaseError(f"Release branch or worktree already exists: {release_branch}")
    run("git", "worktree", "add", "-b", release_branch, str(worktree), cutoff, capture=False)
    try:
        for relative in VERSION_FILES:
            set_version(worktree / relative, version)
        run("uv", "lock", cwd=worktree, capture=False)
        run("uv", "lock", cwd=worktree / "observal-server", capture=False)
        changelog = worktree / "CHANGELOG.md"
        changelog.write_text(prepend_changelog(changelog.read_text(), changelog_section, version))
        notes_path = worktree / ".github" / "release-notes.md"
        notes_path.write_text(notes)
        write_manifest(worktree / ".release.toml", version, channel, previous_tag, cutoff, included)
        run("git", "add", *RELEASE_FILES, cwd=worktree)
        changed = set(run("git", "diff", "--cached", "--name-only", cwd=worktree).splitlines())
        unexpected = changed - set(RELEASE_FILES)
        unexpected.update(run("git", "diff", "--name-only", cwd=worktree).splitlines())
        unexpected.update(run("git", "ls-files", "--others", "--exclude-standard", cwd=worktree).splitlines())
        if unexpected:
            raise ReleaseError(f"Release preparation changed unexpected files: {sorted(unexpected)}")
        run("git", "diff", "--cached", "--check", cwd=worktree)
        run("git", "commit", "-s", "-m", f"chore(release): v{version}", cwd=worktree, capture=False)
        run("git", "push", fork, release_branch, cwd=worktree, capture=False)
        body = pr_body(version, previous_tag, cutoff, included, changelog_section)
        with tempfile.TemporaryDirectory() as tmpdir:
            body_path = Path(tmpdir) / "release-pr-body.md"
            body_path.write_text(body)
            url = run(
                "gh",
                "pr",
                "create",
                "--repo",
                repo,
                "--head",
                f"{fork_owner}:{release_branch}",
                "--base",
                "main",
                "--title",
                f"chore(release): v{version}",
                "--body-file",
                str(body_path),
                cwd=worktree,
            )
        print(f"\nRelease PR created: {url}")
        print("Merge it with a merge commit. The workflow rejects squash and rebase merges.")
    except Exception:
        print(f"Release worktree preserved for recovery: {worktree}", file=sys.stderr)
        raise
    else:
        run("git", "worktree", "remove", str(worktree), capture=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="render the release without creating a branch or PR")
    parser.add_argument("--upstream", default="upstream", help="remote for the canonical repository")
    parser.add_argument("--fork", default="origin", help="remote that receives the release branch")
    args = parser.parse_args()
    try:
        prepare(args.preview, args.upstream, args.fork)
    except (ReleaseError, KeyboardInterrupt) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
