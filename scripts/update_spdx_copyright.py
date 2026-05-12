#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""
Pre-commit hook: ensures the committer's SPDX-FileCopyrightText line is present
in every staged file that already has an SPDX header.

- Reads committer identity from git config (user.name + user.email)
- Skips files with no existing SPDX header (new files without headers are
  caught by reuse-lint in CI)
- Skips binary files and files in LICENSES/ or .reuse/
- Uses the current year
- Idempotent: does nothing if the email is already in the header
"""

import subprocess
import sys
from datetime import date
from pathlib import Path

SKIP_DIRS = {"LICENSES", ".reuse", "node_modules", ".git", ".venv", "__pycache__"}
SKIP_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".map", ".lock"}


def git_identity() -> tuple[str, str]:
    def run(args):
        return subprocess.run(args, capture_output=True, text=True).stdout.strip()

    name = run(["git", "config", "user.name"])
    email = run(["git", "config", "user.email"])
    if not name or not email:
        print("::error:: git user.name or user.email not configured", file=sys.stderr)
        sys.exit(1)
    return name, email


def comment_prefix(path: Path) -> tuple[str, str] | None:
    """Return (prefix, suffix) for the file's comment style, or None to skip."""
    name = path.name
    ext = path.suffix.lower()

    if ext in SKIP_EXTS:
        return None
    if ext in {
        ".py",
        ".sh",
        ".yml",
        ".yaml",
        ".toml",
        ".tf",
        ".tfvars",
        ".conf",
        ".cfg",
        ".env",
        ".example",
        ".gitignore",
    }:
        return ("# ", "")
    if ext in {".ts", ".tsx", ".mjs", ".js"}:
        return ("// ", "")
    if ext in {".md", ".xml", ".svg", ".html"}:
        return ("<!-- ", " -->")
    if ext == ".css":
        return ("/* ", " */")
    if name in {
        "Makefile",
        "Dockerfile",
        "Dockerfile.api",
        "Dockerfile.web",
        ".dockerignore",
        ".editorconfig",
        ".gitattributes",
    }:
        return ("# ", "")
    # default
    return ("# ", "")


def already_has_email(raw: bytes, email: str) -> bool:
    try:
        head = raw[:1024].decode("utf-8", errors="ignore")
    except Exception:
        return True  # skip on error
    return email.lower() in head.lower()


def has_spdx_header(raw: bytes) -> bool:
    try:
        return b"SPDX-FileCopyrightText" in raw[:512]
    except Exception:
        return False


def inject_copyright(path: Path, name: str, email: str, year: int):
    style = comment_prefix(path)
    if style is None:
        return

    prefix, suffix = style
    new_line = f"{prefix}SPDX-FileCopyrightText: {year} {name} <{email}>{suffix}\n"

    raw = path.read_bytes()
    eol = b"\r\n" if b"\r\n" in raw[:1024] else b"\n"
    nl = "\r\n" if eol == b"\r\n" else "\n"

    text = raw.decode("utf-8", errors="replace")

    # Insert after the last existing SPDX-FileCopyrightText line
    lines = text.splitlines(keepends=True)
    last_copyright_idx = -1
    for i, line in enumerate(lines):
        if "SPDX-FileCopyrightText" in line:
            last_copyright_idx = i

    if last_copyright_idx == -1:
        return  # no existing copyright lines, skip

    new_line_eol = new_line.rstrip("\r\n") + nl
    lines.insert(last_copyright_idx + 1, new_line_eol)
    path.write_bytes("".join(lines).encode("utf-8", errors="replace"))


def add_fresh_header(path: Path, name: str, email: str, year: int):
    """Add a complete SPDX header to a file that doesn't have one yet."""
    style = comment_prefix(path)
    if style is None:
        return

    prefix, suffix = style
    copyright_line = f"{prefix}SPDX-FileCopyrightText: {year} {name} <{email}>{suffix}"
    # REUSE-IgnoreStart
    license_line = f"{prefix}SPDX-License-Identifier: AGPL-3.0-only{suffix}"
    # REUSE-IgnoreEnd

    raw = path.read_bytes()
    eol = b"\r\n" if b"\r\n" in raw[:1024] else b"\n"
    nl = "\r\n" if eol == b"\r\n" else "\n"

    text = raw.decode("utf-8", errors="replace")

    header = copyright_line + nl + license_line + nl + nl

    # Preserve shebang on first line
    if text.startswith("#!"):
        newline_pos = text.index("\n") + 1
        new_content = text[:newline_pos] + header + text[newline_pos:]
    else:
        new_content = header + text

    path.write_bytes(new_content.encode("utf-8", errors="replace"))


def staged_files() -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
    )
    paths = []
    for line in result.stdout.splitlines():
        p = Path(line.strip())
        if not p.exists():
            continue
        parts = set(p.parts)
        if parts & SKIP_DIRS:
            continue
        paths.append(p)
    return paths


def main():
    name, email = git_identity()
    year = date.today().year
    files = staged_files()
    modified = []
    created = []

    for path in files:
        try:
            raw = path.read_bytes()
        except Exception:
            continue

        if not has_spdx_header(raw):
            # New file without header — add a fresh one
            add_fresh_header(path, name, email, year)
            subprocess.run(["git", "add", str(path)])
            created.append(str(path))
            continue
        if already_has_email(raw, email):
            continue

        inject_copyright(path, name, email, year)
        # re-stage the file
        subprocess.run(["git", "add", str(path)])
        modified.append(str(path))

    if created:
        print(f"[spdx-update] Added SPDX header to {len(created)} new file(s):")
        for f in created:
            print(f"  {f}")
    if modified:
        print(f"[spdx-update] Added copyright line to {len(modified)} file(s):")
        for f in modified:
            print(f"  {f}")


if __name__ == "__main__":
    main()
