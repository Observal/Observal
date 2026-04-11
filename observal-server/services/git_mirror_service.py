"""Git mirroring and component discovery service."""

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Mirror directory — use tempdir for tests, configurable for production
DEFAULT_MIRROR_BASE = Path(tempfile.gettempdir()) / "observal_mirrors"


@dataclass
class DiscoveredComponent:
    name: str
    path: str  # relative to repo root
    component_type: str  # mcp, skill, hook, prompt, sandbox
    description: str = ""


@dataclass
class SyncResult:
    success: bool
    components: list[DiscoveredComponent] = field(default_factory=list)
    commit_sha: str = ""
    error: str = ""


def _mirror_path(git_url: str, base: Path = DEFAULT_MIRROR_BASE) -> Path:
    """Content-addressed mirror directory."""
    url_hash = hashlib.sha256(git_url.encode()).hexdigest()[:16]
    return base / url_hash


def _run_git(args: list[str], cwd: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a git command with timeout."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def clone_or_update(git_url: str, branch: str = "main", base: Path = DEFAULT_MIRROR_BASE) -> Path:
    """Shallow clone or update a repo mirror. Returns the mirror directory path."""
    base.mkdir(parents=True, exist_ok=True)
    mirror_dir = _mirror_path(git_url, base)

    if mirror_dir.exists() and (mirror_dir / ".git").exists():
        # Update existing mirror
        result = _run_git(["fetch", "origin", branch, "--depth", "1"], cwd=str(mirror_dir))
        if result.returncode != 0:
            raise RuntimeError(f"git fetch failed: {result.stderr.strip()}")
        result = _run_git(["reset", "--hard", f"origin/{branch}"], cwd=str(mirror_dir))
        if result.returncode != 0:
            raise RuntimeError(f"git reset failed: {result.stderr.strip()}")
    else:
        # Fresh shallow clone
        if mirror_dir.exists():
            shutil.rmtree(mirror_dir)
        result = _run_git(
            [
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                branch,
                git_url,
                str(mirror_dir),
            ]
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr.strip()}")

    return mirror_dir


def get_commit_sha(mirror_dir: Path) -> str:
    """Get the current HEAD commit SHA."""
    result = _run_git(["rev-parse", "HEAD"], cwd=str(mirror_dir))
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def discover_components(mirror_dir: Path, component_type: str | None = None) -> list[DiscoveredComponent]:
    """Discover components using manifest (primary) or convention scan (fallback)."""
    # Try manifest first
    for manifest_name in (".observal.json", "observal.json"):
        manifest_path = mirror_dir / manifest_name
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
                return _parse_manifest(manifest, component_type, mirror_dir=mirror_dir)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Invalid manifest %s: %s", manifest_path, e)
                # Fall through to convention scan

    # Convention scan fallback
    return _scan_by_convention(mirror_dir, component_type)


def _safe_path(base: Path, rel: str) -> bool:
    """Check that a relative path stays within base (no traversal)."""
    try:
        resolved = (base / rel).resolve()
        return resolved == base.resolve() or str(resolved).startswith(str(base.resolve()) + "/")
    except (OSError, ValueError):
        return False


def _parse_manifest(
    manifest: dict, component_type: str | None = None, mirror_dir: Path | None = None
) -> list[DiscoveredComponent]:
    """Parse .observal.json manifest."""
    components = []
    type_keys = {
        "mcp": "mcps",
        "skill": "skills",
        "hook": "hooks",
        "prompt": "prompts",
        "sandbox": "sandboxes",
    }

    types_to_scan = (
        {component_type: type_keys[component_type]} if component_type and component_type in type_keys else type_keys
    )

    for ctype, key in types_to_scan.items():
        for entry in manifest.get(key, []):
            comp_path = entry.get("path", "")
            # Reject path traversal attempts
            if mirror_dir and not _safe_path(mirror_dir, comp_path):
                logger.warning("Skipping component with unsafe path: %s", comp_path)
                continue
            components.append(
                DiscoveredComponent(
                    name=entry.get("name", comp_path.split("/")[-1]),
                    path=comp_path,
                    component_type=ctype,
                    description=entry.get("description", ""),
                )
            )

    return components


# Convention directories per component type
_CONVENTION_DIRS = {
    "mcp": ["src", "mcps", "servers"],
    "skill": ["skills"],
    "hook": ["hooks"],
    "prompt": ["prompts"],
    "sandbox": ["sandboxes"],
}

# Markers that identify a valid component directory
_COMPONENT_MARKERS = {
    "mcp": lambda p: any(f for f in p.rglob("*.py") if ".git" not in f.parts),
    "skill": lambda p: (p / "SKILL.md").exists(),
    "hook": lambda p: (p / "hook.json").exists(),
    "prompt": lambda p: any(p.glob("*.md")) or any(p.glob("*.txt")),
    "sandbox": lambda p: (p / "Dockerfile").exists(),
}


def _scan_by_convention(mirror_dir: Path, component_type: str | None = None) -> list[DiscoveredComponent]:
    """Discover components by scanning conventional directories."""
    components = []
    types_to_scan = (
        {component_type: _CONVENTION_DIRS[component_type]}
        if component_type and component_type in _CONVENTION_DIRS
        else _CONVENTION_DIRS
    )

    for ctype, dirs in types_to_scan.items():
        marker = _COMPONENT_MARKERS.get(ctype, lambda p: True)
        for dir_name in dirs:
            base = mirror_dir / dir_name
            if not base.exists() or not base.is_dir():
                continue
            for item in sorted(base.iterdir()):
                if item.is_symlink() or not item.is_dir():
                    continue
                if not _safe_path(mirror_dir, str(item.relative_to(mirror_dir))):
                    continue
                if marker(item):
                    components.append(
                        DiscoveredComponent(
                            name=item.name,
                            path=str(item.relative_to(mirror_dir)),
                            component_type=ctype,
                        )
                    )

    return components


_FASTMCP_PATTERN = re.compile(r"FastMCP\(|from\s+mcp\.server\.fastmcp\s+import|from\s+fastmcp\s+import")


def validate_mcp_component(component_path: Path) -> tuple[bool, str]:
    """Validate an MCP component uses FastMCP. Returns (passed, detail)."""
    for py_file in component_path.rglob("*.py"):
        if ".git" in py_file.parts or py_file.is_symlink():
            continue
        try:
            content = py_file.read_text(errors="ignore")
            if _FASTMCP_PATTERN.search(content):
                return True, f"FastMCP found in {py_file.name}"
        except Exception:
            continue
    return False, "No FastMCP usage found. MCP servers must use FastMCP."


def sync_source(
    git_url: str, component_type: str, branch: str = "main", base: Path = DEFAULT_MIRROR_BASE
) -> SyncResult:
    """Full sync pipeline: clone -> discover -> validate. Returns SyncResult."""
    try:
        mirror_dir = clone_or_update(git_url, branch=branch, base=base)
        commit_sha = get_commit_sha(mirror_dir)
        components = discover_components(mirror_dir, component_type)

        # Validate MCP components
        valid_components = []
        for comp in components:
            if comp.component_type == "mcp":
                comp_path = mirror_dir / comp.path
                passed, detail = validate_mcp_component(comp_path)
                if not passed:
                    logger.warning("MCP validation failed for %s: %s", comp.name, detail)
                    continue  # Skip invalid MCPs
            valid_components.append(comp)

        return SyncResult(
            success=True,
            components=valid_components,
            commit_sha=commit_sha,
        )
    except Exception as e:
        logger.exception("Sync failed for %s", git_url)
        return SyncResult(success=False, error=str(e))
