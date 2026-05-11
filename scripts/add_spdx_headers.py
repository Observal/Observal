#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""
Adds SPDX headers to all source files.
- Runs git log per file to collect real authors and year ranges
- Deduplicates authors with multiple emails
- Skips bots (renovate, github-actions)
- Inline headers for commentable file types
- REUSE.toml for JSON, images, lock files, binaries
- ee/ files get LicenseRef-Observal-Enterprise
- Preserves original line endings (CRLF vs LF)
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Author deduplication: email (lowercase) -> (canonical name, canonical email)
# ---------------------------------------------------------------------------
EMAIL_CANONICAL = {
    # Hari Srinivasan (repo owner)
    "79502699+haz3-jolt@users.noreply.github.com": ("Hari Srinivasan", "harisrini21@gmail.com"),
    "harisrini21@gmail.com": ("Hari Srinivasan", "harisrini21@gmail.com"),
    # Apoorv Garg
    "apoorvgarg.21@gmail.com": ("Apoorv Garg", "apoorvgarg.21@gmail.com"),
    # Subramania Raja (dhanpraja231)
    "66559537+dhanpraja231@users.noreply.github.com": ("Subramania Raja", "dhanpraja231@gmail.com"),
    "dhanpraja231@gmail.com": ("Subramania Raja", "dhanpraja231@gmail.com"),
    # Kaushik Kumar
    "kaushikrjpm10@gmail.com": ("Kaushik Kumar", "kaushikrjpm10@gmail.com"),
    # Lokesh Selvam
    "lokeshselvam7025@gmail.com": ("Lokesh Selvam", "lokeshselvam7025@gmail.com"),
    # Luca Magrini
    "89993099+luca12341234@users.noreply.github.com": ("Luca Magrini", "lucamagrini1234@gmail.com"),
    "lucamagrini1234@gmail.com": ("Luca Magrini", "lucamagrini1234@gmail.com"),
    # Shaan Narendran
    "shaannaren06@gmail.com": ("Shaan Narendran", "shaannaren06@gmail.com"),
    "shaannarendran@shaans-macbook-pro.local": ("Shaan Narendran", "shaannaren06@gmail.com"),
    # Shreem Seth
    "shreemseth26@gmail.com": ("Shreem Seth", "shreemseth26@gmail.com"),
    # Srihari
    "sriharilegend23@gmail.com": ("SrihariLegend", "sriharilegend23@gmail.com"),
    # Vishnu M
    "vishnu.muthiah04@gmail.com": ("Vishnu Muthiah", "vishnu.muthiah04@gmail.com"),
    # Swathi Saravanan
    "ss4522@cornell.edu": ("Swathi Saravanan", "ss4522@cornell.edu"),
    # Aryan Iyappan
    "aryaniyappan2006@gmail.com": ("Aryan Iyappan", "aryaniyappan2006@gmail.com"),
    # Devaansh Dubey
    "devaanshdubey@gmail.com": ("Devaansh Dubey", "devaanshdubey@gmail.com"),
    # Tanvi Reddy
    "reddyplayer22@gmail.com": ("Tanvi Reddy", "reddyplayer22@gmail.com"),
    # Santhosh Raja
    "santhoshpkraja2004@gmail.com": ("Santhosh Raja", "santhoshpkraja2004@gmail.com"),
    # Ai-chan
    "aoikabu12@gmail.com": ("Ai-chan-0411", "aoikabu12@gmail.com"),
    # Hemalatha Madeswaran
    "hemalathamadeswaran@gmail.com": ("Hemalatha Madeswaran", "hemalathamadeswaran@gmail.com"),
    # Naraen Rammoorthi
    "naraen13@gmail.com": ("Naraen Rammoorthi", "naraen13@gmail.com"),
    # DoomsCoder
    "vedantkakade05@gmail.com": ("DoomsCoder", "vedantkakade05@gmail.com"),
    # vikeesh (no real email found, keep github noreply)
    "74416966+vikeesh@users.noreply.github.com": ("vikeesh", "74416966+vikeesh@users.noreply.github.com"),
}

BOT_EMAILS = {
    "29139614+renovate[bot]@users.noreply.github.com",
    "41898282+github-actions[bot]@users.noreply.github.com",
    "github-actions[bot]@users.noreply.github.com",
}

