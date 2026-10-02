# SPDX-License-Identifier: Apache-2.0

"""Pi apply worker, launched only by the explicitly gated startup pilot.

A registry/account worker lock covers comparison through durable outcome
sealing. The 90-second budget limits *admission*, not the duration of a commit:
killing a process after it starts replacing files would defeat rollback.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import time
from typing import TYPE_CHECKING

from observal_cli import auto_update_install, auto_update_policy, client, installed_updates
from observal_cli import startup_update_check as check
from observal_cli.errors import CliError

if TYPE_CHECKING:
    from pathlib import Path

SHUTDOWN_DIR = check.config.CONFIG_DIR / "update-shutdown"
APPLY_SECONDS = 90
RECOVERY_RESERVE_SECONDS = 15


def expected_notice_key(registry: str, account: str, session_id: str) -> str:
    """Same UTF-8, NUL-separated identity used by the Pi extension."""
    return hashlib.sha256(f"{registry}\0{account}\0{session_id}".encode()).hexdigest()


def shutdown_marker(notice_key: str) -> Path:
    if len(notice_key) != 64 or any(ch not in "0123456789abcdef" for ch in notice_key):
        raise ValueError("Invalid startup notice key")
    return SHUTDOWN_DIR / f"{notice_key}.json"


def _reserve_pending(path: Path, payload: dict) -> None:
    """Create a durable, non-replaceable write-ahead record before any install.

    Linking a fully fsynced temp file avoids ever exposing a half-written
    record, and refuses to overwrite an unresolved record from an earlier run.
    """
    body = json.dumps(payload, ensure_ascii=False).encode()
    if len(body) > check.MAX_NOTICE_BYTES:
        raise ValueError("Pending update record exceeds the notice limit")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    directory = path.parent.lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_mode & 0o077 or not directory.st_mode & stat.S_IWUSR:
        raise OSError("Update notice directory is not private and writable")
    fd, temporary = tempfile.mkstemp(prefix=".update-pending-", dir=path.parent)
    linked = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)  # Atomic no-clobber reservation.
        linked = True
        check._sync_directory(path.parent)
    except BaseException:
        if linked:
            # A failed directory sync cannot certify this reservation or
            # completion seal. Best-effort remove the newly linked entry.
            try:
                path.unlink()
                check._sync_directory(path.parent)
            except OSError:
                pass
        raise
    finally:
        os.unlink(temporary)


def _unresolved_pending(registry: str, account: str) -> bool:
    """Do not accumulate uncertain installs for the same local identity."""
    for path in check.NOTICE_DIR.glob("*.pending"):
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > check.MAX_NOTICE_BYTES:
                return True
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or record.get("state") != "pending":
                return True
            if record.get("registry") == registry and record.get("account_id") == account:
                return True
        except (OSError, ValueError, UnicodeError):
            return True
    return False


def _pending_payload(registry: str, account: str, session_id: str, msg: dict, completed: list[dict]) -> dict:
    return {
        "schema": 1,
        "state": "pending",
        "registry": registry,
        "account_id": account,
        "session_id": session_id,
        "checked_at": int(time.time()),
        "item": {key: msg.get(key) for key in ("name", "current_version", "latest_version")},
        "completed": [{key: item.get(key) for key in ("name", "status")} for item in completed],
    }


def _ended(key: str) -> bool:
    """Unreadable marker storage is not permission to start a mutation."""
    marker = shutdown_marker(key)
    try:
        return marker.exists() or marker.is_symlink()
    except OSError:
        return True


def apply_pi(cwd: str, session_id: str, notice_key: str) -> None:
    """Bounded admission and durable result; the CLI caller must not kill this worker."""
    shutdown_marker(notice_key)  # Reject malformed keys before accessing local files.
    if not session_id or len(session_id) > 256:
        raise ValueError("Invalid session identifier")
    registry = auto_update_policy.active_registry()
    account = auto_update_policy.active_account()
    if notice_key != expected_notice_key(registry, account, session_id):
        raise ValueError("Startup notice key does not match the authenticated session")
    deadline = time.monotonic() + APPLY_SECONDS
    # Hold a separate cross-process gate until the final seal or failure. The
    # inner installer takes the registry gate; neither freeze nor manual pulls
    # ever wait for this outer worker gate while holding their own locks.
    with (
        auto_update_policy.apply_worker_gate(registry, account, timeout=max(0, deadline - time.monotonic())),
        client.bounded_requests(deadline - RECOVERY_RESERVE_SECONDS),
    ):
        _apply_pi_serialized(cwd, session_id, notice_key, registry=registry, account=account, deadline=deadline)


def _apply_pi_serialized(
    cwd: str, session_id: str, notice_key: str, *, registry: str, account: str, deadline: float
) -> None:
    marker = shutdown_marker(notice_key)
    pending_path = check.NOTICE_DIR / f"{notice_key}.pending"
    complete_path = check.NOTICE_DIR / f"{notice_key}.complete"
    journal_active = False
    unresolved_pending = False
    payload: dict = {
        "schema": 1,
        "registry": registry,
        "account_id": account,
        "session_id": session_id,
        "checked_at": int(time.time()),
        "items": [],
        "warning": None,
        "effective_in_current_session": "no",
    }
    try:
        # Never silently treat an inaccessible marker directory as a live session.
        marker.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory_stat = marker.parent.lstat()
        if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_mode & 0o077:
            raise OSError("Shutdown marker storage is unsafe")
        # An earlier attempt with this identity may have changed files but
        # failed to record its outcome. Do not overwrite its evidence or retry.
        unresolved_pending = _unresolved_pending(registry, account) or complete_path.exists()
        if unresolved_pending:
            payload["warning"] = "An earlier installation outcome is unresolved; inspect managed files before retrying."
        installed = installed_updates.inventory_for_context("pi", cwd)
        if installed:
            findings = check._cached_or_compare(registry, account, cwd, installed)
            policy = auto_update_policy.policy_status(registry)
            enabled = policy["effective"] and not policy.get("warning")
            if policy.get("warning"):
                payload["warning"] = "Auto-update policy is unreadable; automatic installs are disabled."
            for item in findings[: check.MAX_ITEMS]:
                msg = check._message(item, enabled=enabled)
                if msg is None:
                    continue
                if not enabled:
                    msg["reason"] = "Automatic updates are frozen or unavailable; run `observal unfreeze` to opt in."
                elif item.get("reason") is None:
                    msg["reason"] = "This item requires a manual update in the Pi pilot."
                if (
                    enabled
                    and item.get("type") == "agent"
                    and item.get("scope") == "user"
                    and item.get("release_verified")
                ):
                    current = [
                        entry
                        for entry in installed
                        if entry.get("id") == item.get("id")
                        and entry.get("type") == "agent"
                        and entry.get("scope") == "user"
                        and entry.get("directory") == item.get("directory")
                        and entry.get("current_version") == item.get("current_version")
                    ]
                    if len(current) != 1:
                        msg["status"] = "skipped"
                        msg["reason"] = "The installed agent changed or is ambiguous; update manually."
                    elif unresolved_pending:
                        msg["status"] = "skipped"
                        msg["reason"] = "An earlier update outcome is unresolved; inspect local managed files."
                    elif _ended(notice_key) or time.monotonic() + RECOVERY_RESERVE_SECONDS >= deadline:
                        msg["status"] = "skipped"
                        msg["reason"] = "Pi closed or the install admission window expired; update manually."
                    else:
                        # Persist this exact candidate and prior outcomes before
                        # allowing an installer to mutate any owned bytes.
                        pending = _pending_payload(registry, account, session_id, msg, payload["items"])
                        try:
                            if journal_active:
                                check._write_json(pending_path, pending, check.MAX_NOTICE_BYTES)
                            else:
                                _reserve_pending(pending_path, pending)
                                journal_active = True
                        except (OSError, ValueError):
                            # A failed directory sync can leave a visible but
                            # not yet durable reservation. Never claim it
                            # resolves an older pending outcome.
                            if not journal_active and (pending_path.exists() or pending_path.is_symlink()):
                                unresolved_pending = True
                            msg["status"] = "skipped"
                            msg["reason"] = "Cannot persist an update outcome; no installation was started."
                            payload["warning"] = (
                                "Update notice storage is unavailable; automatic installs are disabled."
                            )
                            payload["items"].append(msg)
                            break
                        try:
                            result = auto_update_install.apply_pi_agent(
                                {**current[0], "latest_version": item["latest_version"]},
                                registry=registry,
                                account=account,
                                deadline=deadline,
                                shutdown_requested=lambda: _ended(notice_key),
                            )
                            msg["status"] = "updated" if result.get("status") == "updated" else "failed"
                            msg["reason"] = (
                                "Saved Pi profile updated and verified; the current session and any copied active "
                                "profile are unchanged. Re-select the agent with `/agent` and reload to activate it."
                                if msg["status"] == "updated"
                                else "Installation could not be verified; inspect the local files."
                            )
                            msg["manual_command"] = None if msg["status"] == "updated" else msg["manual_command"]
                        except auto_update_install.InstallSkipError:
                            msg["status"] = "skipped"
                            msg["reason"] = (
                                "Automatic installation was unsafe or interrupted before commit; update manually."
                            )
                        except auto_update_install.InstallFailedError as error:
                            msg["status"] = "failed"
                            msg["reason"] = (
                                "Installation may be partial; inspect local recovery backups before re-pulling."
                                if error.partial
                                else "Installation failed; original files were restored."
                            )
                            if error.partial:
                                # Keep the spool bounded even for an agent with
                                # many owned skills. Every original backup stays
                                # in recovery_dir for manual inspection.
                                recovery = error.result.copy()
                                recovery["recovery_files"] = error.result["recovery_files"][:20]
                                recovery["recovery_files_omitted"] = len(error.result["recovery_files"]) - len(
                                    recovery["recovery_files"]
                                )
                                msg["recovery"] = recovery
                        except (CliError, OSError, ValueError, TypeError):
                            msg["status"] = "skipped"
                            msg["reason"] = "Automatic installation could not be verified; update manually."
                        except Exception:
                            # An unexpected installer error must never be reported
                            # as success, even if a separate repair is needed.
                            msg["status"] = "failed"
                            msg["reason"] = "Installation stopped unexpectedly; inspect local files before re-pulling."
                payload["items"].append(msg)
    except (CliError, OSError, ValueError, TypeError):
        payload["warning"] = "Update worker could not complete; inspect managed installs and run `observal outdated`."
    finally:
        # Even if a mutation succeeded before an unexpected exception, never
        # forge a success: the installed-state verifier is the only authority.
        # Only this worker's completed result can resolve its own journal.
        payload["outcome_final"] = not unresolved_pending
        payload["journaled"] = journal_active
        notice = check.NOTICE_DIR / f"{notice_key}.json"
        # Never replace a previous unresolved outcome for this same session.
        if journal_active or not (pending_path.exists() or complete_path.exists()):
            try:
                check._write_json(notice, payload, check.MAX_NOTICE_BYTES)
            except ValueError:
                # Do not lose the only recovery pointer to an oversized result.
                compact = {
                    **payload,
                    "warning": "Update details exceeded the notice limit; inspect local managed files.",
                }
                compact["items"] = []
                for item in payload["items"]:
                    reduced = {
                        key: item.get(key)
                        for key in ("name", "type", "scope", "status", "current_version", "latest_version", "reason")
                    }
                    if item.get("recovery", {}).get("partial"):
                        recovery = item["recovery"]
                        reduced["recovery"] = {
                            "partial": True,
                            "recovery_dir": recovery.get("recovery_dir"),
                            "recovery_files": recovery.get("recovery_files", [])[:1],
                            "recovery_files_omitted": recovery.get("recovery_files_omitted", 0)
                            + max(0, len(recovery.get("recovery_files", [])) - 1),
                        }
                    compact["items"].append(reduced)
                try:
                    check._write_json(notice, compact, check.MAX_NOTICE_BYTES)
                except ValueError:
                    # Last resort: retain the private backup directory even when
                    # target-to-backup references do not fit the spool quota.
                    minimal = {**payload, "warning": "Update result was too large; inspect local recovery backups."}
                    minimal["items"] = [
                        {
                            "status": item["status"],
                            "name": str(item.get("name") or "agent")[:100],
                            "reason": "Inspect the local recovery directory; installation state may be partial.",
                            "recovery": {
                                "partial": True,
                                "recovery_dir": item["recovery"]["recovery_dir"],
                                "recovery_files": [],
                                "recovery_files_omitted": 1,
                            },
                        }
                        for item in payload["items"]
                        if item.get("recovery", {}).get("partial")
                    ]
                    check._write_json(notice, minimal, check.MAX_NOTICE_BYTES)
            if journal_active:
                # A durable completion seal proves the final notice reached disk.
                # Without it, an os.replace followed by a failed directory fsync
                # must not let the Pi bridge erase the pending record.
                _reserve_pending(
                    complete_path,
                    {
                        "schema": 1,
                        "state": "complete",
                        "registry": registry,
                        "account_id": account,
                        "session_id": session_id,
                    },
                )
                pending_path.unlink(missing_ok=True)
                check._sync_directory(check.NOTICE_DIR)
            check._prune_directory(check.NOTICE_DIR, check.MAX_OUTSTANDING)
