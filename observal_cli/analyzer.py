# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Local repository analysis for MCP server submissions.

Clones the repo using the system git (which inherits the user's credential
helpers, SSO sessions, SSH keys, etc.) and runs the same analysis that the
server performs: MCP pattern detection, AST parsing, env-var scanning.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

_CLONE_TIMEOUT = 120  # seconds

# ---------------------------------------------------------------------------
# Patterns (mirrored from observal-server/services/mcp_validator.py)
# ---------------------------------------------------------------------------

_PYTHON_MCP_PATTERN = re.compile(
    r"FastMCP\("
    r"|@mcp\.server"
    r"|from\s+mcp\.server\s+import\s+Server"
    r"|from\s+mcp\s+import"
    r"|import\s+mcp\b"
    r"|McpServer\("
    r"|MCPServer\("
    r"|@app\.tool\b"
    r"|@server\.tool\b"
    r"|Server\(\s*name\s*="
)

_ENV_VAR_PATTERN_PYTHON = re.compile(
    r"""os\.environ\s*(?:\.get\s*\(\s*|\.?\[?\s*\[?\s*)["']([A-Z][A-Z0-9_]+)["']"""
    r"""|os\.getenv\s*\(\s*["']([A-Z][A-Z0-9_]+)["']"""
)

_ENV_VAR_PATTERN_GO = re.compile(r"""os\.Getenv\(\s*"([A-Z][A-Z0-9_]+)"\s*\)""")

# README patterns: docker -e flags, export statements, JSON config keys
_README_PATTERNS = [
    re.compile(r"""-e\s+([A-Z][A-Z0-9_]+)"""),
    re.compile(r"""export\s+([A-Z][A-Z0-9_]+)="""),
    re.compile(r""""([A-Z][A-Z0-9_]+)"\s*:\s*\""""),
]

_ENV_VAR_PATTERN_TS = re.compile(
    r"""process\.env\.([A-Z][A-Z0-9_]+)"""
    r"""|process\.env\[\s*["']([A-Z][A-Z0-9_]+)["']\s*\]"""
)

_INTERNAL_ENV_VARS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "LANG",
        "TERM",
        "PWD",
        "TMPDIR",
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUSERBASE",
        "PYTHONHOME",
        "PYTHONUNBUFFERED",
        "VIRTUAL_ENV",
        "NODE_ENV",
        "NODE_PATH",
        "NODE_OPTIONS",
        "PORT",
        "HOST",
        "DEBUG",
        "APP",
        "LOG_LEVEL",
        "LOGGING_LEVEL",
        "HOSTNAME",
        "DISPLAY",
        "EDITOR",
        "PAGER",
        "TZ",
        "LC_ALL",
        "LC_CTYPE",
    }
)

# User-facing env vars that match a filtered prefix but should still be detected
_ALLOWED_ENV_VARS = frozenset(
    {
        "GITHUB_TOKEN",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "DOCKER_HOST",
    }
)

# Prefix patterns for build/CI/infrastructure env vars that are never user-facing
_FILTERED_PREFIXES = (
    "CI_",
    "GITHUB_",
    "GITLAB_",
    "CIRCLECI_",
    "TRAVIS_",
    "JENKINS_",
    "BUILDKITE_",
    "DOCKER_",
    "BUILDKIT_",
    "COMPOSE_",
    "NPM_",
    "PIP_",
    "UV_",
    "MCP_LOG_",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clone_repo(git_url: str, dest: str) -> str | None:
    """Shallow-clone a repo using system git. Returns error string or None on success."""
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", git_url, dest],
            capture_output=True,
            text=True,
            timeout=_CLONE_TIMEOUT,
        )
    except FileNotFoundError:
        return "git is not installed or not on PATH"
    except subprocess.TimeoutExpired:
        return f"Clone timed out after {_CLONE_TIMEOUT}s"

    if result.returncode != 0:
        stderr = result.stderr.strip().lower()
        auth_hints = ("authentication", "403", "404", "could not read username", "terminal prompts disabled")
        if any(h in stderr for h in auth_hints):
            return "Repository is private or not accessible."
        if "not found" in stderr or "does not exist" in stderr:
            return "Repository not found. Check the URL."
        return f"git clone failed: {result.stderr.strip()}"
    return None


def _is_filtered_env_var(name: str) -> bool:
    """Return True if the env var is internal/infrastructure and should not be prompted."""
    if name in _ALLOWED_ENV_VARS:
        return False
    if name in _INTERNAL_ENV_VARS:
        return True
    return any(name.startswith(prefix) for prefix in _FILTERED_PREFIXES)