# ---------------------------------------------------------------------------
# File type -> comment style: (prefix, suffix)
# None means: use REUSE.toml
# ---------------------------------------------------------------------------
COMMENT_STYLES = {
    ".py": ("# ", ""),
    ".sh": ("# ", ""),
    ".yml": ("# ", ""),
    ".yaml": ("# ", ""),
    ".toml": ("# ", ""),
    ".tf": ("# ", ""),
    ".tfvars": ("# ", ""),
    ".conf": ("# ", ""),
    ".gitignore": ("# ", ""),
    ".example": ("# ", ""),
    ".env": ("# ", ""),
    ".cfg": ("# ", ""),
    ".css": ("/* ", " */"),
    ".ts": ("// ", ""),
    ".tsx": ("// ", ""),
    ".mjs": ("// ", ""),
    ".js": ("// ", ""),
    ".xml": ("<!-- ", " -->"),
    ".svg": ("<!-- ", " -->"),
    ".md": ("<!-- ", " -->"),
    ".html": ("<!-- ", " -->"),
    # REUSE.toml only
    ".json": None,
    ".lock": None,
    ".png": None,
    ".jpg": None,
    ".jpeg": None,
    ".gif": None,
    ".ico": None,
    ".woff": None,
    ".woff2": None,
    ".ttf": None,
    ".eot": None,
    ".map": None,
}

FILENAME_STYLES = {
    "Makefile": ("# ", ""),
    "Dockerfile": ("# ", ""),
    "Dockerfile.api": ("# ", ""),
    "Dockerfile.web": ("# ", ""),
    ".dockerignore": ("# ", ""),
    ".gitignore": ("# ", ""),
    ".editorconfig": ("# ", ""),
    ".gitattributes": ("# ", ""),
    ".gitbook.yaml": ("# ", ""),
}

SKIP_DIRS = {
    "node_modules",
    ".git",
    ".venv",
    "__pycache__",
    "alembic",
    ".worktrees",
    ".ruff_cache",
}

SKIP_FILES = {
    "pnpm-lock.yaml",
    "uv.lock",
    "package-lock.json",
    "LICENSE",
    "NOTICE",
    "COPYING",
    "CLA.md",
    "add_spdx_headers.py",
}


def get_comment_style(path: Path):
    name = path.name
    if name in FILENAME_STYLES:
        return FILENAME_STYLES[name]
    ext = path.suffix.lower()
    if ext in COMMENT_STYLES:
        return COMMENT_STYLES[ext]
    return ("# ", "")  # default: treat as hash-comment text file


