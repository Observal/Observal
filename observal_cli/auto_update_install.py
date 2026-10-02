# SPDX-License-Identifier: Apache-2.0

"""Guarded Pi user-agent installer, enabled only in the opt-in Pi startup pilot.

Only plain profile files and registry-direct, script-free skills whose exact
paths were captured by a manual pull are supported. MCP merges, git clones,
setup commands, new files and active-profile switches remain notice-only.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.version import InvalidVersion, Version

from observal_cli import auto_update_policy as policy
from observal_cli import client, install_baseline, installed_updates, lockfile, update_preflight
from observal_cli.shared.utils import sanitize_name

if TYPE_CHECKING:
    from collections.abc import Callable

MAX_BYTES = 2 * 1024 * 1024


class InstallSkipError(ValueError):
    """Notice-only: nothing was changed."""


class InstallFailedError(RuntimeError):
    """A write failed; `partial` means manual repair is required."""

    def __init__(
        self,
        message: str,
        *,
        partial: bool,
        recovery_dir: Path | None = None,
        recovery_files: dict[Path, Path] | None = None,
    ) -> None:
        super().__init__(message)
        self.partial = partial
        # Local verified paths only: never include file contents, tokens, or
        # arbitrary registry-supplied paths in a recovery result.
        self.recovery_dir = str(recovery_dir) if partial and recovery_dir is not None else None
        self.result = {
            "partial": partial,
            "recovery_dir": self.recovery_dir,
            "recovery_files": [
                {"target": str(target), "backup": str(backup)} for target, backup in (recovery_files or {}).items()
            ]
            if partial
            else [],
        }


def _owned_digest(path: Path) -> str:
    """Recheck the exact target, including symlinked parents, at a write boundary."""
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
        raise install_baseline.BaselineError("The managed file is missing or crosses a symbolic link")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_path(raw: str, root: Path, directory: Path) -> Path:
    if not isinstance(raw, str) or not raw:
        raise InstallSkipError("The server returned an invalid Pi path.")
    if raw.startswith("~/"):
        candidate = Path.home() / raw[2:]
    elif raw.startswith("~"):
        raise InstallSkipError("The server returned an unsupported home path.")
    else:
        candidate = directory / raw
    if not candidate.is_absolute() or any(part.is_symlink() for part in (candidate, *candidate.parents)):
        raise InstallSkipError("A generated Pi path contains a symbolic link.")
    target = candidate.resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise InstallSkipError("The release changes the managed profile location or creates a file.")
    return target


def plan_pi_files(snippet: object, item: dict, old_files: dict[str, str]) -> dict[Path, bytes]:
    """Compute the complete *file* plan before any mutation.

    Do not call the manual pull writer: it merges files, invokes git/setup
    commands and can create paths before discovering a later conflict.
    """
    if not isinstance(snippet, dict) or set(snippet) - {"agent_profile", "skill_components"}:
        raise InstallSkipError("The Pi release requires an unsupported config merge or setup action.")
    local_name = item.get("local_name")
    if not isinstance(local_name, str) or local_name in {"", ".", ".."} or Path(local_name).name != local_name:
        raise InstallSkipError("The installed Pi profile name is unknown.")
    root = (Path.home() / ".pi" / "agent" / "agents" / local_name).resolve()
    if not root.is_dir() or root.is_symlink():
        raise InstallSkipError("The managed Pi profile is unavailable.")
    directory = Path(item["directory"]).resolve()
    if not directory.is_dir():
        raise InstallSkipError("The original pull directory no longer exists.")
    profile = snippet.get("agent_profile")
    if not isinstance(profile, dict) or not isinstance(profile.get("content"), str):
        raise InstallSkipError("The Pi release has no directly writable agent profile.")
    profile_path = _safe_path(profile.get("path"), root, directory)
    if profile_path != root / "AGENTS.md":
        raise InstallSkipError("The Pi release changes its agent profile path.")
    planned: dict[Path, bytes] = {profile_path: profile["content"].encode()}
    skills = snippet.get("skill_components", [])
    if not isinstance(skills, list):
        raise InstallSkipError("The release has invalid skill components.")
    for component in skills:
        if not isinstance(component, dict) or component.get("git_url") or component.get("script_content"):
            raise InstallSkipError("Git or executable skill installs require a manual pull.")
        content = component.get("skill_md_content")
        name = component.get("name")
        if not isinstance(content, str) or not content or not isinstance(name, str):
            raise InstallSkipError("The release requires an unsupported skill source.")
        target = _safe_path(component.get("path"), root, directory)
        if target != root / "skills" / sanitize_name(name) / "SKILL.md" or target in planned:
            raise InstallSkipError("The release changes or duplicates a managed skill path.")
        planned[target] = content.encode()
    if set(map(str, planned)) != set(old_files):
        raise InstallSkipError("The target file plan differs from the manual pull's ownership baseline.")
    if sum(path.stat().st_size + len(data) for path, data in planned.items()) > MAX_BYTES:
        raise InstallSkipError("The installation exceeds the bounded atomic-update size.")
    return planned


def _same_components(release: dict, lock: dict) -> None:
    expected = release.get("components")
    actual = lock.get("components")
    if not isinstance(expected, list) or not isinstance(actual, list) or len(expected) != len(actual):
        raise InstallSkipError("The server returned a different component lock.")
    pinned: dict[tuple[str, str], str] = {}
    for entry in expected:
        if not isinstance(entry, dict):
            raise InstallSkipError("The target component lock is malformed.")
        identity = (entry.get("component_type"), entry.get("component_id"))
        version = entry.get("resolved_version")
        if identity in pinned or not all(isinstance(key, str) and key for key in identity):
            raise InstallSkipError("The target component lock is incomplete.")
        try:
            if not isinstance(version, str) or version == "latest":
                raise InvalidVersion(str(version))
            Version(version)
        except InvalidVersion as error:
            raise InstallSkipError("The target component version is not pinned.") from error
        pinned[identity] = version
    found: dict[tuple[str, str], str] = {}
    for entry in actual:
        if not isinstance(entry, dict):
            raise InstallSkipError("The installed component lock is malformed.")
        identity = (entry.get("type"), entry.get("id"))
        if identity in found or not all(isinstance(key, str) and key for key in identity):
            raise InstallSkipError("The installed component lock is ambiguous.")
        found[identity] = entry.get("version")
    if pinned != found:
        raise InstallSkipError("The generated install lock does not match the approved release pins.")


def _stage(planned: dict[Path, bytes], profile_root: Path) -> tuple[dict[Path, Path], dict[Path, Path]]:
    """Keep temporary files outside tracked skill directories, on the same filesystem."""
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    stage_dir = Path(tempfile.mkdtemp(prefix=".observal-update-", dir=profile_root))
    try:
        for index, (target, content) in enumerate(planned.items()):
            mode = stat.S_IMODE(target.stat().st_mode)
            backup = stage_dir / f"{index}.before"
            next_file = stage_dir / f"{index}.next"
            backup.write_bytes(target.read_bytes())
            next_file.write_bytes(content)
            os.chmod(backup, mode)
            os.chmod(next_file, mode)
            backups[target] = backup
            staged[target] = next_file
        return staged, backups
    except BaseException:
        for entry in stage_dir.iterdir():
            entry.unlink()
        stage_dir.rmdir()
        raise


def _restore(
    entry: dict,
    registry: str,
    paths: list[str],
    old_files: dict[str, str],
    backups: dict[Path, Path],
    planned: dict[Path, bytes],
    *,
    metadata: bool,
) -> bool:
    """Restore only bytes we wrote; keep original backups until rollback verifies.

    An editor may have changed a committed target since replacement. Never
    replace those edits with the backup, even during recovery.
    """
    ok = True
    for target, backup in backups.items():
        try:
            current = _owned_digest(target)
            if current == old_files[str(target)]:
                continue
            if current != hashlib.sha256(planned[target]).hexdigest():
                ok = False
                continue
            restore_file = backup.with_suffix(".restore")
            shutil.copyfile(backup, restore_file)
            shutil.copymode(backup, restore_file)
            os.replace(restore_file, target)
        except (OSError, ValueError, install_baseline.BaselineError):
            ok = False
    if metadata:
        try:
            lockfile.upsert_agent(
                "pi",
                name=entry["name"],
                agent_id=entry["id"],
                version=entry["current_version"],
                scope="user",
                directory=entry["directory"],
                components=entry["components"],
                namespace=entry.get("namespace"),
                slug=entry.get("slug"),
                local_name=entry.get("local_name"),
                lock_digest=entry["lock_digest"],
                lock_status=entry["lock_status"],
                record_use=False,
            )
        except (OSError, RuntimeError, ValueError):
            ok = False
    if ok:
        try:
            if install_baseline._files(paths) != old_files:
                return False  # Never adopt an external edit made during rollback.
            install_baseline.capture(
                registry=registry,
                harness="pi",
                agent_id=entry["id"],
                scope="user",
                root=entry["directory"],
                version=entry["current_version"],
                lock_digest=entry["lock_digest"],
                written_paths=paths,
            )
            install_baseline.verified_files(
                registry=registry,
                harness="pi",
                agent_id=entry["id"],
                scope="user",
                root=entry["directory"],
                version=entry["current_version"],
                lock_digest=entry["lock_digest"],
            )
            saved = lockfile.installed_agent("pi", entry["id"], scope="user", directory=entry["directory"])
            if (
                not saved
                or saved.get("version") != entry["current_version"]
                or saved.get("lock_digest") != entry["lock_digest"]
            ):
                return False
        except (OSError, ValueError, RuntimeError):
            ok = False
    return ok


def apply_pi_agent(
    item: dict,
    *,
    registry: str,
    account: str,
    deadline: float,
    shutdown_requested: Callable[[], bool] = lambda: False,
) -> dict:
    """Install only an independently revalidated, previously owned Pi profile.

    `deadline` is a monotonic admission deadline, not permission to kill a
    process during commit. Pi shutdown is not synchronized with commit: a
    marker arriving just after the final check can still permit a verified
    install. Startup invokes it only under the explicit pilot gate.
    """
    if item.get("type") != "agent" or not isinstance(item.get("id"), str):
        raise InstallSkipError("Only tracked Pi agents can be updated automatically.")
    # Deliberately nested: compute the inner wait budget only *after* acquiring
    # the registry gate; freeze cannot overtake a committed installation.
    with policy.registry_gate(registry, timeout=max(0, min(2, deadline - time.monotonic()))):  # noqa: SIM117
        with policy.pi_install_lock(registry, timeout=max(0, min(2, deadline - time.monotonic()))):
            if shutdown_requested() or time.monotonic() + 15 >= deadline:
                raise InstallSkipError("The Pi session ended or the install admission window closed.")
            if policy.active_registry() != registry or policy.active_account() != account:
                raise InstallSkipError("The authenticated registry or account changed.")
            entries = installed_updates.inventory_for_context("pi", item.get("directory") or "")
            matching = [entry for entry in entries if entry["id"] == item["id"] and entry["scope"] == "user"]
            if len(matching) != 1:
                raise InstallSkipError("The managed installation is missing or ambiguous.")
            current = matching[0]
            if (
                current["current_version"] != item.get("current_version")
                or current["lock_digest"] != item.get("lock_digest")
                or current["directory"] != item.get("directory")
            ):
                raise InstallSkipError("The installed version or lock changed during the check.")
            verified = installed_updates.compare([current], verify_releases=True)[0]
            if verified.get("latest_version") != item.get("latest_version"):
                raise InstallSkipError("The approved target changed; check again before installing.")
            update_preflight.pi_user_agent_candidate(verified, registry=registry)
            baseline_path = install_baseline._path(registry, "pi", item["id"], "user", current["directory"])
            old_paths = json.loads(baseline_path.read_text(encoding="utf-8"))["paths"]
            old_files = install_baseline.verified_files(
                registry=registry,
                harness="pi",
                agent_id=item["id"],
                scope="user",
                root=current["directory"],
                version=current["current_version"],
                lock_digest=current["lock_digest"],
            )
            # Fetch the *exact* approved version, not latest-by-default; no
            # credentials, executable install options or project pins on argv.
            result = client.post_public(
                f"/api/v1/agents/{item['id']}/install",
                {
                    "harness": "pi",
                    "version": verified["latest_version"],
                    "strict": True,
                    "options": {"scope": "user", "local_name": current["local_name"]},
                    "platform": sys.platform,
                },
            )
            if (
                not isinstance(result, dict)
                or str(result.get("agent_id")) != item["id"]
                or result.get("harness") != "pi"
                or result.get("version") != verified["latest_version"]
                or result.get("warnings")
            ):
                raise InstallSkipError("The server did not generate the approved target version.")
            lock = result.get("lock")
            if (
                not isinstance(lock, dict)
                or lock.get("status") != "locked"
                or not isinstance(lock.get("digest"), str)
                or not lock["digest"]
                or lock.get("problems")
            ):
                raise InstallSkipError("The generated agent has no complete strict component lock.")
            _same_components(verified["release"], lock)
            planned = plan_pi_files(result.get("config_snippet"), current, old_files)
            if shutdown_requested() or time.monotonic() + 15 >= deadline:
                raise InstallSkipError("The Pi session ended or not enough time remains for safe recovery.")
            # Re-read consent and every owned byte as near to commit as possible.
            update_preflight.pi_user_agent_candidate(verified, registry=registry)
            if policy.active_account() != account or policy.active_registry() != registry:
                raise InstallSkipError("The authenticated identity changed before commit.")
            staged: dict[Path, Path] = {}
            backups: dict[Path, Path] = {}
            metadata_attempted = False
            committed: list[Path] = []
            keep_recovery = False
            paths = old_paths
            try:
                profile_root = next(iter(planned)).parent
                staged, backups = _stage(planned, profile_root)
                # Staging is outside captured paths; an external edit in the
                # meantime is still refused before the first replacement.
                install_baseline.verified_files(
                    registry=registry,
                    harness="pi",
                    agent_id=item["id"],
                    scope="user",
                    root=current["directory"],
                    version=current["current_version"],
                    lock_digest=current["lock_digest"],
                )
                # Best-effort last check, not an atomic boundary with Pi's
                # marker writer. Shutdown racing after this check may precede
                # the first replace; finish verification or restore old bytes.
                if shutdown_requested() or time.monotonic() + 15 >= deadline:
                    raise InstallSkipError("The Pi session ended or the recovery window closed before commit.")
                for target, prepared in staged.items():
                    # Check each target immediately before its replacement;
                    # the earlier whole-install check is not enough when an
                    # editor changes a later file during a multi-file commit.
                    if _owned_digest(target) != old_files[str(target)]:
                        raise install_baseline.BaselineError("A managed file changed before replacement")
                    # os.replace may commit even if a wrapper raises afterward.
                    committed.append(target)
                    os.replace(prepared, target)
                metadata_attempted = True
                lockfile.upsert_agent(
                    "pi",
                    name=current["name"],
                    agent_id=item["id"],
                    version=verified["latest_version"],
                    scope="user",
                    directory=current["directory"],
                    components=lock["components"],
                    namespace=current.get("namespace"),
                    slug=current.get("slug"),
                    local_name=current["local_name"],
                    lock_digest=lock["digest"],
                    lock_status="locked",
                    record_use=False,
                )
                install_baseline.capture(
                    registry=registry,
                    harness="pi",
                    agent_id=item["id"],
                    scope="user",
                    root=current["directory"],
                    version=verified["latest_version"],
                    lock_digest=lock["digest"],
                    written_paths=paths,
                )
                saved = lockfile.installed_agent("pi", item["id"], scope="user", directory=current["directory"])
                if (
                    not saved
                    or saved.get("version") != verified["latest_version"]
                    or saved.get("lock_digest") != lock["digest"]
                    or saved.get("components") != lock["components"]
                ):
                    raise InstallFailedError("The installed state could not be verified.", partial=True)
                install_baseline.verified_files(
                    registry=registry,
                    harness="pi",
                    agent_id=item["id"],
                    scope="user",
                    root=current["directory"],
                    version=verified["latest_version"],
                    lock_digest=lock["digest"],
                )
                if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in planned} != {
                    str(path): hashlib.sha256(data).hexdigest() for path, data in planned.items()
                }:
                    raise InstallFailedError("The installed files do not match the generated plan.", partial=True)
            except Exception as error:
                if not committed and not metadata_attempted:
                    raise InstallSkipError("The prepared install could not be committed safely.") from error
                stage_dir = next(iter(backups.values())).parent
                try:
                    recovered = _restore(
                        current,
                        registry,
                        paths,
                        old_files,
                        {target: backups[target] for target in committed},
                        planned,
                        metadata=metadata_attempted,
                    )
                except Exception:
                    recovered = False
                keep_recovery = not recovered
                raise InstallFailedError(
                    "The install failed; old files restored."
                    if recovered
                    else "The install failed and may be partial; inspect the local recovery backups before re-pulling.",
                    partial=not recovered,
                    recovery_dir=stage_dir if keep_recovery else None,
                    recovery_files=backups if keep_recovery else None,
                ) from error
            finally:
                if backups:
                    stage_dir = next(iter(backups.values())).parent
                    if keep_recovery:
                        # Retain every .before file, including ones from which
                        # restoration succeeded, so the user can inspect the
                        # complete original state. The directory is mode 0700.
                        try:
                            for entry in stage_dir.iterdir():
                                if entry.suffix in {".next", ".restore"}:
                                    entry.unlink(missing_ok=True)
                        except OSError:
                            # Never mask the partial-failure result or discard
                            # its recovery reference for optional temp cleanup.
                            pass
                    else:
                        for entry in stage_dir.iterdir():
                            entry.unlink(missing_ok=True)
                        stage_dir.rmdir()
            lockfile._record_capability_use(
                kind="agent",
                source="pull",
                harness="pi",
                component_id=item["id"],
                version=verified["latest_version"],
                directory=current["directory"],
                namespace=current.get("namespace"),
                slug=current.get("slug"),
            )
            return {
                "status": "updated",
                "id": item["id"],
                "current_version": current["current_version"],
                "target_version": verified["latest_version"],
                "description": verified["release"].get("description"),
                "effective_in_current_session": "no",
                "reload_required": True,
            }