# Directories that contain test / internal / build code — not user-facing config
_SKIP_DIRS = frozenset(
    {
        "test",
        "tests",
        "e2e",
        "internal",
        "testdata",
        "vendor",
        "node_modules",
        "__pycache__",
        ".git",
    }
)


def _is_test_file(path: Path) -> bool:
    """Return True if the file is in a test/internal directory or is a test file."""
    if any(part in _SKIP_DIRS for part in path.parts):
        return True
    name = path.name
    return name.endswith("_test.go") or name.startswith("test_") or name.endswith("_test.py")


def _scan_files_for_env_vars(root: Path, glob: str, pattern: re.Pattern, found: dict[str, str]) -> None:
    """Scan files matching *glob* for env var references using *pattern*."""
    for path in root.rglob(glob):
        if _is_test_file(path.relative_to(root)):
            continue
        try:
            content = path.read_text(errors="ignore")
            for m in pattern.finditer(content):
                name = next((g for g in m.groups() if g), None)
                if name and not _is_filtered_env_var(name):
                    found.setdefault(name, "")
        except Exception:
            continue


def _scan_readme_for_env_vars(root: Path, found: dict[str, str]) -> None:
    """Extract env vars from README files (docker -e, export, JSON config)."""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        readme = root / name
        if not readme.exists():
            continue
        try:
            content = readme.read_text(errors="ignore")
        except Exception:
            continue
        for pattern in _README_PATTERNS:
            for m in pattern.finditer(content):
                var = m.group(1)
                if var and not _is_filtered_env_var(var):
                    found.setdefault(var, "")
        break  # only scan the first README found


def _extract_manifest_env_vars(root: Path, found: dict[str, str]) -> bool:
    """Extract env vars from a server.json MCP manifest (authoritative source).

    The manifest is the standard MCP server descriptor. Env vars declared here
    are always included — they bypass the prefix filter since the author
    explicitly listed them as required.

    Returns True if a valid server.json was found (even if it declares no env vars).
    """
    manifest = root / "server.json"
    if not manifest.exists():
        return False
    try:
        data = json.loads(manifest.read_text(errors="ignore"))
    except Exception:
        return False
    # packages[].runtimeArguments — Docker -e flags (e.g. GitHub MCP server)
    for pkg in data.get("packages", []):
        for arg in pkg.get("runtimeArguments", []):
            value = arg.get("value", "")
            # Pattern: "ENV_VAR={placeholder}" — extract the var name before '='
            if "=" in value:
                var_name = value.split("=", 1)[0]
                if var_name and var_name == var_name.upper():
                    desc = arg.get("description", "")
                    found.setdefault(var_name, desc)

    # remotes[].variables — URL-interpolated secrets (e.g. ?api_key={key})
    for remote in data.get("remotes", []):
        for var_key, var_meta in (remote.get("variables") or {}).items():
            desc = var_meta.get("description", "") if isinstance(var_meta, dict) else ""
            found.setdefault(var_key, desc)
    return True


