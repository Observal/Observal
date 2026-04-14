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

_ENV_VAR_PATTERN = re.compile(
    r"""os\.environ\s*(?:\.get\s*\(\s*|\.?\[?\s*\[?\s*)["']([A-Z][A-Z0-9_]+)["']"""
    r"""|os\.getenv\s*\(\s*["']([A-Z][A-Z0-9_]+)["']"""
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
        "VIRTUAL_ENV",
        "NODE_ENV",
        "PORT",
        "HOST",
        "DEBUG",
        "LOG_LEVEL",
        "LOGGING_LEVEL",
    }
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


def _detect_env_vars(tmp_dir: str) -> list[dict]:
    """Scan repo files for required environment variables."""
    root = Path(tmp_dir)
    found: dict[str, str] = {}

    for py_file in root.rglob("*.py"):
        try:
            content = py_file.read_text(errors="ignore")
            for m in _ENV_VAR_PATTERN.finditer(content):
                name = m.group(1) or m.group(2)
                if name and name not in _INTERNAL_ENV_VARS:
                    found.setdefault(name, "")
        except Exception:
            continue

    for env_file in root.glob(".env*"):
        if env_file.name in (".env", ".env.local"):
            continue
        try:
            for line in env_file.read_text(errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key = line.split("=", 1)[0].strip()
                if key and key == key.upper() and key not in _INTERNAL_ENV_VARS:
                    found.setdefault(key, "")
        except Exception:
            continue

    for dockerfile in (root / "Dockerfile", root / "dockerfile"):
        if not dockerfile.exists():
            continue
        try:
            for line in dockerfile.read_text(errors="ignore").splitlines():
                stripped = line.strip()
                if stripped.startswith(("ENV ", "ARG ")):
                    parts = stripped.split(None, 2)
                    if len(parts) >= 2:
                        key = parts[1].split("=", 1)[0]
                        if key and key == key.upper() and key not in _INTERNAL_ENV_VARS:
                            found.setdefault(key, "")
        except Exception:
            continue

    return [{"name": k, "description": v, "required": True} for k, v in sorted(found.items())]


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
            base = {"name": name, "description": "", "version": "0.1.0", "tools": [], "environment_variables": env_vars}
            if non_python:
                return {**base, "framework": non_python}
            return base

        tree = ast.parse(entry_point.read_text(errors="ignore"))
        server_name, server_desc, tools, issues = _analyze_python_entry(tree, git_url, tmp_dir)

        return {
            "name": server_name,
            "description": server_desc,
            "version": "0.1.0",
            "tools": tools,
            "issues": issues,
            "environment_variables": env_vars,
        }
    except Exception:
        return {**_empty, "error": "Local analysis failed unexpectedly."}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
