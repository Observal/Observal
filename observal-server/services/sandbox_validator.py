# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Sandbox source validator.

Verifies that a Dockerfile exists at the declared source location
by issuing HTTP HEAD requests to forge raw-file URLs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx


@dataclass
class ValidatorResult:
    valid: bool
    message: str | None = None


_GITHUB_RE = re.compile(r"(?:https?://)?github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")
_GITLAB_RE = re.compile(r"(?:https?://)?gitlab\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")
_BITBUCKET_RE = re.compile(r"(?:https?://)?bitbucket\.org/([^/]+)/([^/]+?)(?:\.git)?/?$")


def _parse_forge(source_url: str) -> tuple[str, str, str] | None:
    """Parse source URL into (forge_type, owner, repo) or None."""
    m = _GITHUB_RE.match(source_url)
    if m:
        return ("github", m.group(1), m.group(2))
    m = _GITLAB_RE.match(source_url)
    if m:
        return ("gitlab", m.group(1), m.group(2))
    m = _BITBUCKET_RE.match(source_url)
    if m:
        return ("bitbucket", m.group(1), m.group(2))
    return None


def _build_raw_url(forge: str, owner: str, repo: str, ref: str, path: str) -> str:
    """Build the raw file URL for the given forge."""
    if forge == "github":
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
    if forge == "gitlab":
        return f"https://gitlab.com/{owner}/{repo}/-/raw/{ref}/{path}"
    if forge == "bitbucket":
        return f"https://bitbucket.org/{owner}/{repo}/raw/{ref}/{path}"
    raise ValueError(f"Unknown forge: {forge}")


async def validate_sandbox_source(
    source_url: str,
    sandbox_path: str | None = None,
    source_ref: str | None = None,
) -> ValidatorResult:
    """Verify that a Dockerfile exists at the declared source location.

    Strategy:
    1. Parse source_url to determine forge type (GitHub, GitLab, Bitbucket)
    2. Construct raw-file URL for the Dockerfile
    3. HTTP HEAD request (10s timeout)
    4. Interpret response
    """
    parsed = _parse_forge(source_url)
    if not parsed:
        return ValidatorResult(
            valid=False,
            message="Unsupported git forge. Only GitHub, GitLab, and Bitbucket URLs are supported for validation.",
        )

    forge, owner, repo = parsed
    ref = source_ref or "main"  # Note: defaults to 'main'; repos using 'master' must pass source_ref explicitly

    # Build path to Dockerfile
    if sandbox_path:
        # Normalize: strip trailing slashes
        sandbox_path = sandbox_path.rstrip("/")
        dockerfile_path = f"{sandbox_path}/Dockerfile"
    else:
        dockerfile_path = "Dockerfile"

    raw_url = _build_raw_url(forge, owner, repo, ref, dockerfile_path)

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, max_redirects=3) as client:
            resp = await client.head(raw_url)

        if resp.status_code == 200:
            return ValidatorResult(valid=True)
        elif resp.status_code == 404:
            return ValidatorResult(
                valid=False,
                message=f"Dockerfile not found at {dockerfile_path} in {source_url} (ref: {ref})",
            )
        elif resp.status_code in (401, 403):
            return ValidatorResult(
                valid=False,
                message="Repository not accessible (private repo or auth required)",
            )
        else:
            return ValidatorResult(
                valid=False,
                message=f"Unexpected response: HTTP {resp.status_code}",
            )
    except httpx.TimeoutException:
        return ValidatorResult(
            valid=False,
            message="Validation request timed out after 10s",
        )
    except httpx.HTTPError as e:
        return ValidatorResult(
            valid=False,
            message=f"Network error during validation: {e}",
        )
