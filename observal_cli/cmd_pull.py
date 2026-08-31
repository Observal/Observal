# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""observal pull: fetch agent config from the server and write harness files to disk."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from contextlib import nullcontext, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile

import typer
from loguru import logger as optic
from packaging.version import InvalidVersion, Version
from rich import print as rprint

from observal_cli import client, config
from observal_cli.constants import VALID_HARNESSES
from observal_cli.errors import ErrorCategory, fail
from observal_cli.harness import ensure_loaded, get_adapter
from observal_cli.prompts import password_input, select_one
from observal_cli.render import OutputMode, esc, output_json, spinner
from observal_shared.harness_registry import get_scope_aware_harnesses

# Hook script names used as placeholders in server-generated agent configs.
# Resolved to absolute paths client-side before writing to disk.
_HOOK_SCRIPT_NAMES = ("observal-hook.sh", "observal-stop-hook.sh")


def _component_conflicts(harness: str, agent_name: str, components: list[dict]) -> list[str]:
    """Return installed component version conflicts for the incoming agent."""
    from observal_cli.lockfile import read_registry_lockfile

    try:
        _, registry = read_registry_lockfile()
    except (OSError, RuntimeError) as error:
        fail(
            ErrorCategory.UNAVAILABLE,
            "Could not read the local installation lockfile.",
            operation="Pull agent",
            resource="Observal lockfile",
            remediation="Repair or remove the malformed lockfile, then retry.",
            detail=repr(error),
        )
    harness_section = registry.get("harnesses", {}).get(harness, {})
    other_agents = harness_section.get("agents", [])

    existing: dict[str, list[tuple[str, str]]] = {}
    for other in other_agents:
        if other.get("name") == agent_name:
            continue
        for component in other.get("components", []):
            component_name = component.get("name", "")
            component_version = component.get("version")
            if component_name and component_version:
                existing.setdefault(component_name, []).append((component_version, other.get("name", "?")))

    conflicts: list[str] = []
    for component in components:
        component_name = component.get("name", "")
        component_version = component.get("version")
        if not component_name or not component_version:
            continue
        for existing_version, existing_agent in existing.get(component_name, []):
            if existing_version != component_version:
                conflicts.append(
                    f"{component.get('type', 'component')} {component_name}: v{component_version} "
                    f"(this agent) vs v{existing_version} (from {existing_agent})"
                )
    return conflicts


def _resolve_hook_paths(content: str) -> str:
    """Replace hook script names with absolute paths in agent file content.

    Server-side config generator emits bare script names (observal-hook.sh)
    since it doesn't know the client's install path. This resolves them to
    the actual paths inside the installed package.

    Uses regex anchored to quoted command context so matches like
    ``"observal-hook.sh --agent-name foo"`` are resolved correctly,
    but comments or prose mentioning the script name are not affected.
    """
    import shutil

    hooks_dir = Path(__file__).parent / "hooks"
    for name in _HOOK_SCRIPT_NAMES:
        local = hooks_dir / name
        path = local.resolve().as_posix()
        if not local.is_file():
            # Fallback: check if it's on PATH
            found = shutil.which(name)
            if not found:
                continue
            path = Path(found).resolve().as_posix()
        # Match script name inside quotes with optional trailing args, replace only the script name
        pattern = rf'"{re.escape(name)}(?:\s+[^"]*)?'
        replacement = f'"{path}'
        content = re.sub(pattern, replacement, content)
    return content


def _collect_mcp_env_vars(
    agent_detail: dict, *, no_prompt: bool = False, env_overrides: dict[str, str] | None = None
) -> dict[str, dict[str, str]]:
    """Discover MCP env vars from agent components and prompt the user for values.

    When *no_prompt* is True, uses values from *env_overrides* for known vars
    and skips prompting entirely. Missing vars are omitted (server handles
    placeholders).

    Returns {mcp_listing_id: {VAR_NAME: value}} for all MCPs that have env vars.
    """
    env_values: dict[str, dict[str, str]] = {}
    _overrides = env_overrides or {}

    # Collect MCP component IDs from both mcp_links and component_links
    mcp_ids: list[tuple[str, str]] = []  # (listing_id, display_name)
    for link in agent_detail.get("mcp_links", []):
        mcp_ids.append((str(link["mcp_listing_id"]), link.get("mcp_name", "")))
    for link in agent_detail.get("component_links", []):
        if link.get("component_type") == "mcp":
            cid = str(link["component_id"])
            # Avoid duplicates if already in mcp_links
            if not any(mid == cid for mid, _ in mcp_ids):
                mcp_ids.append((cid, link.get("component_name", "")))

    if not mcp_ids:
        return env_values

    # Fetch each MCP listing to get its environment_variables
    for listing_id, display_name in mcp_ids:
        listing = client.get(f"/api/v1/mcps/{listing_id}")

        ev_list = listing.get("environment_variables") or []
        if not ev_list:
            continue

        required = [ev for ev in ev_list if ev.get("required", True)]
        optional = [ev for ev in ev_list if not ev.get("required", True)]
        mcp_name = display_name or listing.get("name", listing_id[:8])
        mcp_env: dict[str, str] = {}

        if no_prompt:
            # Non-interactive: use --env flag values for matching vars
            for ev in required + optional:
                if ev["name"] in _overrides:
                    mcp_env[ev["name"]] = _overrides[ev["name"]]
        else:
            if required:
                rprint(f"\n[bold]{esc(mcp_name)}[/bold] requires {len(required)} environment variable(s):")
                for ev in required:
                    if ev["name"] in _overrides:
                        mcp_env[ev["name"]] = _overrides[ev["name"]]
                        rprint(f"  [green]\u2713[/green] {esc(ev['name'])} [dim](from --env)[/dim]")
                    else:
                        desc = f" [dim]({esc(ev['description'])})[/dim]" if ev.get("description") else ""
                        val = password_input(f"  {esc(ev['name'])}{desc}")
                        mcp_env[ev["name"]] = val

            if optional:
                rprint(f"\n[dim]{esc(mcp_name)}: {len(optional)} optional env var(s):[/dim]")
                for ev in optional:
                    if ev["name"] in _overrides:
                        mcp_env[ev["name"]] = _overrides[ev["name"]]
                        rprint(f"  [green]\u2713[/green] {esc(ev['name'])} [dim](from --env)[/dim]")
                    else:
                        desc = f" [dim]({esc(ev['description'])})[/dim]" if ev.get("description") else ""
                        val = password_input(f"  {esc(ev['name'])}{desc} (press Enter to skip)")
                        if val:
                            mcp_env[ev["name"]] = val

        if mcp_env:
            env_values[listing_id] = mcp_env

    # Warn about MCPs that had env vars but user skipped all of them
    return env_values


