# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import logging
import time
from urllib.parse import urlparse, urlunparse

import httpx
import typer
from loguru import logger as optic
from rich import print as rprint
from rich.console import Console

from observal_cli import config

console = Console(stderr=True)
logger = logging.getLogger(__name__)

# Cached server version for the process lifetime
_server_version_cache: str | None = None
# Whether version enforcement has already run this session
_version_enforced: bool = False

# Subcommands exempt from version enforcement (user needs these to fix mismatches)
_EXEMPT_SUBCOMMANDS = frozenset({"self", "server"})


def _get_cli_version() -> str:
    """Get current CLI version string for request headers."""
    try:
        from importlib.metadata import version

        return version("observal-cli")
    except Exception:
        return "0.0.0"


def _client() -> tuple[str, dict]:
    cfg = config.get_or_exit()
    base_url = cfg["server_url"].rstrip("/")
    headers = {
        "Authorization": f"Bearer {cfg['access_token']}",
        "X-Observal-CLI-Version": _get_cli_version(),
    }
    # Run version enforcement once per session (unless exempt subcommand)
    _enforce_version_once(base_url)
    return base_url, headers


def _enforce_version_once(server_url: str) -> None:
    """Run version enforcement exactly once per CLI session.

    Checks if CLI version exactly matches server. Hard exits on mismatch.
    Exempt: `observal self` and `observal server` subcommands.
    """
    global _version_enforced
    if _version_enforced:
        return
    _version_enforced = True

    # Check if current subcommand is exempt (handle flags before subcommand)
    import sys

    positional_args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if positional_args and positional_args[0] in _EXEMPT_SUBCOMMANDS:
        return

    from observal_cli.version_check import check_version_compatibility

    check_version_compatibility(server_url)


def _handle_error(e: httpx.HTTPStatusError, path: str = ""):
    """Handle HTTP errors with actionable messages."""
    optic.trace("e={}, path={}", e, path)
    ct = e.response.headers.get("content-type", "")
    if "application/json" in ct:
        try:
            detail = e.response.json().get("detail", e.response.text)
        except (ValueError, UnicodeDecodeError):
            detail = e.response.text
    else:
        detail = e.response.text
    code = e.response.status_code

    path_info = f" ({path})" if path else ""

    if code == 401:
        rprint(f"[red]Authentication failed{path_info}.[/red]")
        rprint("[dim]  Run [bold]observal auth login[/bold] to re-authenticate.[/dim]")
    elif code == 403:
        rprint(f"[red]Permission denied{path_info}.[/red]")
        if detail:
            rprint(f"[dim]  {detail}[/dim]")
        else:
            rprint("[dim]  You do not have permission to perform this action.[/dim]")
    elif code == 404:
        rprint(f"[red]Not found{path_info}.[/red]")
        # Extract component type from API path (e.g. /api/v1/hooks/abc -> hook)
        parts = path.strip("/").split("/")
        type_plural = parts[2] if len(parts) > 2 else "mcps"
        if type_plural.endswith("xes"):
            type_singular = type_plural[:-2]  # sandboxes -> sandbox
        elif type_plural.endswith("s"):
            type_singular = type_plural[:-1]  # mcps -> mcp, skills -> skill
        else:
            type_singular = type_plural
        if len(parts) > 3 and parts[2] == "insights" and parts[3] == "agents":
            browse_cmd = "observal agent list"
        else:
            # 'agent' is a top-level subcommand, not nested under 'registry'
            browse_cmd = (
                "observal agent list" if type_singular == "agent" else f"observal registry {type_singular} list"
            )
        rprint(f"[dim]  Check that the resource ID is correct, or use [bold]{browse_cmd}[/bold] to browse.[/dim]")
    elif code == 426:
        rprint(f"[red]Version mismatch{path_info}.[/red]")
        if detail:
            rprint(f"[dim]  {detail}[/dim]")
    elif code == 429:
        rprint(f"[red]Rate limited{path_info}.[/red]")
        retry_after = e.response.headers.get("Retry-After", "a few seconds")
        rprint(f"[dim]  Try again in {retry_after}.[/dim]")
    elif code >= 500:
        rprint(f"[red]Server error {code}{path_info}.[/red]")
        rprint("[dim]  Check server logs or run [bold]observal doctor[/bold] for diagnostics.[/dim]")
    else:
        rprint(f"[red]Error {code}{path_info}:[/red] {detail}")

    raise typer.Exit(code=1)


