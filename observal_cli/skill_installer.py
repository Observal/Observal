# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 EuanTop <euan@mail.bnu.edu.cn>
# SPDX-License-Identifier: Apache-2.0

"""Install and synchronize the bundled Observal skills."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from rich import print as rprint

if TYPE_CHECKING:
    from observal_cli.harness import BundledSkillPlan

_SKILL_DIRS = (
    "observal",
    "observal-agents",
    "observal-registry",
    "observal-ops",
    "observal-admin",
    "observal-advanced",
)
_SKILLS_BASE = Path(__file__).parent / "skills"


def _hash_value(digest: object, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _directory_hash(root: Path) -> str | None:
    """Return a deterministic SHA-256 hash for a complete directory tree."""
    if not root.is_dir() or root.is_symlink():
        return None

    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        _hash_value(digest, path.relative_to(root).as_posix().encode())
        if path.is_symlink():
            _hash_value(digest, b"link")
            _hash_value(digest, os.readlink(path).encode())
        elif path.is_dir():
            _hash_value(digest, b"directory")
        elif path.is_file():
            _hash_value(digest, b"file")
            _hash_value(digest, str(stat.S_IMODE(path.stat().st_mode)).encode())
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
        else:
            raise OSError(f"Unsupported file type in bundled skill: {path}")
    return digest.hexdigest()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _replace_directory(source: Path, target: Path) -> None:
    """Replace a managed directory as one rollback-safe filesystem operation."""
    target.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=f".{target.name}.sync-", dir=target.parent))
    staged = work_dir / "new"
    backup = work_dir / "old"
    had_target = target.exists() or target.is_symlink()

    try:
        shutil.copytree(source, staged)
        if had_target:
            target.rename(backup)
        try:
            staged.rename(target)
        except OSError:
            if had_target and backup.exists():
                backup.rename(target)
            raise
        _remove_path(backup)
    finally:
        _remove_path(work_dir)


def _sync_skill_directory(source_dir: Path, skill_file: Path) -> bool:
    """Hash-check one managed skill and replace its entire directory on drift."""
    if skill_file.name != "SKILL.md":
        raise OSError(f"Bundled skills require a directory ending in SKILL.md: {skill_file}")
    target_dir = skill_file.parent
    if _directory_hash(source_dir) == _directory_hash(target_dir):
        return False
    _replace_directory(source_dir, target_dir)
    return True


def _remove_antigravity_legacy_files(source_dir: Path, skill_file: Path) -> None:
    """Remove the former flat-file layout after Antigravity moves to skill directories."""
    skills_root = skill_file.parent.parent
    _remove_path(skills_root / f"{source_dir.name}.md")
    for source in source_dir.rglob("*"):
        if source.is_file() and source.name != "SKILL.md":
            _remove_path(skills_root / source.relative_to(source_dir))
    references = skills_root / "references"
    if references.is_dir() and not any(references.iterdir()):
        references.rmdir()


def _bundled_sources() -> dict[str, Path]:
    sources = {name: _SKILLS_BASE / name for name in _SKILL_DIRS}
    missing = [str(path / "SKILL.md") for path in sources.values() if not (path / "SKILL.md").is_file()]
    if missing:
        raise FileNotFoundError(f"Bundled Observal skills are incomplete: {', '.join(missing)}")
    return sources


def _skills_match(source_dir: Path, skill_file: Path) -> bool:
    try:
        source_hash = _directory_hash(source_dir)
        return source_hash is not None and source_hash == _directory_hash(skill_file.parent)
    except OSError:
        return False


def _is_unchanged_bundled_copy(source_dir: Path, skill_file: Path) -> bool:
    """Return whether an older, possibly partial bundle is safe to remove."""
    candidate_dir = skill_file.parent
    if not skill_file.is_file() or not candidate_dir.is_dir() or candidate_dir.is_symlink():
        return False
    try:
        for candidate in candidate_dir.rglob("*"):
            source = source_dir / candidate.relative_to(candidate_dir)
            if candidate.is_symlink():
                if not source.is_symlink() or os.readlink(candidate) != os.readlink(source):
                    return False
            elif candidate.is_dir():
                if not source.is_dir() or source.is_symlink():
                    return False
            elif candidate.is_file():
                if not source.is_file() or candidate.read_bytes() != source.read_bytes():
                    return False
            else:
                return False
    except OSError:
        return False
    return True


def _installation_plans(home: Path) -> dict[str, dict[str, BundledSkillPlan]]:
    """Return bundled skill plans for installed harnesses in registry order."""
    from observal_cli.harness import ensure_loaded, get_all_adapters
    from observal_shared.harness_registry import HARNESS_REGISTRY

    ensure_loaded()
    registered = get_all_adapters()
    adapters = {name: registered[name] for name in HARNESS_REGISTRY if name in registered}
    installed = frozenset(name for name, adapter in adapters.items() if adapter.is_installed(home))
    sources = _bundled_sources()
    plans: dict[str, dict[str, BundledSkillPlan]] = {}

    for harness_name, adapter in adapters.items():
        if harness_name not in installed:
            continue
        harness_plans: dict[str, BundledSkillPlan] = {}
        for skill_name, source_dir in sources.items():
            plan = adapter.plan_bundled_skill_install(skill_name, home, installed)
            if plan is None:
                continue
            reusable = next(
                (candidate for candidate in plan.reuse_candidates if _is_unchanged_bundled_copy(source_dir, candidate)),
                None,
            )
            harness_plans[skill_name] = replace(plan, target=reusable) if reusable else plan
        if harness_plans:
            plans[harness_name] = harness_plans
    return plans


def _should_sync(source_dir: Path, plan: BundledSkillPlan, install_missing: bool) -> bool:
    return (
        install_missing
        or plan.target.parent.exists()
        or plan.target.parent.is_symlink()
        or any(_is_unchanged_bundled_copy(source_dir, candidate) for candidate in plan.cleanup_candidates)
    )


def _reconcile_observal_skills(home: Path, *, install_missing: bool) -> tuple[list[str], list[str]]:
    """Synchronize planned destinations and safely remove obsolete duplicates."""
    sources = _bundled_sources()
    plans = _installation_plans(home)
    selected = {
        harness_name: harness_plans
        for harness_name, harness_plans in plans.items()
        if any(_should_sync(sources[name], plan, install_missing) for name, plan in harness_plans.items())
    }
    targets: dict[Path, Path] = {}
    cleanups: set[tuple[Path, Path, Path]] = set()
    warnings: list[str] = []

    for harness_plans in selected.values():
        for skill_name, plan in harness_plans.items():
            source_dir = sources[skill_name]
            targets[plan.target] = source_dir
            cleanups.update((candidate, source_dir, plan.target) for candidate in plan.cleanup_candidates)

    for target, source_dir in targets.items():
        _sync_skill_directory(source_dir, target)

    antigravity_plans = selected.get("antigravity", {})
    for skill_name, plan in antigravity_plans.items():
        _remove_antigravity_legacy_files(sources[skill_name], plan.target)

    for candidate, source_dir, target in sorted(cleanups, key=lambda item: str(item[0])):
        if candidate == target or not (candidate.parent.exists() or candidate.parent.is_symlink()):
            continue
        if not _skills_match(source_dir, target):
            warnings.append(f"Preserved {candidate}: replacement at {target} is unavailable or differs.")
            continue
        if not _is_unchanged_bundled_copy(source_dir, candidate):
            warnings.append(f"Preserved divergent bundled skill copy at {candidate}; review it manually.")
            continue
        _remove_path(candidate.parent)

    installed = [
        harness_name
        for harness_name, harness_plans in selected.items()
        if all(_skills_match(sources[name], plan.target) for name, plan in harness_plans.items())
    ]
    return installed, warnings


def missing_observal_skill_harnesses(home: Path | None = None) -> list[str]:
    """Return display names for installed harnesses missing the core bundled skill."""
    from observal_shared.harness_registry import HARNESS_REGISTRY

    return [
        HARNESS_REGISTRY[harness_name]["display_name"]
        for harness_name, plans in _installation_plans(home or Path.home()).items()
        if (core_plan := plans.get("observal")) is not None and not core_plan.target.is_file()
    ]


def sync_observal_skills(*, install_missing: bool = False) -> list[str]:
    """Synchronize installed skill bundles for every detected harness."""
    from observal_shared.harness_registry import HARNESS_REGISTRY

    installed, _warnings = _reconcile_observal_skills(Path.home(), install_missing=install_missing)
    return [HARNESS_REGISTRY[name]["display_name"] for name in installed]


def install_observal_skill() -> None:
    """Install current bundled skills to every detected harness."""
    import json as _json

    from observal_shared.harness_registry import HARNESS_REGISTRY

    installed, warnings = _reconcile_observal_skills(Path.home(), install_missing=True)

    # Kiro-specific: ensure the active agent has skill resources wired up.
    _kiro_skill_resource = "skill://~/.kiro/skills/*/SKILL.md"
    kiro_settings = Path.home() / ".kiro" / "settings" / "cli.json"
    if kiro_settings.exists():
        try:
            settings_data = _json.loads(kiro_settings.read_text())
            active_agent = settings_data.get("chat.defaultAgent", "")
            if active_agent:
                agent_profile = Path.home() / ".kiro" / "agents" / f"{active_agent}.json"
                if agent_profile.exists():
                    agent_data = _json.loads(agent_profile.read_text())
                    resources = agent_data.get("resources", [])
                    if _kiro_skill_resource not in resources:
                        resources.append(_kiro_skill_resource)
                        agent_data["resources"] = resources
                        agent_profile.write_text(_json.dumps(agent_data, indent=2) + "\n")
        except (OSError, _json.JSONDecodeError):
            pass

    if installed:
        display_names = [HARNESS_REGISTRY[name]["display_name"] for name in installed]
        rprint(f"\n[green]✓ Observal skills synchronized for:[/green] {', '.join(display_names)}")
        rprint('[dim]  LLMs can now use Observal commands directly (for example, "create a PR agent for kiro")[/dim]')
    for warning in warnings:
        rprint(f"[yellow]Warning:[/yellow] {warning}")
