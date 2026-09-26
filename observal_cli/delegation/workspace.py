# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""A throwaway copy of the caller's working tree for a delegated agent.

The child runs in a detached ``git worktree`` of the caller's repository at
HEAD, with the caller's uncommitted changes and untracked (not ignored) files
laid on top, so it sees exactly what the caller sees. Whatever the child edits
stays there. When it finishes, the difference between the tree it started
from and the tree it left is returned as a patch; the caller decides whether
to ``git apply`` it. Nothing is committed and no ref is created: trees are
recorded through a private index file, so signing and hooks never run.

Outside a git repository the child gets an empty scratch directory.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger as optic

MAX_UNTRACKED_BYTES = 50 * 1024 * 1024
GIT_TIMEOUT = 120


class WorkspaceError(RuntimeError):
    pass


def _git(cwd: Path, *args: str, env: dict | None = None, input_bytes: bytes | None = None) -> bytes:
    full_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            input=input_bytes,
            capture_output=True,
            env=full_env,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceError(f"git {args[0]} failed to run") from exc
    if result.returncode != 0:
        raise WorkspaceError(f"git {args[0]} failed: {result.stderr.decode(errors='replace').strip()[:300]}")
    return result.stdout


def repo_root(path: Path) -> Path | None:
    try:
        out = _git(path, "rev-parse", "--show-toplevel").decode().strip()
    except WorkspaceError:
        return None
    if not out:
        return None
    try:
        _git(path, "rev-parse", "--verify", "HEAD")
    except WorkspaceError:
        return None  # unborn branch: nothing to check out
    return Path(out)


@dataclass
class Workspace:
    path: Path
    scratch: Path
    repo: Path | None
    start_tree: str | None = None
    base_tree: str | None = None
    setup_paths: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    _root: Path | None = None

    @property
    def is_git(self) -> bool:
        return self.repo is not None


def _write_tree(worktree: Path, index_file: Path) -> str:
    env = {"GIT_INDEX_FILE": str(index_file)}
    with contextlib.suppress(FileNotFoundError):
        index_file.unlink()
    _git(worktree, "add", "-A", env=env)
    return _git(worktree, "write-tree", env=env).decode().strip()


def _copy_untracked(repo: Path, worktree: Path, notes: list[str]) -> None:
    listing = _git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    total = 0
    skipped = 0
    for raw in listing.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="surrogateescape")
        src = repo / rel
        if not src.is_file() or src.is_symlink():
            continue
        size = src.stat().st_size
        if total + size > MAX_UNTRACKED_BYTES:
            skipped += 1
            continue
        dest = worktree / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        total += size
    if skipped:
        notes.append(f"{skipped} large untracked file(s) were not copied into the delegated workspace.")


def create(cwd: Path) -> Workspace:
    """Create the child's workspace for a caller working in ``cwd``."""
    # Resolved: on macOS the temp dir is under /var, a symlink to /private/var, and the
    # agent install rejects generated paths that resolve outside its target directory.
    root = Path(tempfile.mkdtemp(prefix="observal-delegate-")).resolve()
    scratch = root / "scratch"
    scratch.mkdir()
    repo = repo_root(cwd)
    if repo is None:
        empty = root / "workspace"
        empty.mkdir()
        return Workspace(
            path=empty,
            scratch=scratch,
            repo=None,
            notes=["The caller is not in a git repository; the agent worked in an empty directory."],
            _root=root,
        )

    worktree = root / "worktree"
    notes: list[str] = []
    try:
        _git(repo, "worktree", "add", "--detach", "--quiet", str(worktree), "HEAD")
        patch = _git(repo, "diff", "--binary", "HEAD")
        if patch.strip():
            try:
                _git(worktree, "apply", "--binary", "--whitespace=nowarn", input_bytes=patch)
            except WorkspaceError:
                notes.append("Uncommitted changes could not be applied; the agent saw HEAD.")
        _copy_untracked(repo, worktree, notes)
        start = _write_tree(worktree, scratch / "start.index")
    except WorkspaceError:
        with contextlib.suppress(WorkspaceError):
            _git(repo, "worktree", "remove", "--force", str(worktree))
        shutil.rmtree(root, ignore_errors=True)
        with contextlib.suppress(WorkspaceError):
            _git(repo, "worktree", "prune")
        raise
    # Keep the path relative to the checkout: a caller in a subdirectory works there.
    rel = cwd.resolve().relative_to(repo.resolve()) if cwd.resolve().is_relative_to(repo.resolve()) else Path()
    return Workspace(path=worktree / rel, scratch=scratch, repo=repo, start_tree=start, notes=notes, _root=root)


def mark_baseline(ws: Workspace) -> None:
    """Record the tree after the agent's own config was written, so it never shows up in the patch.

    Harnesses also rewrite their config when they start (OpenCode adds a
    ``$schema`` key to ``opencode.json``), so every path the install created or
    changed is left out of the patch, not just its initial content.
    """
    if not ws.is_git:
        return
    ws.base_tree = _write_tree(ws.path, ws.scratch / "base.index")
    if ws.start_tree and ws.start_tree != ws.base_tree:
        names = _git(ws.path, "diff-tree", "-r", "--name-only", "-z", ws.start_tree, ws.base_tree)
        ws.setup_paths = [p.decode("utf-8", errors="surrogateescape") for p in names.split(b"\0") if p]


def changes(ws: Workspace) -> str:
    """Patch from the baseline to the tree the agent left. Empty when nothing changed."""
    if not ws.is_git or not ws.base_tree:
        return ""
    after = _write_tree(ws.path, ws.scratch / "after.index")
    if after == ws.base_tree:
        return ""
    pathspec = [":(top)", *(f":(top,exclude,literal){p}" for p in ws.setup_paths)] if ws.setup_paths else []
    return _git(ws.path, "diff-tree", "-p", "--binary", "--no-color", ws.base_tree, after, "--", *pathspec).decode(
        "utf-8", errors="replace"
    )


def destroy(ws: Workspace) -> None:
    if ws.repo is not None and ws._root is not None:
        try:
            _git(ws.repo, "worktree", "remove", "--force", str(ws._root / "worktree"))
        except WorkspaceError:
            optic.debug("delegation worktree removal failed; pruning")
            with contextlib.suppress(WorkspaceError):
                _git(ws.repo, "worktree", "prune")
    if ws._root is not None:
        shutil.rmtree(ws._root, ignore_errors=True)