def _handle_connect():
    """Handle connection errors."""
    cfg = config.load()
    server_url = cfg.get("server_url", "not set")
    rprint("[red]Connection failed.[/red] Cannot reach the Observal server.")
    rprint(f"[dim]  Server URL: {server_url}[/dim]")
    rprint("[dim]  Is the server running? Try [bold]observal doctor[/bold] to diagnose.[/dim]")
    raise typer.Exit(code=1)


def _handle_timeout(path: str = ""):
    """Handle request timeout."""
    optic.trace("path={}", path)
    timeout = config.get_timeout()
    path_info = f" ({path})" if path else ""
    rprint(f"[red]Request timed out{path_info}.[/red]")
    rprint(f"[dim]  Timeout: {timeout}s. Increase with [bold]OBSERVAL_TIMEOUT[/bold] env var or config.[/dim]")
    rprint("[dim]  Check server health with [bold]observal doctor[/bold].[/dim]")
    raise typer.Exit(code=1)


def _try_refresh_token() -> bool:
    """Attempt to refresh the access token using the stored refresh token.

    Returns True if the refresh succeeded and config was updated.
    """
    cfg = config.load()
    refresh_token = cfg.get("refresh_token")
    server_url = cfg.get("server_url", "").rstrip("/")
    if not refresh_token or not server_url:
        return False

    try:
        r = httpx.post(
            f"{server_url}/api/v1/auth/token/refresh",
            json={"refresh_token": refresh_token},
            timeout=10,
        )
        if r.status_code != 200:
            return False
        data = r.json()
        config.save(
            {
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
            }
        )
        return True
    except Exception:
        return False


_MAX_RETRIES = 3
_RETRY_STATUSES = {429, 503, 504}


def _request_with_retry(
    method: str,
    url: str,
    headers: dict,
    *,
    params: dict | None = None,
    json: dict | None = None,
) -> httpx.Response:
    """Execute an HTTP request with retries on 429/503/504 and Retry-After support.

    On 401, attempts a token refresh and retries once.
    """
    optic.trace("method={}, url={}", method, url)
    timeout = config.get_timeout()
    func = getattr(httpx, method)

    kwargs: dict = {"headers": headers, "timeout": timeout}
    if params is not None:
        kwargs["params"] = params
    if json is not None:
        kwargs["json"] = json

    safe_url = urlunparse(urlparse(url)._replace(netloc=urlparse(url).hostname or ""))
    optic.debug("{} {}", method.upper(), safe_url)
    t0 = time.monotonic()

    for attempt in range(_MAX_RETRIES):
        r = func(url, **kwargs)

        # Auto-refresh on 401
        if r.status_code == 401 and attempt == 0 and _try_refresh_token():
            # Update headers with new token and retry
            cfg = config.load()
            headers["Authorization"] = f"Bearer {cfg['access_token']}"
            kwargs["headers"] = headers
            optic.debug("token refreshed, retrying")
            continue

        if r.status_code not in _RETRY_STATUSES or attempt == _MAX_RETRIES - 1:
            elapsed = (time.monotonic() - t0) * 1000
            optic.debug("{} {} -> {} ({:.0f}ms)", method.upper(), safe_url, r.status_code, elapsed)
            r.raise_for_status()
            return r
        # Honor Retry-After header if present
        retry_after = r.headers.get("Retry-After")
        delay = float(retry_after) if retry_after else 0.5 * (2**attempt)
        logger.debug(f"Retrying {method.upper()} {safe_url} (attempt {attempt + 1}, delay {delay:.1f}s)")
        optic.debug("retrying {} {} (attempt {}, delay {:.1f}s)", method.upper(), safe_url, attempt + 1, delay)
        time.sleep(delay)
    return r  # unreachable but satisfies type checker


def get(path: str, params: dict | None = None) -> dict:
    optic.trace("path={}, params={}", path, params)
    base, headers = _client()
    try:
        r = _request_with_retry("get", f"{base}{path}", headers, params=params)
        return r.json()
    except httpx.HTTPStatusError as e:
        _handle_error(e, path)
    except httpx.ReadTimeout:
        _handle_timeout(path)
    except httpx.ConnectError:
        _handle_connect()


def get_with_headers(path: str, params: dict | None = None) -> tuple[dict, dict[str, str]]:
    """Like ``get()``, but also returns the response headers (lowercased keys).

    Useful for paginated endpoints that return the page count via headers like
    ``X-Total-Count``.
    """
    optic.trace("path={}, params={}", path, params)
    base, headers = _client()
    try:
        r = _request_with_retry("get", f"{base}{path}", headers, params=params)
        # Normalize header keys to lowercase for case-insensitive lookup
        resp_headers = {k.lower(): v for k, v in r.headers.items()}
        return r.json(), resp_headers
    except httpx.HTTPStatusError as e:
        _handle_error(e, path)
    except httpx.ReadTimeout:
        _handle_timeout(path)
    except httpx.ConnectError:
        _handle_connect()


