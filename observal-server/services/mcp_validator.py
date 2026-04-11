import ast
import json
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from git import Repo
from sqlalchemy.ext.asyncio import AsyncSession

from models.mcp import McpListing, McpValidationResult

ALLOWED_SCHEMES = {"https", "http"}
BLOCKED_SCHEMES = {"file", "ftp", "ssh", "git"}

# Patterns that indicate an MCP server implementation (Python files)
_PYTHON_MCP_PATTERN = re.compile(
    r"FastMCP\("  # FastMCP framework
    r"|@mcp\.server"  # standard MCP SDK decorator
    r"|from\s+mcp\.server\s+import\s+Server"  # standard MCP SDK Server import
    r"|from\s+mcp\s+import"  # any MCP SDK usage
    r"|import\s+mcp\b"  # any MCP SDK usage
    r"|McpServer\("  # common custom class name
    r"|MCPServer\("  # common custom class name (alt casing)
    r"|@app\.tool\b"  # common tool decorator
    r"|@server\.tool\b"  # common tool decorator
    r"|Server\(\s*name\s*="  # Server(name=...) pattern
)


def _validate_git_url(url: str) -> str | None:
    """Returns error message if URL is unsafe, None if OK."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL"
    if parsed.scheme not in ALLOWED_SCHEMES:
        return f"URL scheme '{parsed.scheme}' not allowed. Use https://"
    if not parsed.hostname:
        return "URL has no hostname"
    # Block internal/private IPs
    hostname = parsed.hostname.lower()
    if (
        hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
        or hostname.startswith("10.")
        or hostname.startswith("192.168.")
        or hostname.startswith("172.")
    ):
        return "Internal/private URLs not allowed"
    return None


def _detect_non_python_mcp(tmp_dir: str) -> str | None:
    """Check for non-Python MCP frameworks. Returns framework name or None."""
    root = Path(tmp_dir)

    # Check package.json for @modelcontextprotocol/sdk (TypeScript/JS)
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

    # Check Go files for mcp-go imports
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


async def run_validation(listing: McpListing, db: AsyncSession):
    tmp_dir = tempfile.mkdtemp(prefix="observal_")
    try:
        # Stage 1: Clone & Inspect
        entry_point = await _clone_and_inspect(listing, db, tmp_dir)
        if not entry_point:
            return

        # Stage 2: Manifest Validation
        await _manifest_validation(listing, db, entry_point, tmp_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def _clone_and_inspect(listing: McpListing, db: AsyncSession, tmp_dir: str) -> Path | None:
    url_err = _validate_git_url(listing.git_url)
    if url_err:
        db.add(McpValidationResult(listing_id=listing.id, stage="clone_and_inspect", passed=False, details=url_err))
        await db.commit()
        return None
    try:
        Repo.clone_from(listing.git_url, tmp_dir, depth=1)
    except Exception as e:
        db.add(
            McpValidationResult(
                listing_id=listing.id,
                stage="clone_and_inspect",
                passed=False,
                details=f"Failed to clone repo: {e}",
            )
        )
        await db.commit()
        return None

    # Try Python files first
    entry_point = None
    for py_file in Path(tmp_dir).rglob("*.py"):
        try:
            content = py_file.read_text(errors="ignore")
            if _PYTHON_MCP_PATTERN.search(content):
                entry_point = py_file
                break
        except Exception:
            continue

    if entry_point:
        listing.mcp_validated = True
        db.add(
            McpValidationResult(
                listing_id=listing.id,
                stage="clone_and_inspect",
                passed=True,
                details=f"Found MCP entry point: {entry_point.relative_to(tmp_dir)}",
            )
        )
        await db.commit()
        return entry_point

    # Try non-Python MCP frameworks
    non_python_framework = _detect_non_python_mcp(tmp_dir)
    if non_python_framework:
        listing.mcp_validated = True
        db.add(
            McpValidationResult(
                listing_id=listing.id,
                stage="clone_and_inspect",
                passed=True,
                details=f"Found non-Python MCP framework: {non_python_framework}",
            )
        )
        await db.commit()
        return None

    # No known framework detected — still mark as validated but note unknown framework
    listing.mcp_validated = True
    db.add(
        McpValidationResult(
            listing_id=listing.id,
            stage="clone_and_inspect",
            passed=True,
            details=(
                "No recognized MCP framework detected. "
                "Marked as validated with framework: unknown. "
                "Supported detection: FastMCP, MCP SDK (Python/TypeScript/Go), "
                "and common MCP patterns."
            ),
        )
    )
    await db.commit()
    return None


async def _manifest_validation(listing: McpListing, db: AsyncSession, entry_point: Path, tmp_dir: str):
    issues = []
    tools_found = []

    try:
        tree = ast.parse(entry_point.read_text(errors="ignore"))
    except SyntaxError as e:
        db.add(
            McpValidationResult(
                listing_id=listing.id,
                stage="manifest_validation",
                passed=False,
                details=f"Syntax error in entry point: {e}",
            )
        )
        await db.commit()
        return

    # Extract server name from FastMCP() or Server(name=...) constructor
    server_name = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # FastMCP("name") pattern
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "FastMCP"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            server_name = node.args[0].value
            break
        # Server(name="name") pattern
        if isinstance(node.func, ast.Name) and node.func.id == "Server":
            for kw in node.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    server_name = kw.value.value
                    break
            if server_name:
                break
            # Server("name") positional
            if node.args and isinstance(node.args[0], ast.Constant):
                server_name = node.args[0].value
                break

    # Fallback to repo/directory name
    if not server_name:
        server_name = _extract_repo_name(listing.git_url, tmp_dir)

    # Find @mcp.tool / @app.tool / @server.tool decorated functions
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        is_tool = any(
            (isinstance(d, ast.Attribute) and d.attr == "tool")
            or (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "tool")
            for d in node.decorator_list
        )
        if not is_tool:
            continue

        docstring = ast.get_docstring(node) or ""
        # Check params have type annotations (skip 'self' and 'return')
        untyped = [a.arg for a in node.args.args if a.arg != "self" and a.annotation is None]

        tools_found.append(
            {
                "name": node.name,
                "docstring": docstring[:100],
                "has_types": len(untyped) == 0,
            }
        )

        if len(docstring) < 20:
            issues.append(f"Tool '{node.name}' docstring too short ({len(docstring)} chars, need 20+)")
        if untyped:
            issues.append(f"Tool '{node.name}' has untyped params: {', '.join(untyped)}")

    if len(listing.description) < 100:
        issues.append(f"Server description too short ({len(listing.description)} chars, need 100+)")

    if not tools_found:
        issues.append("No @tool decorated functions found")

    passed = len(issues) == 0
    details = f"Server: {server_name}, Tools: {len(tools_found)}"
    if issues:
        details += "\nIssues:\n- " + "\n- ".join(issues)

    if not passed:
        listing.mcp_validated = False

    db.add(
        McpValidationResult(
            listing_id=listing.id,
            stage="manifest_validation",
            passed=passed,
            details=details,
        )
    )
    await db.commit()


async def analyze_repo(git_url: str) -> dict:
    """Clone and analyze a repo without creating a listing. Returns extracted metadata."""
    url_err = _validate_git_url(git_url)
    if url_err:
        return {"name": "", "description": "", "version": "0.1.0", "tools": []}
    tmp_dir = tempfile.mkdtemp(prefix="observal_analyze_")
    try:
        Repo.clone_from(git_url, tmp_dir, depth=1)

        entry_point = None
        for py_file in Path(tmp_dir).rglob("*.py"):
            try:
                if _PYTHON_MCP_PATTERN.search(py_file.read_text(errors="ignore")):
                    entry_point = py_file
                    break
            except Exception:
                continue

        if not entry_point:
            # Try non-Python detection; return repo name as fallback
            non_python = _detect_non_python_mcp(tmp_dir)
            name = _extract_repo_name(git_url, tmp_dir)
            if non_python:
                return {"name": name, "description": "", "version": "0.1.0", "tools": [], "framework": non_python}
            return {"name": name, "description": "", "version": "0.1.0", "tools": []}

        tree = ast.parse(entry_point.read_text(errors="ignore"))

        server_name = ""
        server_desc = ""
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            # FastMCP("name") pattern
            if node.func.id == "FastMCP":
                if node.args and isinstance(node.args[0], ast.Constant):
                    server_name = str(node.args[0].value)
                for kw in node.keywords:
                    if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                        server_desc = str(kw.value.value)
                if server_name:
                    break
            # Server(name="name") pattern
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

        # Fallback to repo name
        if not server_name:
            server_name = _extract_repo_name(git_url, tmp_dir)

        tools = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            is_tool = any(
                (isinstance(d, ast.Attribute) and d.attr == "tool")
                or (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "tool")
                for d in node.decorator_list
            )
            if is_tool:
                tools.append({"name": node.name, "docstring": ast.get_docstring(node) or ""})

        return {"name": server_name, "description": server_desc, "version": "0.1.0", "tools": tools}
    except Exception:
        return {"name": "", "description": "", "version": "0.1.0", "tools": []}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
