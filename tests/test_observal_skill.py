# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Static validation for the bundled Observal skill.

These tests exercise ``observal_cli/skills/observal/SKILL.md`` without invoking
an LLM. They guarantee:

- The file exists at the path the installer expects.
- Frontmatter contains the fields IDE skill loaders rely on.
- Every fenced ``observal …`` shell command in the skill resolves to a real
  Typer command path.
- Every long flag mentioned for a documented command is a real flag on that
  command.
- The auto-generated reference block exists between the expected sentinels.
- The file stays under a sane size budget so it does not blow up LLM context.

If any of these regress, run::

    cd observal-server && uv run --with typer --with rich --with loguru \\
        --with pyyaml python ../scripts/sync_observal_skill.py

and update the skill copy accordingly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import typer
import yaml

from observal_cli.main import app

SKILL_PATH = Path(__file__).resolve().parent.parent / "observal_cli" / "skills" / "observal" / "SKILL.md"

SKILLS_DIR = Path(__file__).resolve().parent.parent / "observal_cli" / "skills"

REFERENCE_PATH = SKILLS_DIR / "observal" / "references" / "commands.md"

ALL_SKILL_PATHS = [
    SKILLS_DIR / "observal" / "SKILL.md",
    SKILLS_DIR / "observal-agents" / "SKILL.md",
    SKILLS_DIR / "observal-registry" / "SKILL.md",
    SKILLS_DIR / "observal-ops" / "SKILL.md",
    SKILLS_DIR / "observal-admin" / "SKILL.md",
    SKILLS_DIR / "observal-advanced" / "SKILL.md",
]

MAX_SKILL_LINES_EACH = 250  # Per-skill budget (split skills should be small)

REQUIRED_FRONTMATTER_FIELDS = ("name", "description", "version")
EXPECTED_COMMAND = "observal"
EXPECTED_NAME = "observal"

BEGIN_SENTINEL = "<!-- BEGIN AUTO-GENERATED COMMAND REFERENCE -->"
END_SENTINEL = "<!-- END AUTO-GENERATED COMMAND REFERENCE -->"

MAX_SKILL_LINES = 1500  # Total budget across all skills combined.

# Top-level groups intentionally hidden from the skill (developer-only tools).
# Mirrors the ``_HIDDEN_GROUPS`` set in scripts/sync_observal_skill.py.
_HIDDEN_GROUPS = {"server", "migrate", "logs", "support"}

# A few fenced examples are illustrative output rather than runnable commands
# (e.g. piped placeholders). Skip those during command resolution.
_PLACEHOLDER_TOKENS = {"<", ">", "..."}


# ── Helpers ────────────────────────────────────────────────────────────────


