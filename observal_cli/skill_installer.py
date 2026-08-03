# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 EuanTop <euan@mail.bnu.edu.cn>
# SPDX-License-Identifier: Apache-2.0

"""Install bundled Observal skills through harness adapters."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from rich import print as rprint

if TYPE_CHECKING:
    from observal_cli.harness import BundledSkillPlan

BUNDLED_SKILL_NAMES = (
    "observal",
    "observal-agents",
    "observal-registry",
    "observal-ops",
    "observal-admin",
    "observal-advanced",
)


@dataclass(frozen=True)
class BundledSkillInstallationPlan:
    """Frozen harness detection and destinations for one installation run."""

    home: Path
    harness_plans: dict[str, dict[str, BundledSkillPlan]] = field(default_factory=dict)


@dataclass(frozen=True)
class BundledSkillInstallResult:
    """Observable result of reconciling the bundled skill family."""

    installed_harnesses: tuple[str, ...] = ()
    changed_paths: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()


def _skills_base() -> Path:
    return Path(__file__).parent / "skills"


def _skill_sources() -> dict[str, Path]:
    base = _skills_base()
    return {
        skill_name: source for skill_name in BUNDLED_SKILL_NAMES if (source := base / skill_name / "SKILL.md").is_file()
    }


def _files_match(first: Path, second: Path) -> bool:
    try:
        return first.is_file() and second.is_file() and first.read_bytes() == second.read_bytes()
    except OSError:
        return False


def plan_observal_skill_installation(home: Path | None = None) -> BundledSkillInstallationPlan:
    """Freeze installed harnesses and ask each adapter where bundled skills belong."""
    from observal_cli.harness import ensure_loaded, get_all_adapters

    home = home or Path.home()
    sources = _skill_sources()
    if "observal" not in sources:
        return BundledSkillInstallationPlan(home=home)

    ensure_loaded()
    adapters = get_all_adapters()
    installed_harnesses = frozenset(
        harness_name for harness_name, adapter in adapters.items() if adapter.is_installed(home)
    )
    harness_plans: dict[str, dict[str, BundledSkillPlan]] = {}

    for harness_name, adapter in adapters.items():
        if harness_name not in installed_harnesses:
            continue
        skill_plans: dict[str, BundledSkillPlan] = {}
        for skill_name, source in sources.items():
            plan = adapter.plan_bundled_skill_install(
                skill_name,
                home,
                installed_harnesses,
            )
            if plan is not None:
                reusable_target = next(
                    (candidate for candidate in plan.reuse_candidates if _files_match(source, candidate)),
                    None,
                )
                if reusable_target is not None:
                    plan = replace(plan, target=reusable_target)
                skill_plans[skill_name] = plan
        if skill_plans:
            harness_plans[harness_name] = skill_plans

    return BundledSkillInstallationPlan(home=home, harness_plans=harness_plans)


def missing_observal_skill_harnesses(home: Path | None = None) -> list[str]:
    """Return display names for installed harnesses missing the core bundled skill."""
    from observal_shared.harness_registry import HARNESS_REGISTRY

    plan = plan_observal_skill_installation(home)
    missing: list[str] = []
    for harness_name, skill_plans in plan.harness_plans.items():
        core_plan = skill_plans.get("observal")
        if core_plan is not None and not core_plan.target.is_file():
            missing.append(HARNESS_REGISTRY[harness_name]["display_name"])
    return missing


def install_observal_skill(home: Path | None = None) -> BundledSkillInstallResult:
    """Reconcile the bundled Observal skill family for all installed harnesses."""
    from observal_cli.harness import get_adapter
    from observal_shared.harness_registry import HARNESS_REGISTRY

    installation_plan = plan_observal_skill_installation(home)
    sources = _skill_sources()
    targets: dict[Path, Path] = {}
    cleanups: set[tuple[Path, Path, Path]] = set()

    for skill_plans in installation_plan.harness_plans.values():
        for skill_name, skill_plan in skill_plans.items():
            source = sources[skill_name]
            targets[skill_plan.target] = source
            cleanups.update((candidate, source, skill_plan.target) for candidate in skill_plan.cleanup_candidates)

    changed_paths: list[Path] = []
    warnings: list[str] = []
    for target, source in targets.items():
        try:
            content = source.read_bytes()
            if target.is_file() and target.read_bytes() == content:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            changed_paths.append(target)
        except OSError as exc:
            warnings.append(f"Could not install bundled skill at {target}: {exc}")

    for candidate, source, target in sorted(cleanups, key=lambda item: str(item[0])):
        if candidate == target or not candidate.exists():
            continue
        if not _files_match(source, target):
            warnings.append(
                f"Preserved {candidate} because replacement at {target} is unavailable or differs from the bundled skill."
            )
            continue
        try:
            if candidate.read_bytes() != source.read_bytes():
                warnings.append(f"Preserved divergent bundled skill copy at {candidate}; review it manually.")
                continue
            candidate.unlink()
            changed_paths.append(candidate)
        except OSError as exc:
            warnings.append(f"Could not inspect or remove stale bundled skill copy at {candidate}: {exc}")

    for harness_name in installation_plan.harness_plans:
        warnings.extend(get_adapter(harness_name).reconcile_bundled_skill_configuration(installation_plan.home))

    installed_harnesses = tuple(
        harness_name
        for harness_name, skill_plans in installation_plan.harness_plans.items()
        if all(_files_match(sources[skill_name], skill_plan.target) for skill_name, skill_plan in skill_plans.items())
    )
    if installed_harnesses:
        display_names = [HARNESS_REGISTRY[name]["display_name"] for name in installed_harnesses]
        rprint(f"\n[green]✓ Observal skill installed for:[/green] {', '.join(display_names)}")
        rprint('[dim]  LLMs can now use Observal commands directly (e.g. "create a PR agent for kiro")[/dim]')

    for warning in warnings:
        rprint(f"[yellow]Warning:[/yellow] {warning}")

    return BundledSkillInstallResult(
        installed_harnesses=installed_harnesses,
        changed_paths=tuple(changed_paths),
        warnings=tuple(warnings),
    )
