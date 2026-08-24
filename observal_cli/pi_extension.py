# SPDX-FileCopyrightText: 2026 amogh-dongre <amoghdongre16@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Install/version-check logic for the bundled Pi telemetry extension.

Two installation modes coexist:
  - npm: the user has `npm:observal-pi[@version]` configured in
    ~/.pi/agent/settings.json. Observal never writes to this path; it only
    reports when a pinned version is older than the installed CLI.
  - local: Observal writes the canonical extension straight to
    ~/.pi/agent/extensions/observal.ts, tracked by an adjacent
    .observal-extension.json manifest recording the CLI version it was
    installed from. A file at that path with no matching manifest is
    treated as unmanaged and never overwritten.

npm takes priority: if it's configured (even if not yet downloaded by Pi),
the local path is left untouched entirely.

Shared by `observal doctor` (interactive check/patch/cleanup) and the
automatic post-login install in cmd_auth.py.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from packaging.version import InvalidVersion, Version

from observal_cli.shared.utils import load_jsonc
from observal_cli.version_check import get_current_version

_NPM_SOURCE = "npm:observal-pi"

NOT_DETECTED = "not_detected"
NOT_INSTALLED = "not_installed"
CURRENT = "current"
STALE = "stale"
NEWER = "newer"
UNMANAGED = "unmanaged"
NPM_CURRENT = "npm_current"
NPM_STALE = "npm_stale"
NPM_UNPINNED = "npm_unpinned"


@dataclass(frozen=True)
class PiExtensionStatus:
    state: str
    message: str | None = None
    action: str | None = None  # None | "install" | "refresh" | "adopt"


def pi_agent_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".pi" / "agent"


def extension_path(home: Path | None = None) -> Path:
    return pi_agent_dir(home) / "extensions" / "observal.ts"


def manifest_path(home: Path | None = None) -> Path:
    return pi_agent_dir(home) / "extensions" / ".observal-extension.json"


def settings_path(home: Path | None = None) -> Path:
    return pi_agent_dir(home) / "settings.json"


def extension_source() -> str:
    """Read the canonical extension source: bundled wheel copy, or dev source tree."""
    bundled = Path(__file__).parent / "_bundled" / "observal.ts"
    source_tree = Path(__file__).parents[1] / "packages" / "pi-extension" / "extensions" / "observal.ts"
    for path in (bundled, source_tree):
        if path.exists():
            return path.read_text()
    raise FileNotFoundError("Bundled Pi telemetry extension is missing")