def post(path: str, json_data: dict | None = None) -> dict:
    optic.trace("path={}, json_data={}", path, json_data)
    base, headers = _client()
    try:
        r = _request_with_retry("post", f"{base}{path}", headers, json=json_data)
        return r.json()
    except httpx.HTTPStatusError as e:
        _handle_error(e, path)
    except httpx.ReadTimeout:
        _handle_timeout(path)
    except httpx.ConnectError:
        _handle_connect()


def put(path: str, json_data: dict | None = None) -> dict:
    optic.trace("path={}, json_data={}", path, json_data)
    base, headers = _client()
    try:
        r = _request_with_retry("put", f"{base}{path}", headers, json=json_data)
        return r.json()
    except httpx.HTTPStatusError as e:
        _handle_error(e, path)
    except httpx.ReadTimeout:
        _handle_timeout(path)
    except httpx.ConnectError:
        _handle_connect()


def patch(path: str, json_data: dict | None = None) -> dict:
    optic.trace("path={}, json_data={}", path, json_data)
    base, headers = _client()
    try:
        r = _request_with_retry("patch", f"{base}{path}", headers, json=json_data)
        return r.json()
    except httpx.HTTPStatusError as e:
        _handle_error(e, path)
    except httpx.ReadTimeout:
        _handle_timeout(path)
    except httpx.ConnectError:
        _handle_connect()


def delete(path: str) -> dict:
    optic.trace("path={}", path)
    base, headers = _client()
    try:
        r = _request_with_retry("delete", f"{base}{path}", headers)
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()
    except httpx.HTTPStatusError as e:
        _handle_error(e, path)
    except httpx.ReadTimeout:
        _handle_timeout(path)
    except httpx.ConnectError:
        _handle_connect()


def get_registered_agents_only() -> bool:
    """Check if the org has registered-agents-only mode enabled.

    Returns False on any error (fail-open, silent, no printed messages).
    """
    try:
        cfg = config.load()
        server_url = cfg.get("server_url", "").rstrip("/")
        token = cfg.get("access_token", "")
        if not server_url or not token:
            return False
        r = httpx.get(
            f"{server_url}/api/v1/admin/org/registered-agents-only",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if r.status_code == 200:
            return r.json().get("registered_agents_only", False)
        return False
    except Exception:
        return False


def get_registered_agent_names() -> set[str]:
    """Fetch the set of registered (approved) agent names from the server.

    Returns empty set on any error (fail-open).
    """
    try:
        cfg = config.load()
        server_url = cfg.get("server_url", "").rstrip("/")
        token = cfg.get("access_token", "")
        if not server_url or not token:
            return set()
        r = httpx.get(
            f"{server_url}/api/v1/agents",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if r.status_code == 200:
            return {item.get("name", "") for item in r.json() if item.get("name")}
    except Exception:
        pass
    return set()


def get_registered_mcp_names() -> set[str]:
    """Fetch the set of registered (approved) MCP names from the server.

    Returns empty set on any error (fail-open).
    """
    try:
        cfg = config.load()
        server_url = cfg.get("server_url", "").rstrip("/")
        token = cfg.get("access_token", "")
        if not server_url or not token:
            return set()
        r = httpx.get(
            f"{server_url}/api/v1/mcp",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if r.status_code == 200:
            return {item.get("name", "") for item in r.json() if item.get("name")}
    except Exception:
        pass
    return set()


def health() -> tuple[bool, float]:
    """Check server health. Returns (ok, latency_ms)."""
    cfg = config.load()
    url = cfg.get("server_url", "").rstrip("/")
    if not url:
        return False, 0
    try:
        t0 = time.monotonic()
        r = httpx.get(f"{url}/health", timeout=5)
        latency = (time.monotonic() - t0) * 1000
        return r.status_code == 200, latency
    except Exception:
        return False, 0


def server_supports(feature: str) -> bool:
    """Check if the connected server supports a given feature.

    Uses version negotiation: effective = min(cli_version, server_version).
    Feature availability is determined by the features registry.
    """
    optic.trace("feature={}", feature)
    global _server_version_cache
    if _server_version_cache is None:
        try:
            data = get("/api/v1/config/version")
            _server_version_cache = data.get("server_version", "0.0.0")
        except Exception:
            return False

    from packaging.version import Version

    from observal_cli.features import is_available

    cli_ver = _get_cli_version()
    try:
        effective = str(min(Version(cli_ver), Version(_server_version_cache)))
    except Exception:
        effective = _server_version_cache

    return is_available(feature, effective)