def get_authors(rel_path: str) -> dict:
    result = subprocess.run(
        ["git", "log", "--follow", "--format=%ae|%an|%ad", "--date=format:%Y", "--", rel_path],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    seen = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        email_raw, name_raw, year_str = parts
        email_lower = email_raw.strip().lower()
        try:
            year = int(year_str.strip())
        except ValueError:
            continue
        if email_lower in BOT_EMAILS:
            continue
        canonical = EMAIL_CANONICAL.get(email_lower)
        if canonical:
            canon_name, canon_email = canonical
        else:
            canon_name = name_raw.strip()
            canon_email = email_raw.strip()
        key = canon_email.lower()
        if key not in seen:
            seen[key] = [canon_name, canon_email, year, year]
        else:
            seen[key][2] = min(seen[key][2], year)
            seen[key][3] = max(seen[key][3], year)
    return seen


def format_copyright_lines(authors: dict, prefix: str, suffix: str) -> list:
    lines = []
    for key in sorted(authors):
        name, email, min_yr, max_yr = authors[key]
        yr = str(min_yr) if min_yr == max_yr else f"{min_yr}-{max_yr}"
        lines.append(f"{prefix}SPDX-FileCopyrightText: {yr} {name} <{email}>{suffix}")
    return lines


def get_license_id(path: Path) -> str:
    rel = str(path.relative_to(ROOT))
    if rel.startswith("ee/"):
        return "AGPL-3.0-only"
    return "AGPL-3.0-only"


def already_has_spdx(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(512)
        return b"SPDX-" in head
    except Exception:
        return False


def prepend_header(path: Path, header_lines: list):
    with open(path, "rb") as f:
        raw = f.read()

    # Detect original line ending and preserve it
    eol = b"\r\n" if b"\r\n" in raw[:1024] else b"\n"
    nl = "\r\n" if eol == b"\r\n" else "\n"

    original = raw.decode("utf-8", errors="replace")
    header = nl.join(header_lines) + nl + nl

    # Preserve shebang on first line
    if original.startswith("#!"):
        newline_pos = original.index("\n") + 1
        new_content = original[:newline_pos] + header + original[newline_pos:]
    else:
        new_content = header + original

    with open(path, "wb") as f:
        f.write(new_content.encode("utf-8", errors="replace"))


def build_reuse_toml(dep5_files: list) -> str:
    """Build REUSE.toml content for files that can't have inline headers."""
    lines = ["version = 1", ""]
    for path, authors in sorted(dep5_files, key=lambda x: str(x[0])):
        rel = str(path.relative_to(ROOT))
        license_id = get_license_id(path)
        lines.append("[[annotations]]")
        lines.append(f'path = "{rel}"')
        copyright_entries = []
        for key in sorted(authors):
            name, email, min_yr, max_yr = authors[key]
            yr = str(min_yr) if min_yr == max_yr else f"{min_yr}-{max_yr}"
            copyright_entries.append(f"SPDX-FileCopyrightText: {yr} {name} <{email}>")
        if len(copyright_entries) == 1:
            lines.append(f'SPDX-FileCopyrightText = "{copyright_entries[0]}"')
        else:
            entries = "[\n" + ",\n".join(f'  "{e}"' for e in copyright_entries) + "\n]"
            lines.append(f"SPDX-FileCopyrightText = {entries}")
        lines.append(f'SPDX-License-Identifier = "{license_id}"')
        lines.append("")
    return "\n".join(lines)


def iter_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        parts = set(path.relative_to(ROOT).parts)
        if parts & SKIP_DIRS:
            continue
        if path.name in SKIP_FILES:
            continue
        if "LICENSES" in parts or ".reuse" in parts:
            continue
        yield path


def main(dry_run: bool = True, limit: int = 0):
    inline_done = 0
    dep5_files = []
    skipped_no_authors = []
    skipped_already = []

    all_files = list(iter_files())
    if limit:
        all_files = all_files[:limit]

    total = len(all_files)
    print(f"Processing {total} files (dry_run={dry_run})...\n")

    for i, path in enumerate(all_files):
        rel = str(path.relative_to(ROOT))

        if already_has_spdx(path):
            skipped_already.append(rel)
            continue

        authors = get_authors(rel)
        if not authors:
            skipped_no_authors.append(rel)
            continue

        style = get_comment_style(path)
        license_id = get_license_id(path)

        if style is None:
            dep5_files.append((path, authors))
            continue

        prefix, suffix = style
        copyright_lines = format_copyright_lines(authors, prefix, suffix)
        # REUSE-IgnoreStart
        license_line = f"{prefix}SPDX-License-Identifier: {license_id}{suffix}"
        # REUSE-IgnoreEnd
        header = [*copyright_lines, license_line]

        if dry_run:
            print(f"[{rel}]")
            for line in header:
                print(f"  {line}")
            print()
        else:
            prepend_header(path, header)

        inline_done += 1
        if not dry_run and i % 50 == 0:
            print(f"  {i}/{total}...", file=sys.stderr)

    # REUSE.toml for non-commentable files
    if dep5_files:
        reuse_toml_path = ROOT / "REUSE.toml"
        if dry_run:
            print("=== REUSE.toml (first 60 lines) ===")
            content = build_reuse_toml(dep5_files)
            print("\n".join(content.splitlines()[:60]))
        else:
            reuse_toml_path.write_text(build_reuse_toml(dep5_files))

    print("\nSummary:")
    print(f"  Inline headers added : {inline_done}")
    print(f"  REUSE.toml entries   : {len(dep5_files)}")
    print(f"  Already had SPDX     : {len(skipped_already)}")
    print(f"  No git history       : {len(skipped_no_authors)}")
    if skipped_no_authors:
        print("  Files with no history:")
        for f in skipped_no_authors:
            print(f"    {f}")


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    lim = 0
    for arg in sys.argv[1:]:
        if arg.startswith("--limit="):
            lim = int(arg.split("=")[1])
    main(dry_run=dry, limit=lim)