def _atomic_write(path: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing_mode = path.stat().st_mode if path.exists() else None
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        temporary.replace(path)
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _npm_entry(settings: dict) -> str | None:
    for package in settings.get("packages", []):
        if isinstance(package, str):
            source = package
        elif isinstance(package, dict):
            source = package.get("source", "")
        else:
            continue
        if source == _NPM_SOURCE or source.startswith(f"{_NPM_SOURCE}@"):
            return source
    return None


def is_npm_configured(pi_dir: Path) -> bool:
    """Whether npm:observal-pi is registered in this Pi agent dir's settings.json.

    Swallows unreadable/invalid settings rather than raising: used by hook
    detection, where a best-effort boolean is all that's needed.
    """
    settings_file = pi_dir / "settings.json"
    if not settings_file.exists():
        return False
    try:
        settings = load_jsonc(settings_file)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return isinstance(settings, dict) and _npm_entry(settings) is not None


def _npm_pinned_version(source: str) -> str | None:
    _, _, version = source.partition(f"{_NPM_SOURCE}@")
    return version or None


def _parse_version(value: str) -> Version | None:
    try:
        return Version(value)
    except InvalidVersion:
        return None


def _read_manifest(home: Path | None = None) -> dict | None:
    path = manifest_path(home)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def check_status(home: Path | None = None) -> PiExtensionStatus:
    """Determine the current install state.

    Raises OSError/ValueError if settings.json or the installed extension
    file exist but can't be read/parsed — callers decide how to surface that.
    """
    pi_dir = pi_agent_dir(home)
    if not pi_dir.exists():
        return PiExtensionStatus(NOT_DETECTED)

    settings_file = settings_path(home)
    settings: dict = {}
    if settings_file.exists():
        settings = load_jsonc(settings_file)
        if not isinstance(settings, dict):
            raise ValueError(f"{settings_file}: must contain a JSON object")

    npm_source = _npm_entry(settings)
    if npm_source is not None:
        pinned = _npm_pinned_version(npm_source)
        pinned_version = _parse_version(pinned) if pinned else None
        current_version = _parse_version(get_current_version())
        if pinned_version is not None and current_version is not None and pinned_version < current_version:
            return PiExtensionStatus(
                NPM_STALE,
                f"Configured {npm_source} is older than the installed Observal CLI "
                f"({get_current_version()}). Run `pi update npm:observal-pi` to refresh the extension.",
            )
        return PiExtensionStatus(NPM_CURRENT if pinned_version is not None else NPM_UNPINNED)

    # Read the bundled source eagerly (not just when we're about to install)
    # so a broken/missing package bundle is surfaced by `doctor check`, not
    # only discovered later when a patch/install is actually attempted.
    expected = extension_source()

    path = extension_path(home)
    if not path.exists():
        return PiExtensionStatus(
            NOT_INSTALLED,
            f"Observal Pi extension is not installed. Doctor can install {path}.",
            action="install",
        )

    try:
        installed = path.read_text()
    except OSError as exc:
        raise OSError(f"{path}: {exc}") from exc

    manifest = _read_manifest(home)
    if manifest is not None and manifest.get("managed") is True and isinstance(manifest.get("version"), str):
        manifest_version = _parse_version(manifest["version"])
        current_version = _parse_version(get_current_version())
        if manifest_version is not None and current_version is not None:
            if manifest_version < current_version:
                return PiExtensionStatus(
                    STALE,
                    f"Observal Pi extension is stale ({manifest['version']} < {get_current_version()}). "
                    f"Doctor can refresh {path}.",
                    action="refresh",
                )
            if manifest_version > current_version:
                return PiExtensionStatus(NEWER)
            return PiExtensionStatus(CURRENT)

    # No trustworthy manifest. Adopt silently if the content already matches
    # what we'd install (covers pre-manifest installs from before this
    # feature existed); otherwise this is a foreign file we must not touch.
    if installed == expected:
        return PiExtensionStatus(CURRENT, action="adopt")
    return PiExtensionStatus(
        UNMANAGED,
        f"{path} exists but is not managed by Observal. Remove it (or move it aside) and "
        "re-run `observal doctor patch --harness pi` to let Observal manage the Pi extension, "
        "or leave it as-is to keep using it unmanaged.",
    )


def install_or_refresh(*, dry_run: bool, home: Path | None = None) -> tuple[bool, str | None]:
    """Perform the recommended action, if any.

    Returns (changed, action) where action is "install" | "refresh" | "adopt",
    matching PiExtensionStatus.action, or (False, None) if nothing to do.
    """
    status = check_status(home)
    if status.action is None:
        return False, None
    if dry_run:
        return True, status.action
    if status.action != "adopt":
        _atomic_write(extension_path(home), extension_source())
    _atomic_write(
        manifest_path(home),
        json.dumps({"managed": True, "version": get_current_version()}, indent=2) + "\n",
    )
    return True, status.action


def remove(*, dry_run: bool, home: Path | None = None) -> bool:
    """Remove an Observal-managed local install. Never touches npm config or unmanaged files."""
    status = check_status(home)
    if status.state not in (CURRENT, STALE, NEWER):
        return False
    if not dry_run:
        extension_path(home).unlink(missing_ok=True)
        manifest_path(home).unlink(missing_ok=True)
    return True
