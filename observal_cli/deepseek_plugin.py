# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-License-Identifier: Apache-2.0

"""Install the Observal-owned Cordis plugin into DSH_HOME, without touching dsh."""

from __future__ import annotations

import hashlib
import json
import shutil
from importlib.resources import files
from pathlib import Path

from observal_cli.sessions.deepseek import resolve_dsh_home
from observal_cli.shared.utils import atomic_write


def plugin_path(home: Path | None = None) -> Path:
    """Path under an explicit DSH_HOME, or the current runtime DSH_HOME."""
    return (home if home is not None else resolve_dsh_home()) / "observal" / "collector.mjs"


def _manifest(home: Path | None = None) -> Path:
    return plugin_path(home).with_name(".collector.json")


def plugin_source() -> str:
    bundled = files("observal_cli").joinpath("_bundled/deepseek.mjs")
    if bundled.is_file():
        return bundled.read_text(encoding="utf-8")
    # Editable installs use the source tree; wheels include the force-included file.
    return (Path(__file__).resolve().parent.parent / "packages/deepseek-plugin/observal.mjs").read_text(
        encoding="utf-8"
    )


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _managed_hash(home: Path | None = None) -> str | None:
    if _manifest(home).is_symlink():
        return None
    try:
        data = json.loads(_manifest(home).read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("managed") is True and isinstance(data.get("sha256"), str):
            return data["sha256"]
    except (OSError, ValueError, TypeError):
        pass
    return None


def _back_up(path: Path) -> None:
    backup = path.with_name(path.name + ".bak")
    number = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.bak.{number}")
        number += 1
    shutil.copy2(path, backup)


def _drifted(path: Path, home: Path | None = None) -> bool:
    return path.is_file() and _sha256(path.read_text(encoding="utf-8")) != _managed_hash(home)


def status(home: Path | None = None) -> str:
    path = plugin_path(home)
    if path.parent.is_symlink() or not path.parent.resolve().is_relative_to(path.parent.parent.resolve()):
        return "unmanaged"
    if path.is_symlink() or _manifest(home).is_symlink():
        return "unmanaged"
    if not path.exists():
        return "missing" if not _manifest(home).exists() else "stale"
    if not path.is_file() or _managed_hash(home) is None:
        return "unmanaged"
    return "current" if path.read_text(encoding="utf-8") == plugin_source() else "stale"


def install(*, home: Path | None = None, dry_run: bool = False) -> bool:
    state = status(home)
    if state == "unmanaged":
        raise ValueError(f"Observal will not overwrite an unmanaged DeepSeek plugin: {plugin_path(home)}")
    if state == "current":
        return False
    if dry_run:
        return True
    path = plugin_path(home)
    if _drifted(path, home):
        _back_up(path)
    source = plugin_source()
    atomic_write(path, source)
    atomic_write(_manifest(home), json.dumps({"managed": True, "sha256": _sha256(source)}, indent=2) + "\n")
    return True


def remove(*, home: Path | None = None, dry_run: bool = False) -> bool:
    path = plugin_path(home)
    if status(home) == "unmanaged" or _managed_hash(home) is None:
        return False
    if not dry_run:
        if _drifted(path, home):
            _back_up(path)
        path.unlink(missing_ok=True)
        _manifest(home).unlink(missing_ok=True)
    return True