def _read_skill() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split ``---``-delimited frontmatter from the body."""
    # Strip leading HTML comments (SPDX headers) line by line.
    lines = text.splitlines(keepends=True)
    start = 0
    for i, line in enumerate(lines):
        stripped_line = line.strip()
        if (stripped_line.startswith("<!--") and stripped_line.endswith("-->")) or stripped_line == "":
            start = i + 1
        else:
            break
    remaining = "".join(lines[start:])
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)", remaining, re.DOTALL)
    if not match:
        raise AssertionError("SKILL.md is missing YAML frontmatter delimited by '---'. IDE skill loaders need it.")
    fm = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)
    return fm, body


def _iter_bash_blocks(body: str):
    """Yield each fenced ``bash`` code block (sans fences) in order."""
    pattern = re.compile(r"```(?:bash|shell|sh)\s*\n(.*?)```", re.DOTALL)
    for m in pattern.finditer(body):
        yield m.group(1)


@dataclass
class ParsedCommand:
    full: str  # Complete invocation as written.
    path: tuple[str, ...]  # ('agent', 'create')
    flags: tuple[str, ...]  # ('--name', '--description', ...)


def _parse_observal_invocations(body: str) -> list[ParsedCommand]:
    """Pull every ``observal …`` invocation out of fenced bash blocks."""
    commands: list[ParsedCommand] = []
    for block in _iter_bash_blocks(body):
        # Join continuation lines so multi-line commands parse as one.
        joined = re.sub(r"\\\s*\n\s*", " ", block)
        for raw_line in joined.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            # Strip leading shell prefixes like '$ ' or 'sudo '.
            line = re.sub(r"^\$\s+", "", line)

            # Collapse pipes/&&/|| chains into separate invocations so each
            # gets validated independently.
            for segment in re.split(r"\s+(?:\|\||&&|;|\|)\s+", line):
                segment = segment.strip()
                if not segment.startswith("observal"):
                    continue
                tokens = _shell_tokens(segment)
                if not tokens or tokens[0] != "observal":
                    continue

                # Walk tokens after `observal` accumulating the command path
                # until we hit a flag (after which everything is args/values).
                path: list[str] = []
                flags: list[str] = []
                seen_flag = False
                for tok in tokens[1:]:
                    if tok.startswith("-"):
                        seen_flag = True
                        # Strip ``=value`` from long flags.
                        flag = tok.split("=", 1)[0]
                        flags.append(flag)
                        continue
                    if seen_flag:
                        # Positional argument or flag value — never a path token.
                        continue
                    if not _is_identifier_token(tok):
                        # Looks like a placeholder (e.g. NAME, <id>) — stop
                        # accumulating; subsequent tokens are arguments.
                        seen_flag = True
                        continue
                    path.append(tok)

                if not path:
                    continue
                commands.append(ParsedCommand(full=segment, path=tuple(path), flags=tuple(flags)))
    return commands


def _shell_tokens(line: str) -> list[str]:
    """Cheap tokenizer: split on whitespace, respecting quoted spans loosely."""
    tokens: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in ("'", '"'):
            quote = ch
        elif ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


def _is_identifier_token(tok: str) -> bool:
    """True when the token looks like a Typer command name (kebab-ish)."""
    if not tok:
        return False
    if tok[0] in _PLACEHOLDER_TOKENS:
        return False
    # Command paths use [a-z0-9-]; anything else is an argument.
    return bool(re.fullmatch(r"[a-z][a-z0-9-]*", tok))


# ── Typer introspection ────────────────────────────────────────────────────


def _resolve_path(path: tuple[str, ...]):
    """Walk the Typer tree by command path. Returns the leaf command/group or None."""
    current_app: typer.Typer = app
    for i, segment in enumerate(path):
        # Match against subgroups first.
        for grp in current_app.registered_groups:
            if grp.name == segment:
                current_app = grp.typer_instance
                break
        else:
            # Fall through: maybe it's a leaf command.
            if i != len(path) - 1:
                return None
            for cmd in current_app.registered_commands:
                if cmd.name == segment or (cmd.callback and cmd.callback.__name__ == segment):
                    return cmd
            return None
    return current_app


def _flags_for_command(cmd: typer.models.CommandInfo) -> set[str]:
    """Extract every long flag declared on a Typer command callback."""
    if cmd.callback is None:
        return set()
    flags: set[str] = set()
    import inspect

    sig = inspect.signature(cmd.callback)
    for param in sig.parameters.values():
        default = param.default
        if isinstance(default, typer.models.OptionInfo):
            for decl in default.param_decls or ():
                # Handle Typer boolean pairs like "--active/--inactive"
                for part in decl.split("/"):
                    if part.startswith("--"):
                        flags.add(part.split("=", 1)[0])
            # Typer derives --param-name from the parameter name when no decl
            # is given. Mirror that.
            if not default.param_decls:
                flags.add(f"--{param.name.replace('_', '-')}")
        elif isinstance(default, typer.models.ArgumentInfo):
            # Arguments do not have flags.
            pass
        else:
            # Plain bool/str defaults still get a flag from Typer.
            if param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY):
                flags.add(f"--{param.name.replace('_', '-')}")
    return flags


def _all_command_paths() -> set[tuple[str, ...]]:
    """Return every reachable command path under the root app."""
    out: set[tuple[str, ...]] = set()

    def walk(prefix: tuple[str, ...], current: typer.Typer) -> None:
        for cmd in current.registered_commands:
            name = cmd.name or (cmd.callback.__name__ if cmd.callback else "")
            if name:
                out.add((*prefix, name))
        for grp in current.registered_groups:
            if not grp.name:
                continue
            if not prefix and grp.name in _HIDDEN_GROUPS:
                continue
            out.add((*prefix, grp.name))
            if grp.typer_instance is not None:
                walk((*prefix, grp.name), grp.typer_instance)

    walk((), app)
    return out


# ── Tests ──────────────────────────────────────────────────────────────────


class TestSkillFile:
    def test_skill_file_exists_at_installer_path(self):
        """``_install_observal_skill`` reads from this exact path."""
        assert SKILL_PATH.exists(), f"{SKILL_PATH} is missing"
        assert SKILL_PATH.is_file()

    def test_all_skill_files_exist(self):
        """All 6 intent-based skills must exist."""
        for path in ALL_SKILL_PATHS:
            assert path.exists(), f"{path} is missing"

    def test_reference_file_exists(self):
        """The auto-generated command reference must exist."""
        assert REFERENCE_PATH.exists(), f"{REFERENCE_PATH} is missing"

    def test_skill_file_under_size_budget(self):
        total = sum(len(p.read_text(encoding="utf-8").splitlines()) for p in ALL_SKILL_PATHS)
        assert total <= MAX_SKILL_LINES, (
            f"All skills combined have {total} lines (budget: {MAX_SKILL_LINES}). Tighten procedures or split further."
        )

    def test_each_skill_under_individual_budget(self):
        for path in ALL_SKILL_PATHS:
            lines = len(path.read_text(encoding="utf-8").splitlines())
            assert lines <= MAX_SKILL_LINES_EACH, (
                f"{path.parent.name}/SKILL.md has {lines} lines (budget: {MAX_SKILL_LINES_EACH}). "
                "Split into a smaller skill."
            )


class TestFrontmatter:
    def setup_method(self):
        self.frontmatter, self.body = _split_frontmatter(_read_skill())

    def test_required_fields_present(self):
        for field in REQUIRED_FRONTMATTER_FIELDS:
            assert field in self.frontmatter, f"frontmatter missing required field: {field}"
            assert self.frontmatter[field], f"frontmatter field {field!r} is empty"

    def test_name_matches_skill_directory(self):
        assert self.frontmatter["name"] == EXPECTED_NAME, (
            f"frontmatter name should be {EXPECTED_NAME!r} so IDE loaders find it"
        )

    def test_command_field_present_when_set(self):
        # ``command`` is optional but if present must point at the CLI binary.
        if "command" in self.frontmatter:
            assert self.frontmatter["command"] == EXPECTED_COMMAND

    def test_version_is_semverish(self):
        version = str(self.frontmatter["version"])
        assert re.fullmatch(r"\d+\.\d+\.\d+(?:[-+].*)?", version), f"version should look like semver, got {version!r}"


class TestAutoGenBlock:
    def test_sentinels_present(self):
        text = REFERENCE_PATH.read_text(encoding="utf-8")
        assert BEGIN_SENTINEL in text, (
            f"missing {BEGIN_SENTINEL!r} in references/commands.md. Run scripts/sync_observal_skill.py."
        )
        assert END_SENTINEL in text, (
            f"missing {END_SENTINEL!r} in references/commands.md. Run scripts/sync_observal_skill.py."
        )
        begin = text.index(BEGIN_SENTINEL)
        end = text.index(END_SENTINEL)
        assert begin < end, "sentinels are out of order"

    def test_auto_gen_block_lists_every_visible_top_level_group(self):
        text = REFERENCE_PATH.read_text(encoding="utf-8")
        block = text[text.index(BEGIN_SENTINEL) : text.index(END_SENTINEL)]
        for grp in app.registered_groups:
            if not grp.name or grp.name in _HIDDEN_GROUPS:
                continue
            assert f"observal {grp.name}" in block, (
                f"auto-gen block does not mention top-level group {grp.name!r}. Run scripts/sync_observal_skill.py."
            )


class TestCommandResolution:
    def setup_method(self):
        # Collect commands from ALL skill files.
        self.commands: list[ParsedCommand] = []
        for path in ALL_SKILL_PATHS:
            _, body = _split_frontmatter(path.read_text(encoding="utf-8"))
            self.commands.extend(_parse_observal_invocations(body))
        self.valid_paths = _all_command_paths()

    def test_at_least_one_command_documented(self):
        assert self.commands, "skill body has no observal CLI invocations"

    def test_every_command_resolves(self):
        unresolved: list[str] = []
        for parsed in self.commands:
            # Try progressively shorter prefixes; the first that resolves wins.
            # That handles cases where the parser greedily ate an argument.
            for length in range(len(parsed.path), 0, -1):
                candidate = parsed.path[:length]
                if candidate in self.valid_paths:
                    break
                resolved = _resolve_path(candidate)
                if resolved is not None:
                    break
            else:
                unresolved.append(f"{parsed.full!r} → path={parsed.path}")
        assert not unresolved, (
            "skill references commands that do not exist in the CLI:\n  "
            + "\n  ".join(unresolved)
            + "\nRun scripts/sync_observal_skill.py and update procedures."
        )


class TestFlagResolution:
    """Every long flag mentioned in any skill must exist on its command."""

    def setup_method(self):
        self.commands: list[ParsedCommand] = []
        for path in ALL_SKILL_PATHS:
            _, body = _split_frontmatter(path.read_text(encoding="utf-8"))
            self.commands.extend(_parse_observal_invocations(body))

    def test_documented_flags_exist(self):
        bad: list[str] = []
        seen: set[tuple[tuple[str, ...], str]] = set()

        for parsed in self.commands:
            # Find the command leaf this invocation targets.
            leaf = None
            for length in range(len(parsed.path), 0, -1):
                candidate = parsed.path[:length]
                resolved = _resolve_path(candidate)
                if isinstance(resolved, typer.models.CommandInfo):
                    leaf = resolved
                    break
            if leaf is None:
                continue  # Resolution test will already have flagged this.

            valid_flags = _flags_for_command(leaf)
            for flag in parsed.flags:
                if not flag.startswith("--"):
                    continue  # Skip short flags; they are noisier to validate.
                key = (parsed.path, flag)
                if key in seen:
                    continue
                seen.add(key)
                if flag not in valid_flags:
                    bad.append(f"{' '.join(parsed.path)} {flag} (in: {parsed.full})")

        assert not bad, "skill documents flags that do not exist on the target command:\n  " + "\n  ".join(bad)