def _scan_env_example(root: Path, found: dict[str, str]) -> None:
    """Scan .env.example / .env.sample files for documented env vars."""
    for env_file in root.glob(".env*"):
        if env_file.name in (".env", ".env.local"):
            continue  # skip actual secrets
        try:
            for line in env_file.read_text(errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key = line.split("=", 1)[0].strip()
                if key and key == key.upper() and not _is_filtered_env_var(key):
                    found.setdefault(key, "")
        except Exception:
            continue


def _detect_env_vars(tmp_dir: str) -> list[dict]:
    """Scan repo files for required environment variables.

    Tiered detection (stops at first tier that finds results):
      1. server.json manifest (authoritative — author's explicit declaration)
      2. README + .env.example (author's documentation)
      3. Source code scanning (last resort — catches os.Getenv / process.env / etc.)
    """
    root = Path(tmp_dir)
    found: dict[str, str] = {}

    # Tier 1: MCP server manifest — authoritative, skip everything else
    if _extract_manifest_env_vars(root, found):
        return [{"name": k, "description": v, "required": True} for k, v in sorted(found.items())]

    # Tier 2: README — author's documented config (export, docker -e, JSON examples)
    _scan_readme_for_env_vars(root, found)
    if found:
        return [{"name": k, "description": v, "required": True} for k, v in sorted(found.items())]

    # Tier 3: .env.example — explicit config template
    _scan_env_example(root, found)
    if found:
        return [{"name": k, "description": v, "required": True} for k, v in sorted(found.items())]

    # Tier 4: Source code scanning — last resort
    _scan_files_for_env_vars(root, "*.py", _ENV_VAR_PATTERN_PYTHON, found)
    _scan_files_for_env_vars(root, "*.go", _ENV_VAR_PATTERN_GO, found)
    for ext in ("*.ts", "*.js", "*.mts", "*.mjs"):
        _scan_files_for_env_vars(root, ext, _ENV_VAR_PATTERN_TS, found)

    return [{"name": k, "description": v, "required": True} for k, v in sorted(found.items())]


# Regex for Docker registry image references in README
_DOCKER_IMAGE_PATTERN = re.compile(
    r"((?:ghcr\.io|docker\.io|registry\.[a-z0-9.-]+\.[a-z]{2,}|[a-z0-9.-]+\.azurecr\.io|[a-z0-9.-]+\.gcr\.io)"
    r"/[a-z0-9_./-]+"
    r"(?::[a-z0-9._-]+)?)"
)


def _detect_docker_image(root: Path, git_url: str) -> tuple[str | None, bool]:
    """Detect Docker image from repo artifacts.

    Returns (image, is_suggested). is_suggested=True for GHCR inference from git URL.

    Priority: compose image > README reference > GHCR inference from git URL.
    Dockerfile FROM is not returned (it's the build base, not the published image).
    """
    # 1. docker-compose / compose files — most authoritative for pre-built images
    for compose_name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        compose_file = root / compose_name
        if compose_file.exists():
            try:
                import yaml

                data = yaml.safe_load(compose_file.read_text(errors="ignore"))
                for svc in (data.get("services") or {}).values():
                    img = svc.get("image")
                    if img and isinstance(img, str):
                        return (img, False)
            except Exception:
                pass

    # 2. README — look for registry image references
    for readme_name in ("README.md", "README.rst", "README.txt", "README"):
        readme = root / readme_name
        if not readme.exists():
            continue
        try:
            content = readme.read_text(errors="ignore")
            m = _DOCKER_IMAGE_PATTERN.search(content)
            if m:
                return (m.group(1), False)
        except Exception:
            pass
        break

    # 3. Infer GHCR from GitHub URL
    _safe_name = re.compile(r"^[a-zA-Z0-9._-]+$")
    try:
        url_parts = urlparse(git_url)
        if url_parts.hostname and "github.com" in url_parts.hostname:
            path = url_parts.path.strip("/")
            if path.endswith(".git"):
                path = path[:-4]
            parts = path.split("/")
            if len(parts) >= 2 and _safe_name.match(parts[0]) and _safe_name.match(parts[1]):
                return (f"ghcr.io/{parts[0]}/{parts[1]}", True)
    except Exception:
        pass

    return (None, False)


def _infer_command_args(
    framework: str | None,
    docker_image: str | None,
    name: str,
    entry_point: str | None = None,
) -> tuple[str | None, list[str] | None]:
    """Infer the startup command and args from framework + docker image.

    Returns (command, args) or (None, None) if nothing can be inferred.
    """
    if docker_image:
        return ("docker", ["run", "-i", "--rm", docker_image])

    fw = (framework or "").lower()
    if "typescript" in fw or "ts" in fw:
        return ("npx", ["-y", name])
    if "go" in fw:
        return (name, [])
    if "python" in fw or entry_point:
        return ("python", ["-m", name])

    return (None, None)


def _detect_non_python_mcp(tmp_dir: str) -> str | None:
    """Check for non-Python MCP frameworks. Returns framework name or None."""
    root = Path(tmp_dir)

    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(errors="ignore"))
            all_deps = {}
            all_deps.update(data.get("dependencies", {}))
            all_deps.update(data.get("devDependencies", {}))
            if "@modelcontextprotocol/sdk" in all_deps:
                return "typescript-mcp-sdk"
        except Exception:
            pass

    for go_file in root.rglob("*.go"):
        try:
            content = go_file.read_text(errors="ignore")
            if "mcp-go" in content or "mcp_go" in content:
                return "go-mcp-sdk"
        except Exception:
            continue

    return None


def _extract_repo_name(git_url: str, tmp_dir: str) -> str:
    """Extract a usable name from the git URL or directory name as fallback."""
    try:
        parsed = urlparse(git_url)
        path = parsed.path.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        name = path.rsplit("/", 1)[-1]
        if name:
            return name
    except Exception:
        pass
    return Path(tmp_dir).name or "unknown"


