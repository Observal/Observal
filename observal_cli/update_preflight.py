# SPDX-License-Identifier: Apache-2.0

"""Fail-closed eligibility checks for guarded Pi user-agent updates.

This module never installs; it is kept separate from the explicit `outdated`
contract, which lists older versions regardless of auto-update eligibility.
"""

from __future__ import annotations

from packaging.version import InvalidVersion, Version

from observal_cli import auto_update_policy, install_baseline


class PreflightSkipError(ValueError):
    """The update remains available for an explicit manual pull only."""


def _identities(components: object, *, installed: bool) -> set[tuple[str, str]]:
    if not isinstance(components, list):
        raise PreflightSkipError("Component identity evidence is missing; update manually.")
    identities: set[tuple[str, str]] = set()
    for component in components:
        if not isinstance(component, dict):
            raise PreflightSkipError("Component identity evidence is malformed; update manually.")
        kind = component.get("type" if installed else "component_type")
        component_id = component.get("id" if installed else "component_id")
        if not isinstance(kind, str) or not kind or not isinstance(component_id, str) or not component_id:
            raise PreflightSkipError("A component has no exact type and registry ID; update manually.")
        version = component.get("version" if installed else "resolved_version")
        try:
            if not isinstance(version, str) or version == "latest":
                raise InvalidVersion(str(version))
            Version(version)
        except InvalidVersion as error:
            raise PreflightSkipError("A component has no exact pinned version; update manually.") from error
        identity = (kind, component_id)
        if identity in identities:
            raise PreflightSkipError("The agent has ambiguous duplicate component identities; update manually.")
        identities.add(identity)
    return identities


def pi_user_agent_candidate(item: dict, *, registry: str) -> dict[str, str]:
    """Validate one verified comparison result without changing any files.

    The guarded installer repeats this under the policy/install gates,
    revalidates the target from the registry, then compares target file paths.
    A positive preflight result alone is NOT install authorization.
    """
    if item.get("type") != "agent" or item.get("harness") != "pi" or item.get("scope") != "user":
        raise PreflightSkipError("Only managed Pi user-scope agents are in the first automatic rollout.")
    if (
        item.get("status") != "outdated"
        or not item.get("outdated")
        or not item.get("release")
        or item.get("release_verified") is not True
    ):
        raise PreflightSkipError(item.get("reason") or "No verified approved update is available.")
    if not auto_update_policy.policy_status(registry)["effective"]:
        raise PreflightSkipError("Automatic updates are frozen; run `observal unfreeze` to opt in.")
    if item.get("lock_status") != "locked" or not item.get("lock_digest"):
        raise PreflightSkipError("The installed agent does not have a complete component lock; update manually.")
    current = item.get("current_version")
    if not isinstance(current, str) or not current:
        raise PreflightSkipError("The installed version is unknown; update manually.")
    installed = _identities(item.get("components"), installed=True)
    target = _identities(item["release"].get("components"), installed=False)
    if installed != target:
        raise PreflightSkipError("The release adds or removes components; review and pull it manually.")
    root = item.get("directory")
    if not isinstance(root, str) or not root:
        raise PreflightSkipError("The installation root is unknown; update manually.")
    try:
        files = install_baseline.verified_files(
            registry=registry,
            harness="pi",
            agent_id=item["id"],
            scope="user",
            root=root,
            version=current,
            lock_digest=item["lock_digest"],
        )
    except install_baseline.BaselineError as error:
        raise PreflightSkipError(str(error)) from error
    return {"current_version": current, "target_version": item["latest_version"], "verified_files": str(len(files))}
