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
from rich import print as rprint
from rich.console import Console

from observal_cli import config

console = Console(stderr=True)
logger = logging.getLogger(__name__)


def _client() -> tuple[str, dict]:
    cfg = config.get_or_exit()
    return cfg["server_url"].rstrip("/"), {"Authorization": f"Bearer {cfg['access_token']}"}


def _handle_error(e: httpx.HTTPStatusError, path: str = ""):
    """Handle HTTP errors with actionable messages."""
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
        # 'agent' is a top-level subcommand, not nested under 'registry'
        browse_cmd = "observal agent list" if type_singular == "agent" else f"observal registry {type_singular} list"
        rprint(f"[dim]  Check that the resource ID is correct, or use [bold]{browse_cmd}[/bold] to browse.[/dim]")
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
    timeout = config.get_timeout()
    func = getattr(httpx, method)

    kwargs: dict = {"headers": headers, "timeout": timeout}
    if params is not None:
        kwargs["params"] = params
    if json is not None:
        kwargs["json"] = json

    for attempt in range(_MAX_RETRIES):
        r = func(url, **kwargs)

        # Auto-refresh on 401
        if r.status_code == 401 and attempt == 0 and _try_refresh_token():
            # Update headers with new token and retry
            cfg = config.load()
            headers["Authorization"] = f"Bearer {cfg['access_token']}"
            kwargs["headers"] = headers
            continue

        if r.status_code not in _RETRY_STATUSES or attempt == _MAX_RETRIES - 1:
            r.raise_for_status()
            return r
        # Honor Retry-After header if present
        retry_after = r.headers.get("Retry-After")
        delay = float(retry_after) if retry_after else 0.5 * (2**attempt)
        safe_url = urlunparse(urlparse(url)._replace(netloc=urlparse(url).hostname or ""))
        logger.debug(f"Retrying {method.upper()} {safe_url} (attempt {attempt + 1}, delay {delay:.1f}s)")
        time.sleep(delay)
    return r  # unreachable but satisfies type checker


def get(path: str, params: dict | None = None) -> dict:
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

    Returns False on any error (fail-open, silent — no printed messages).
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


def check_version_compatibility(server_url: str) -> None:
    """Warn if CLI version is older than server's minimum requirement."""
    from importlib.metadata import version as pkg_version

    try:
        cli_ver_str = pkg_version("observal-cli")
    except Exception:
        return  # dev install, skip check

    try:
        r = httpx.get(f"{server_url.rstrip('/')}/api/v1/config/version", timeout=5)
        if r.status_code != 200:
            return
        data = r.json()
    except Exception:
        return  # server doesn't support this endpoint yet, skip

    min_cli = data.get("min_cli_version")
    server_ver = data.get("server_version", "unknown")
    if not min_cli:
        return

    try:
        cli_tuple = tuple(int(x) for x in cli_ver_str.split("."))
        min_tuple = tuple(int(x) for x in min_cli.split("."))
        if cli_tuple < min_tuple:
            rprint(
                f"\n[bold yellow]⚠ CLI version {cli_ver_str} is older than the server requires "
                f"(minimum {min_cli}).[/bold yellow]\n"
                f"  Server version: {server_ver}\n"
                f"  Please upgrade:\n\n"
                f"    [cyan]uv tool upgrade observal-cli[/cyan]    "
                f"[dim]# or: pip install --upgrade observal-cli[/dim]\n"
            )
    except (ValueError, TypeError):
        pass