def _analyze_python_entry(tree: ast.AST, git_url: str, tmp_dir: str) -> tuple[str, str, list[dict], list[str]]:
    """Extract server name, description, tools, and issues from an AST.

    Returns (server_name, server_desc, tools, issues).
    """
    server_name = ""
    server_desc = ""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id == "FastMCP":
            if node.args and isinstance(node.args[0], ast.Constant):
                server_name = str(node.args[0].value)
            for kw in node.keywords:
                if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                    server_desc = str(kw.value.value)
            if server_name:
                break
        if node.func.id == "Server":
            for kw in node.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    server_name = str(kw.value.value)
                if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                    server_desc = str(kw.value.value)
            if not server_name and node.args and isinstance(node.args[0], ast.Constant):
                server_name = str(node.args[0].value)
            if server_name:
                break

    if not server_name:
        server_name = _extract_repo_name(git_url, tmp_dir)

    tools: list[dict] = []
    issues: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        is_tool = any(
            (isinstance(d, ast.Attribute) and d.attr == "tool")
            or (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "tool")
            for d in node.decorator_list
        )
        if is_tool:
            docstring = ast.get_docstring(node) or ""
            untyped = [a.arg for a in node.args.args if a.arg != "self" and a.annotation is None]
            tools.append({"name": node.name, "docstring": docstring})
            if len(docstring) < 20:
                issues.append(f"Tool '{node.name}': docstring too short ({len(docstring)} chars, need 20+)")
            if untyped:
                issues.append(f"Tool '{node.name}': untyped params: {', '.join(untyped)}")

    if not tools:
        issues.append("No @tool decorated functions found")

    return server_name, server_desc, tools, issues


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_local(git_url: str) -> dict:
    """Clone a repo locally and analyze it for MCP metadata.

    Returns a dict matching the McpAnalyzeResponse shape:
    {name, description, version, tools, environment_variables, issues, error}
    """
    logger.debug("analyze_local: git_url={}", git_url)
    _empty: dict = {"name": "", "description": "", "version": "0.1.0", "tools": []}

    tmp_dir = tempfile.mkdtemp(prefix="observal_cli_analyze_")
    try:
        clone_err = _clone_repo(git_url, tmp_dir)
        if clone_err:
            return {**_empty, "error": clone_err}

        # Find Python MCP entry point
        entry_point = None
        for py_file in Path(tmp_dir).rglob("*.py"):
            try:
                if _PYTHON_MCP_PATTERN.search(py_file.read_text(errors="ignore")):
                    entry_point = py_file
                    break
            except Exception:
                continue

        env_vars = _detect_env_vars(tmp_dir)

        if not entry_point:
            non_python = _detect_non_python_mcp(tmp_dir)
            name = _extract_repo_name(git_url, tmp_dir)
            docker_image, docker_suggested = _detect_docker_image(Path(tmp_dir), git_url)
            cmd, cmd_args = _infer_command_args(non_python, docker_image, name)
            base: dict = {
                "name": name,
                "description": "",
                "version": "0.1.0",
                "tools": [],
                "environment_variables": env_vars,
            }
            if non_python:
                base["framework"] = non_python
            if docker_image:
                base["docker_image"] = docker_image
                base["docker_image_suggested"] = docker_suggested
            if cmd:
                base["command"] = cmd
                base["args"] = cmd_args
            return base

        tree = ast.parse(entry_point.read_text(errors="ignore"))
        server_name, server_desc, tools, issues = _analyze_python_entry(tree, git_url, tmp_dir)
        relative_entry = str(entry_point.relative_to(tmp_dir))

        docker_image, docker_suggested = _detect_docker_image(Path(tmp_dir), git_url)
        cmd, cmd_args = _infer_command_args("python", docker_image, server_name, relative_entry)
        result: dict = {
            "name": server_name,
            "description": server_desc,
            "version": "0.1.0",
            "tools": tools,
            "issues": issues,
            "environment_variables": env_vars,
            "entry_point": relative_entry,
        }
        if docker_image:
            result["docker_image"] = docker_image
            result["docker_image_suggested"] = docker_suggested
        if cmd:
            result["command"] = cmd
            result["args"] = cmd_args
        return result
    except Exception:
        return {**_empty, "error": "Local analysis failed unexpectedly."}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