def _collect_mcp_headers(
    agent_detail: dict, *, no_prompt: bool = False, header_overrides: dict[str, str] | None = None
) -> dict[str, dict[str, str]]:
    """Discover MCP headers from agent components and prompt the user for values.

    When *no_prompt* is True, uses values from *header_overrides* for known headers
    and skips prompting entirely. Missing headers are omitted.

    Returns {mcp_listing_id: {Header-Name: value}} for all MCPs that have headers.
    """
    header_values: dict[str, dict[str, str]] = {}
    _overrides = header_overrides or {}

    # Collect MCP component IDs from both mcp_links and component_links
    mcp_ids: list[tuple[str, str]] = []
    for link in agent_detail.get("mcp_links", []):
        mcp_ids.append((str(link["mcp_listing_id"]), link.get("mcp_name", "")))
    for link in agent_detail.get("component_links", []):
        if link.get("component_type") == "mcp":
            cid = str(link["component_id"])
            if not any(mid == cid for mid, _ in mcp_ids):
                mcp_ids.append((cid, link.get("component_name", "")))

    if not mcp_ids:
        return header_values

    for listing_id, display_name in mcp_ids:
        listing = client.get(f"/api/v1/mcps/{listing_id}")

        header_list = listing.get("headers") or []
        if not header_list:
            continue

        required = [h for h in header_list if h.get("required", True)]
        optional = [h for h in header_list if not h.get("required", True)]
        mcp_name = display_name or listing.get("name", listing_id[:8])
        mcp_hdrs: dict[str, str] = {}

        if no_prompt:
            for h in required + optional:
                if h["name"] in _overrides:
                    mcp_hdrs[h["name"]] = _overrides[h["name"]]
        else:
            if required:
                rprint(f"\n[bold]{esc(mcp_name)}[/bold] requires {len(required)} header(s):")
                for h in required:
                    if h["name"] in _overrides:
                        mcp_hdrs[h["name"]] = _overrides[h["name"]]
                        rprint(f"  [green]\u2713[/green] {esc(h['name'])} [dim](from --header)[/dim]")
                    else:
                        desc = f" [dim]({esc(h['description'])})[/dim]" if h.get("description") else ""
                        val = password_input(f"  {esc(h['name'])}{desc}")
                        mcp_hdrs[h["name"]] = val

            if optional:
                rprint(f"\n[dim]{esc(mcp_name)}: {len(optional)} optional header(s):[/dim]")
                for h in optional:
                    if h["name"] in _overrides:
                        mcp_hdrs[h["name"]] = _overrides[h["name"]]
                        rprint(f"  [green]\u2713[/green] {esc(h['name'])} [dim](from --header)[/dim]")
                    else:
                        desc = f" [dim]({esc(h['description'])})[/dim]" if h.get("description") else ""
                        val = password_input(f"  {esc(h['name'])}{desc} (press Enter to skip)")
                        if val:
                            mcp_hdrs[h["name"]] = val

        if mcp_hdrs:
            header_values[listing_id] = mcp_hdrs

    return header_values


def _dict_to_toml(d: dict) -> str:
    """Very basic TOML serializer for MCP configs."""
    lines = []
    for section, servers in d.items():
        for name, srv in servers.items():
            lines.append(f"[{section}.{name}]")
            for k, v in srv.items():
                if isinstance(v, list):
                    arr = ", ".join(json.dumps(s) for s in v)
                    lines.append(f"{k} = [{arr}]")
                elif isinstance(v, dict):
                    for subk, subv in v.items():
                        lines.append(f"{k}.{subk} = {json.dumps(subv)}")
                elif isinstance(v, bool):
                    lines.append(f"{k} = {'true' if v else 'false'}")
                elif isinstance(v, str):
                    lines.append(f"{k} = {json.dumps(v)}")
                else:
                    lines.append(f"{k} = {v}")
            lines.append("")
    return "\n".join(lines)


def _atomic_write_text(path: Path, content: str) -> None:
    temporary: Path | None = None
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
        temporary.replace(path)
    except (OSError, UnicodeError):
        if temporary:
            temporary.unlink(missing_ok=True)
        raise


def _merge_toml_text(existing_text: str, content: dict, root_key: str) -> str:
    parsed = tomllib.loads(existing_text)
    incoming = content.get(root_key, {})
    existing_section = parsed.get(root_key, {})
    if not isinstance(incoming, dict) or not isinstance(existing_section, dict):
        raise ValueError(f"TOML section {root_key} must be a mapping")

    lines = existing_text.splitlines(keepends=True)
    for name in set(incoming).intersection(existing_section):
        header = f"[{root_key}.{name}]"
        start = next((index for index, line in enumerate(lines) if line.strip() == header), None)
        if start is None:
            raise ValueError(f"cannot safely update existing TOML table {header}")
        end = start + 1
        while end < len(lines) and not lines[end].lstrip().startswith("["):
            end += 1
        del lines[start:end]

    existing = "".join(lines).rstrip()
    rendered = _dict_to_toml(content).rstrip()
    return f"{existing}\n\n{rendered}\n" if existing else f"{rendered}\n"


def _merge_yaml_config(path: Path, content: dict, root_key: str, *, existed: bool, merge: bool) -> str:
    """Write a YAML config, merging one section into the file already on disk.

    Goose keeps providers, global settings, and MCP extensions in a single
    ``config.yaml``, so an install must only touch its own section. An existing
    file that cannot be parsed is left untouched rather than overwritten.
    """
    import yaml

    existing: dict = {}
    if existed:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            raise
        except UnicodeError as error:
            raise ValueError(f"cannot merge unreadable YAML: {path}") from error
        try:
            loaded = yaml.safe_load(text) or {}
        except yaml.YAMLError as error:
            raise ValueError(f"cannot merge unreadable YAML: {path}") from error
        if not isinstance(loaded, dict):
            raise ValueError(f"cannot merge YAML whose top level is not a mapping: {path}")
        existing = loaded

    if merge and existed:
        section = existing.get(root_key)
        incoming = content.get(root_key, {})
        if section is not None and not isinstance(section, dict):
            raise ValueError(f"cannot merge non-mapping YAML section {root_key}: {path}")
        if not isinstance(incoming, dict):
            raise ValueError(f"incoming YAML section {root_key} is not a mapping")
        existing[root_key] = {**(section or {}), **incoming}
        payload = existing
    else:
        payload = {**existing, **content}
    _atomic_write_text(path, yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
    return "merged" if existed else "created"


def _write_file(path: Path, content: str | dict, *, merge_mcp: bool = False) -> str:
    """Write content to a file path, creating parent dirs as needed.

    If *merge_mcp* is True and the file already exists, merge the incoming
    dict into the existing one rather than overwriting.

    Returns a human-readable status string ("created", "updated", "merged").
    """
    optic.trace("path={}, len={}", path, len(str(content)))
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()

    if isinstance(content, dict):
        root_key = next(iter(content.keys())) if content else "mcpServers"
        if path.suffix == ".toml":
            toml_str = _dict_to_toml(content)
            if existed and merge_mcp:
                existing_text = path.read_text(encoding="utf-8")
                _atomic_write_text(path, _merge_toml_text(existing_text, content, root_key))
                return "merged"
            _atomic_write_text(path, toml_str)
        elif path.suffix in (".yaml", ".yml"):
            return _merge_yaml_config(path, content, root_key, existed=existed, merge=merge_mcp)
        else:
            if merge_mcp and existed:
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    raise
                except UnicodeError as error:
                    raise ValueError(f"cannot merge unreadable JSON: {path}") from error
                try:
                    existing = json.loads(text)
                except json.JSONDecodeError as error:
                    raise ValueError(f"cannot merge unreadable JSON: {path}") from error
                if not isinstance(existing, dict):
                    raise ValueError(f"cannot merge JSON whose top level is not an object: {path}")
                incoming_servers = content.get(root_key, {})
                section = existing.setdefault(root_key, {})
                if not isinstance(section, dict) or not isinstance(incoming_servers, dict):
                    raise ValueError(f"cannot merge non-object JSON section {root_key}: {path}")
                section.update(incoming_servers)
                _atomic_write_text(path, json.dumps(existing, indent=2) + "\n")
                return "merged"
            _atomic_write_text(path, json.dumps(content, indent=2) + "\n")
    else:
        _atomic_write_text(path, content)

    return "updated" if existed else "created"


def _write_file_checked(path: Path, content: str | dict, *, merge_mcp: bool = False) -> str:
    try:
        return _write_file(path, content, merge_mcp=merge_mcp)
    except ValueError as error:
        fail(
            ErrorCategory.CONFLICT,
            f"Could not safely merge existing configuration: {path}.",
            operation="Pull agent",
            resource=str(path),
            remediation="Fix or back up the existing configuration, then retry.",
            detail=repr(error),
        )
    except OSError as error:
        fail(
            ErrorCategory.UNAVAILABLE,
            f"Could not write generated configuration: {path}.",
            operation="Pull agent",
            resource=str(path),
            remediation="Check file permissions and available disk space.",
            detail=repr(error),
        )


def _rewrite_kiro_hooks(content: dict, agent_id: str | None = None) -> dict:
    """Rewrite Kiro hook commands to use the current Python interpreter.

    The server generates commands with bare 'python3' which won't find
    observal_cli when installed in a project-local virtual environment.
    """
    hooks = content.get("hooks") or {}

    from observal_cli.harness_specs.kiro_hooks_spec import build_kiro_hooks

    cfg = config.get_or_exit()
    hooks_url = f"{cfg['server_url'].rstrip('/')}/api/v1/telemetry/hooks"
    desired_hooks = build_kiro_hooks(hooks_url, agent_id=agent_id or "")

    # Replace only Observal hooks, preserve any user-added hooks
    for event, desired_entries in desired_hooks.items():
        existing = hooks.get(event, [])
        cleaned = [h for h in existing if "observal_cli" not in h.get("command", "")]
        hooks[event] = cleaned + desired_entries

    content["hooks"] = hooks
    return content


def _rewrite_copilot_cli_hooks(content: dict, agent_id: str | None = None) -> dict:
    """Rewrite Copilot CLI hook commands to inject per-agent attribution.

    The server emits a generic ``.github/hooks/observal.json`` whose commands
    carry no agent identity, so sessions fall back to best-effort cwd matching
    and go unattributed for user-scope installs or when the project moves.
    Rebuilding the Observal hooks with ``build_copilot_cli_hooks(agent_id=...)``
    prepends ``OBSERVAL_AGENT_ID`` (both bash and powershell forms), which the
    session push hook resolves to an exact agent+version via the lockfile.

    User-added hooks in the file are preserved; only Observal's entries are
    replaced. Mirrors _rewrite_kiro_hooks().
    """
    hooks = content.get("hooks")
    if not hooks:
        return content

    from observal_cli.harness_specs.copilot_cli_hooks_spec import build_copilot_cli_hooks

    desired_hooks = build_copilot_cli_hooks(agent_id=agent_id or "")["hooks"]

    # Replace only Observal hooks, preserve any user-added hooks
    for event, desired_entries in desired_hooks.items():
        existing = hooks.get(event, [])
        cleaned = [
            h
            for h in existing
            if "copilot_cli_session_push" not in h.get("bash", "")
            and "hooks.session_push --harness copilot-cli" not in h.get("bash", "")
        ]
        hooks[event] = cleaned + desired_entries

    content["hooks"] = hooks
    return content


def _resolve_path(raw_path: str, target_dir: Path, *, allow_home: bool = False) -> Path:
    """Resolve a path from the config snippet relative to *target_dir*.

    By default, ``~/`` prefixes are mapped under *target_dir* (not the real
    home directory) so that the pull command always writes inside the project.
    When *allow_home* is True (e.g. user explicitly chose --scope user), real
    ``$HOME`` expansion is allowed.

    Raises typer.Exit if the resolved path escapes *target_dir* (and home
    expansion is not permitted).
    """
    optic.trace("raw_path={}, target_dir={}", raw_path, target_dir)
    if raw_path.startswith("~/") or raw_path.startswith("~\\"):
        if allow_home:
            return Path(raw_path).expanduser().resolve()
        resolved = (target_dir / raw_path[2:]).resolve()
    else:
        resolved = (target_dir / raw_path).resolve()

    if not resolved.is_relative_to(target_dir):
        fail(
            ErrorCategory.VALIDATION,
            f"Generated path escapes the target directory: {raw_path}.",
            operation="Pull agent",
            resource=raw_path,
            remediation="Use a safe target directory or report the invalid server config.",
        )

    return resolved


# harnesses that support a project vs user install scope (derived from registry)
_SCOPE_AWARE_HARNESSES = get_scope_aware_harnesses()


def _progress(output: OutputMode | str, message: str | None = None):
    return nullcontext() if output == "json" else spinner(message)


def _parse_assignments(values: list[str] | None, label: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values or []:
        key, separator, value = item.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if not separator or not key or not value:
            fail(
                ErrorCategory.VALIDATION,
                f"Invalid {label} assignment.",
                operation="Pull agent",
                resource=label,
                remediation=f"Use {label}=VALUE with a non-empty name and value.",
            )
        parsed[key] = value
    return parsed


def _validate_pull_inputs(harness: str, scope: str | None, version: str | None) -> tuple[str, str | None, str | None]:
    harness = harness.strip().lower()
    if harness not in VALID_HARNESSES:
        fail(
            ErrorCategory.VALIDATION,
            f"Unknown harness: {harness}.",
            operation="Pull agent",
            resource="target harness",
            remediation=f"Choose from: {', '.join(VALID_HARNESSES)}.",
        )
    if scope is not None:
        scope = scope.strip().lower()
        if scope not in {"project", "user"}:
            fail(
                ErrorCategory.VALIDATION,
                f"Unknown install scope: {scope}.",
                operation="Pull agent",
                resource="install scope",
                remediation="Choose project or user.",
            )
        if harness not in _SCOPE_AWARE_HARNESSES:
            fail(
                ErrorCategory.VALIDATION,
                f"Harness {harness} does not support an explicit install scope.",
                operation="Pull agent",
                resource="install scope",
                remediation="Remove --scope for this harness.",
            )
    if version is not None:
        try:
            version = str(Version(version))
        except InvalidVersion:
            fail(
                ErrorCategory.VALIDATION,
                f"Invalid semantic version: {version}.",
                operation="Pull agent",
                resource="agent version",
                remediation="Use a semantic version such as 1.2.3.",
            )
    return harness, scope, version


def _parse_model_overrides(values: list[str]) -> tuple[str | None, dict[str, str]]:
    """Parse one or more ``--model`` flags.

    Two grammars are accepted:

    * ``--model <value>`` - applies to the harness selected for this pull.
    * ``--model <harness>=<value>`` - explicit per-harness override (advanced; lets
      a single command target a specific harness without ambiguity).

    Returns ``(default_value, per_harness_overrides)``.
    """
    optic.trace("values={}", values)
    default: str | None = None
    overrides: dict[str, str] = {}
    for raw in values or []:
        if "=" in raw:
            harness_key, _, val = raw.partition("=")
            harness_key = harness_key.strip().lower()
            val = val.strip()
            if harness_key not in VALID_HARNESSES or not val:
                fail(
                    ErrorCategory.VALIDATION,
                    f"Invalid model override: {raw}.",
                    operation="Pull agent",
                    resource="model override",
                    remediation="Use MODEL or HARNESS=MODEL with a registered harness.",
                )
            overrides[harness_key] = val
        elif raw.strip():
            default = raw.strip()
        else:
            fail(
                ErrorCategory.VALIDATION,
                "Model override cannot be empty.",
                operation="Pull agent",
                resource="model override",
                remediation="Provide a model ID or remove the empty --model option.",
            )
    return default, overrides


def _agent_saved_model(agent_detail: dict | None, harness: str) -> str | None:
    """Return the model the agent has saved for a harness, if any.

    Per-harness override wins; otherwise the legacy ``model_name`` is used as
    the implicit default for Claude Code only. Mirrors the server-side
    server resolver rules so the CLI never re-prompts when the author has
    already chosen a model.
    """
    ensure_loaded()
    return get_adapter(harness).saved_model(agent_detail)


def _collect_install_options(
    harness: str,
    *,
    scope: str | None,
    model_default: str | None,
    model_overrides: dict[str, str],
    tools: str | None,
    no_prompt: bool,
    refresh_models: bool = False,
    agent_detail: dict | None = None,
    quiet: bool = False,
) -> dict:
    """Interactively collect harness-specific install options.

    Honors explicit ``--scope``/``--model``/``--tools`` flags; only prompts for
    what's missing when running in an interactive terminal and ``--no-prompt``
    isn't set. The model picker consults the registry-backed harness model data.

    When the agent already has a saved model for the target harness (set in the
    builder) and the user didn't pass ``--model``, the saved value is used
    silently - the picker is skipped so authoring decisions aren't undone
    by a stray Enter at the prompt.
    """
    optic.trace("harness={}", harness)
    import sys

    from observal_cli.render import format_model as _format_model
    from observal_shared.harness_registry import get_default_scope, has_model_selection

    opts: dict = {}
    interactive = sys.stdin.isatty() and not no_prompt

    if harness in _SCOPE_AWARE_HARNESSES:
        default_scope = get_default_scope(harness)
        if scope:
            opts["scope"] = scope
        elif interactive:
            project_label, user_label = _SCOPE_AWARE_HARNESSES[harness]
            labels = {"project": project_label, "user": user_label}
            choice = select_one("  Scope", [user_label, project_label], default=labels.get(default_scope, user_label))
            opts["scope"] = "user" if choice.startswith("user") else "project"
        else:
            opts["scope"] = default_scope

    if has_model_selection(harness):
        explicit = model_overrides.get(harness) or model_default
        saved = _agent_saved_model(agent_detail, harness)
        if explicit:
            opts["model"] = explicit
        elif saved:
            try:
                primary, _secondary, _ = _format_model({"model_id": saved})
                pretty = primary or saved
            except (KeyError, TypeError, ValueError):
                pretty = saved
            if not quiet:
                rprint(f"  [dim]Model:[/dim] {esc(pretty)} [dim](from agent)[/dim]")
            # Pass through the saved value so the server records the same
            # choice on the install download record. The resolver still
            # validates the candidate against the harness registry and falls
            # back gracefully if needed.
            opts["model"] = saved
        elif interactive:
            from observal_cli import model_catalog as _catalog

            catalog = _catalog.fetch_catalog(refresh=refresh_models)
            choices = _catalog.model_choices_for_picker(catalog, harness)
            choice_labels = [c[0] for c in choices] if choices else []
            choice_labels = ["auto (let the harness decide)", *choice_labels]
            picked = select_one("  Model", choice_labels, default="auto (let the harness decide)")
            if picked.startswith("auto"):
                opts["model"] = ""
            else:
                for label, model_id in choices:
                    if label == picked:
                        opts["model"] = model_id
                        break

    ensure_loaded()
    get_adapter(harness).apply_install_options(opts, tools)
    return opts


def register_pull(app: typer.Typer):
    @app.command("pull")
    def pull(
        agent_id: str = typer.Argument(..., help="Agent ID, name, row number, or @alias"),
        harness: str = typer.Option(
            ...,
            "--harness",
            "-i",
            help="Target harness (cursor, kiro, claude-code, codex, copilot, copilot-cli, opencode, antigravity, pi)",
        ),
        directory: str = typer.Option(".", "--dir", "-d", help="Target directory for written files"),
        dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview files without writing"),
        scope: str | None = typer.Option(
            None, "--scope", help="Install scope: 'project' or 'user' for harnesses that support both"
        ),
        model: list[str] | None = typer.Option(
            None,
            "--model",
            help=(
                "Model override. Accepts '<value>' (applies to the selected --harness) or "
                "'<harness>=<value>' for explicit per-harness overrides. May be repeated."
            ),
        ),
        tools: str | None = typer.Option(None, "--tools", help="Comma-separated tool whitelist (Claude Code only)"),
        refresh_models: bool = typer.Option(
            False, "--refresh-models", help="Bust the local model catalog cache before showing the model picker"
        ),
        no_prompt: bool = typer.Option(False, "--no-prompt", "-y", help="Skip interactive prompts"),
        env: list[str] | None = typer.Option(
            None, "--env", "-e", help="Non-secret MCP environment setting (KEY=VALUE, repeatable)"
        ),
        header: list[str] | None = typer.Option(
            None, "--header", "-H", help="Non-secret MCP header setting (Header-Name=value, repeatable)"
        ),
        version: str | None = typer.Option(
            None, "--version", "-V", help="Install a specific version (e.g. '1.2.0'). Defaults to latest."
        ),
        output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
    ):
        """Fetch agent config and write harness files to disk.

        Calls the server to generate an install config for the specified harness,
        then writes rules files, MCP configs, and agent files into the target
        directory.  Use --dry-run to preview without writing.

        Use --env KEY=VALUE and --header Header-Name=value only for non-secret
        settings because command arguments are visible to other processes. For
        credentials, omit --no-prompt and enter values interactively. When
        --no-prompt is set, prompts are skipped and only flag values are used.

        Examples:
          observal agent pull my-agent --harness claude-code --no-prompt
          observal agent pull my-agent --harness claude-code --version 1.2.0
          observal agent pull my-agent --harness cursor --no-prompt --dry-run
        """
        if output == "json" and not no_prompt:
            fail(
                ErrorCategory.VALIDATION,
                "JSON mode cannot prompt for installation values.",
                operation="Pull agent",
                resource="agent installation",
                remediation="Add --no-prompt only when no secret values are required; otherwise use interactive table mode.",
            )
        harness, scope, version = _validate_pull_inputs(harness, scope, version)
        env_overrides = _parse_assignments(env, "environment variable")
        header_overrides = _parse_assignments(header, "header")
        model_default, model_overrides = _parse_model_overrides(model or [])
        unused_model_harnesses = set(model_overrides) - {harness}
        if unused_model_harnesses:
            fail(
                ErrorCategory.VALIDATION,
                f"Model override does not target the selected harness: {sorted(unused_model_harnesses)[0]}.",
                operation="Pull agent",
                resource="model override",
                remediation=f"Use {harness}=MODEL or a bare MODEL value.",
            )
        from observal_shared.harness_registry import has_model_selection

        if (model_default or model_overrides) and not has_model_selection(harness):
            fail(
                ErrorCategory.VALIDATION,
                f"Harness {harness} does not support model selection.",
                operation="Pull agent",
                resource="model override",
                remediation="Remove --model for this harness.",
            )
        if tools and harness != "claude-code":
            fail(
                ErrorCategory.VALIDATION,
                f"Harness {harness} does not support --tools.",
                operation="Pull agent",
                resource="tool allowlist",
                remediation="Remove --tools or select claude-code.",
            )
        if refresh_models and no_prompt:
            fail(
                ErrorCategory.VALIDATION,
                "--refresh-models requires the interactive model picker.",
                operation="Pull agent",
                resource="model catalog",
                remediation="Remove --no-prompt or remove --refresh-models.",
            )

        resolved = client.resolve_registry_reference("agent", agent_id)
        target_dir = Path(directory).resolve()
        ensure_loaded()
        adapter = get_adapter(harness)

        # Fetch agent details to discover MCP env vars
        with _progress(output, "Fetching agent details..."):
            agent_detail = client.get(f"/api/v1/agents/{resolved}")

        env_values = _collect_mcp_env_vars(agent_detail, no_prompt=no_prompt, env_overrides=env_overrides or None)
        header_values = _collect_mcp_headers(
            agent_detail, no_prompt=no_prompt, header_overrides=header_overrides or None
        )

        if output != "json":
            rprint(f"\n[bold]Install options for [cyan]{esc(harness)}[/cyan]:[/bold]")
        if refresh_models:
            from observal_cli import model_catalog as _catalog

            _catalog.invalidate_cache()
        options = _collect_install_options(
            harness,
            scope=scope,
            model_default=model_default,
            model_overrides=model_overrides,
            tools=tools,
            no_prompt=no_prompt,
            refresh_models=refresh_models,
            agent_detail=agent_detail,
            quiet=output == "json",
        )
        is_user_scope = options.get("scope") == "user"
        if is_user_scope and output != "json":
            rprint("  [dim]Files will be written to your home directory (user scope).[/dim]")

        from observal_cli.lockfile import local_registry_name

        namespace = agent_detail.get("namespace", "")
        slug = agent_detail.get("slug") or agent_detail.get("name", "agent")
        try:
            local_name = local_registry_name(
                harness,
                "agent",
                namespace,
                slug,
                scope=options.get("scope", "project"),
                directory=str(target_dir),
            )
        except (OSError, RuntimeError) as error:
            fail(
                ErrorCategory.UNAVAILABLE,
                "Could not read the local installation lockfile.",
                operation="Pull agent",
                resource="Observal lockfile",
                remediation="Repair or remove the malformed lockfile, then retry.",
                detail=repr(error),
            )
        options["local_name"] = local_name

        lock_components = [
            {
                "type": link.get("component_type", "unknown"),
                "name": link.get("component_name", ""),
                "id": str(link.get("component_id", "")),
                "version": link.get("version_ref"),
            }
            for link in agent_detail.get("component_links", [])
        ]
        conflict_warnings = _component_conflicts(
            harness,
            agent_name=agent_detail.get("name", resolved),
            components=lock_components,
        )

        with _progress(output, f"Pulling {harness} config for agent {resolved[:8]}..."):
            install_body: dict = {
                "harness": harness,
                "env_values": env_values,
                "header_values": header_values,
                "options": options,
                "platform": sys.platform,
            }
            if version:
                install_body["version"] = version
            result = client.post(
                f"/api/v1/agents/{resolved}/install",
                install_body,
            )

        snippet = result.get("config_snippet", {})
        if not snippet:
            fail(
                ErrorCategory.UNAVAILABLE,
                "The server returned an empty agent configuration.",
                operation="Pull agent",
                resource="generated agent configuration",
                remediation="Check server compatibility and the agent's harness support.",
            )

        written: list[tuple[str, str]] = []  # (path, status)

        # ── mcp_config with path key (Cursor/VSCode/Gemini) ─
        mcp_cfg = snippet.get("mcp_config")
        if mcp_cfg and isinstance(mcp_cfg, dict) and "path" in mcp_cfg:
            p = _resolve_path(mcp_cfg["path"], target_dir, allow_home=is_user_scope)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file_checked(p, mcp_cfg["content"], merge_mcp=True)
                written.append((str(p), status))

        # ── hooks_config (Cursor/VSCode/Copilot/OpenCode/Gemini) ─
        hooks_cfg = snippet.get("hooks_config")
        if hooks_cfg and isinstance(hooks_cfg, dict) and "path" in hooks_cfg:
            p = _resolve_path(hooks_cfg["path"], target_dir, allow_home=is_user_scope)
            content = hooks_cfg["content"]
            if isinstance(content, str):
                content = _resolve_hook_paths(content)
            elif isinstance(content, dict):
                # Resolve hook paths inside JSON content (command fields)
                raw = json.dumps(content)
                raw = _resolve_hook_paths(raw)
                import re

                raw = re.sub(
                    r"(?<!/)python3? -m observal_cli\.",
                    f"{sys.executable} -m observal_cli.",
                    raw,
                )
                content = json.loads(raw)
                content = adapter.rewrite_hooks(content, agent_id=str(agent_detail.get("id", resolved)))
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file_checked(p, content, merge_mcp=hooks_cfg.get("merge", False))
                written.append((str(p), status))

        # ── agent_profile (Kiro, Cursor) ────────────────────────
        agent_profile = snippet.get("agent_profile")
        if agent_profile:
            # Rewrite hook commands to use the current Python interpreter
            # so they work regardless of which directory Kiro is launched from.
            if isinstance(agent_profile.get("content"), dict):
                agent_profile["content"] = adapter.rewrite_agent_profile(
                    agent_profile["content"], agent_id=str(agent_detail.get("id", resolved))
                )
            elif isinstance(agent_profile.get("content"), str):
                agent_profile["content"] = _resolve_hook_paths(agent_profile["content"])
            agent_profile_allow_home = adapter.allow_home_agent_profile(is_user_scope)
            p = _resolve_path(agent_profile["path"], target_dir, allow_home=agent_profile_allow_home)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file_checked(p, agent_profile["content"])
                written.append((str(p), status))

        # ── steering_file (Kiro) ───────────────────────────
        steering_file = snippet.get("steering_file")
        if steering_file:
            p = _resolve_path(steering_file["path"], target_dir, allow_home=is_user_scope)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file_checked(p, steering_file["content"])
                written.append((str(p), status))

        # ── hook_files (script files from hook components) ─────
        hook_files = snippet.get("hook_files") or []
        for hf in hook_files:
            p = _resolve_path(hf["path"], target_dir, allow_home=is_user_scope)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                existed = p.exists()
                _write_file_checked(p, hf["content"])
                if hf.get("executable"):
                    import os

                    try:
                        os.chmod(p, 0o755)
                    except OSError as error:
                        fail(
                            ErrorCategory.UNAVAILABLE,
                            f"Could not mark generated hook executable: {p}.",
                            operation="Pull agent",
                            resource=str(p),
                            remediation="Check file ownership and permissions.",
                            detail=repr(error),
                        )
                written.append((str(p), "updated" if existed else "created"))

        # ── prompt_files (native Copilot .github/prompts/*.prompt.md) ─
        for pf in snippet.get("prompt_files") or []:
            p = _resolve_path(pf["path"], target_dir, allow_home=is_user_scope)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                existed = p.exists()
                _write_file_checked(p, pf["content"])
                written.append((str(p), "updated" if existed else "created"))

        # ── Direct skill files ─────────────────────────
        for sf in snippet.get("skills") or []:
            p = _resolve_path(sf["path"], target_dir, allow_home=is_user_scope)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file_checked(p, sf["content"])
                written.append((str(p), status))

        # ── Skills ────────────────────────────────────
        # Two install modes:
        #   1. git_url present → clone full skill directory from git
        #   2. skill_md_content present (registry_direct) → write SKILL.md + optional script
        from observal_cli.cmd_skill import _sanitize_name, install_skill_from_git, install_skill_registry_direct

        skill_components = snippet.get("skill_components") or []
        failed_skills: list[str] = []
        scope_str = "user" if is_user_scope else "project"
        for sc in skill_components:
            sc_name = _sanitize_name(sc.get("name", "skill"))
            git_url = sc.get("git_url")
            skill_dest = None
            if sc.get("path"):
                skill_dest = _resolve_path(sc["path"], target_dir, allow_home=is_user_scope).parent

            if dry_run:
                mode = "would clone" if git_url else "would write"
                written.append((str(skill_dest) if skill_dest else f"<skill:{sc_name}>", mode))
                continue

            if git_url:
                with redirect_stdout(StringIO()) if output == "json" else nullcontext():
                    result_path = install_skill_from_git(
                        name=sc.get("name", "skill"),
                        git_url=git_url,
                        skill_path=sc.get("skill_path", "/"),
                        git_ref=sc.get("git_ref", "main"),
                        harness=harness,
                        scope=scope_str,
                        skill_md_content=sc.get("skill_md_content"),
                        cwd=target_dir,
                        dest=skill_dest,
                    )
                if result_path:
                    written.append((str(result_path), "cloned"))
                else:
                    failed_skills.append(sc_name)
                    if output != "json":
                        rprint(
                            f"[red]\u2717 Failed to install skill '{esc(sc_name)}'.[/red] "
                            f"Clone from {esc(git_url)} failed."
                        )
            else:
                # Registry direct: SKILL.md content + optional script
                with redirect_stdout(StringIO()) if output == "json" else nullcontext():
                    result_path = install_skill_registry_direct(
                        name=sc.get("name", "skill"),
                        skill_md_content=sc.get("skill_md_content"),
                        script_content=sc.get("script_content"),
                        script_filename=sc.get("script_filename"),
                        harness=harness,
                        scope=scope_str,
                        cwd=target_dir,
                        dest=skill_dest,
                    )
                if result_path:
                    written.append((str(result_path), "installed"))
                else:
                    failed_skills.append(sc_name)
                    if output != "json":
                        rprint(f"[red]\u2717 Failed to install skill '{esc(sc_name)}'.[/red] No content available.")

        if failed_skills:
            fail(
                ErrorCategory.UNAVAILABLE,
                f"Failed to install {len(failed_skills)} agent skill(s).",
                operation="Pull agent",
                resource="agent skills",
                remediation="Check skill source access and content, then retry.",
                detail=", ".join(failed_skills),
            )

        if not written:
            fail(
                ErrorCategory.UNAVAILABLE,
                "The generated agent configuration contained no writable files.",
                operation="Pull agent",
                resource="generated agent configuration",
                remediation="Check agent contents and harness support, then retry.",
            )

        warnings_list = conflict_warnings + list(result.get("warnings") or []) + (snippet.get("_warnings") or [])

        # Run required harness registration before recording the pull as installed.
        setup_results: list[dict] = []
        setup_failures: list[str] = []
        setup_cmds = snippet.get("mcp_setup_commands") or []
        if setup_cmds and not dry_run:
            for command in setup_cmds:
                try:
                    process = subprocess.run(command, capture_output=True, text=True)
                except FileNotFoundError:
                    setup_results.append({"command": command, "status": "failed", "return_code": None})
                    setup_failures.append(f"{command[0]} not found")
                    continue
                status = "completed" if process.returncode == 0 else "failed"
                setup_results.append({"command": command, "status": status, "return_code": process.returncode})
                if process.returncode != 0:
                    setup_failures.append(f"{command[0]} exited with code {process.returncode}")
        elif setup_cmds:
            setup_results = [{"command": command, "status": "would_run", "return_code": None} for command in setup_cmds]

        if setup_failures:
            fail(
                ErrorCategory.UNAVAILABLE,
                f"Agent files were written, but {len(setup_failures)} MCP setup command(s) failed.",
                operation="Pull agent",
                resource="harness MCP registration",
                remediation="Fix the reported command and pull the agent again.",
                detail="; ".join(setup_failures),
            )

        # Record installation state only after files and setup commands succeed.
        if not dry_run:
            agent_uuid = agent_detail.get("id", resolved)
            agent_version = agent_detail.get("version") or agent_detail.get("latest_version")

            from observal_cli.lockfile import upsert_agent

            try:
                upsert_agent(
                    harness,
                    name=agent_detail.get("name", resolved),
                    agent_id=str(agent_uuid),
                    version=agent_version,
                    scope=options.get("scope", "project"),
                    directory=str(target_dir),
                    components=lock_components,
                    namespace=agent_detail.get("namespace"),
                    slug=agent_detail.get("slug"),
                    local_name=local_name,
                )
            except (OSError, RuntimeError) as error:
                fail(
                    ErrorCategory.UNAVAILABLE,
                    "Agent files were written, but installation tracking failed.",
                    operation="Pull agent",
                    resource="Observal lockfile",
                    remediation="Repair the local lockfile and pull the agent again.",
                    detail=repr(error),
                )

            try:
                from observal_cli.layer import ensure_local_snapshot

                ensure_local_snapshot(project_dir=str(target_dir))
            except (OSError, RuntimeError, ValueError):
                warnings_list.append("Local layer snapshot could not be refreshed; run `observal doctor`.")

            try:
                adapter.persist_active_agent(str(agent_uuid), agent_detail.get("name", resolved), agent_version)
            except (OSError, RuntimeError) as error:
                fail(
                    ErrorCategory.UNAVAILABLE,
                    "Agent files and lockfile were updated, but active-agent state could not be persisted.",
                    operation="Pull agent",
                    resource=f"{harness} active-agent state",
                    remediation="Fix harness configuration permissions and pull the agent again.",
                    detail=repr(error),
                )

            from observal_cli.audit import emit_cli_audit

            emit_cli_audit(
                "agent.pull",
                resource_type="agent",
                resource_id=str(agent_uuid),
                resource_name=agent_detail.get("name", resolved),
                detail=f"harness={harness}",
                sensitivity="high",
            )

        if output == "json":
            output_json(
                {
                    "agent": {
                        "id": str(agent_detail.get("id", resolved)),
                        "qualified_name": agent_detail.get("qualified_name")
                        or (f"{namespace}/{slug}" if namespace else slug),
                        "version": agent_detail.get("version") or agent_detail.get("latest_version"),
                        "local_name": local_name,
                    },
                    "harness": harness,
                    "scope": options.get("scope", "project"),
                    "dry_run": dry_run,
                    "target_directory": str(target_dir),
                    "files": [{"path": path, "status": status} for path, status in written],
                    "warnings": warnings_list,
                    "setup_commands": setup_results,
                }
            )
            return

        if dry_run:
            rprint("\n[bold yellow]Dry run[/bold yellow] - no files written:\n")
        else:
            rprint(
                f"\n[bold green]Pulled {esc(harness)} config[/bold green] "
                f"({len(written)} file{'s' if len(written) != 1 else ''}):\n"
            )
        for path, status in written:
            style = "dim" if dry_run else "green"
            rprint(f"  [{style}]{esc(status)}[/{style}]  {esc(path)}")
        if warnings_list:
            rprint("")
            for warning in warnings_list:
                rprint(f"  [yellow]⚠[/yellow]  {esc(warning)}")
        if setup_results:
            title = "Would run these setup commands:" if dry_run else "Registered MCP servers:"
            rprint(f"\n[bold]{title}[/bold]")
            for setup in setup_results:
                command_text = " ".join(map(str, setup["command"]))
                marker = "$" if dry_run else "✓"
                rprint(f"  [green]{marker}[/green] {esc(command_text)}")
