import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".observal"
CONFIG_FILE = CONFIG_DIR / "config.json"
ALIASES_FILE = CONFIG_DIR / "aliases.json"
LAST_RESULTS_FILE = CONFIG_DIR / "last_results.json"

DEFAULTS = {
    "output": "table",
    "color": True,
    "server_url": "",
    "access_token": "",
    "refresh_token": "",
    "timeout": 30,
}


def load() -> dict:
    """Load config from disk and apply environment variable overrides."""
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text()))

    # Environment variable overrides (No login required if these are set)
    if env_url := os.environ.get("OBSERVAL_SERVER_URL"):
        cfg["server_url"] = env_url
    if env_token := os.environ.get("OBSERVAL_ACCESS_TOKEN"):
        cfg["access_token"] = env_token
    # Backward compat: OBSERVAL_API_KEY env var maps to access_token
    if env_key := os.environ.get("OBSERVAL_API_KEY"):
        cfg["access_token"] = env_key
    # CI/CD convenience: OBSERVAL_TOKEN env var (e.g. from SSO service tokens)
    if env_ci_token := os.environ.get("OBSERVAL_TOKEN"):
        cfg["access_token"] = env_ci_token

    return cfg


def save(data: dict):
    """Save config to disk (safely ignoring environment variables)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Read strictly from disk so we don't accidentally save env vars
    existing = {}
    if CONFIG_FILE.exists():
        existing = json.loads(CONFIG_FILE.read_text())

    existing.update(data)

    # Write with restrictive permissions from the start (contains API key)
    old_umask = os.umask(0o077)
    try:
        CONFIG_FILE.write_text(json.dumps(existing, indent=2))
    finally:
        os.umask(old_umask)


def get_timeout() -> int:
    """Get request timeout in seconds. Env var > config > default."""
    env_timeout = os.environ.get("OBSERVAL_TIMEOUT")
    if env_timeout:
        try:
            return int(env_timeout)
        except ValueError:
            logger.warning("Invalid OBSERVAL_TIMEOUT=%r, falling back to config/default", env_timeout)
    cfg = load()
    return int(cfg.get("timeout", 30))


def get_or_exit() -> dict:
    cfg = load()
    if not cfg.get("server_url") or not cfg.get("access_token"):
        import typer
        from rich import print as rprint

        rprint(
            "[red]Not configured.[/red] Run [bold]observal auth login[/bold] or set the [bold]OBSERVAL_TOKEN[/bold] / [bold]OBSERVAL_ACCESS_TOKEN[/bold] environment variable."
        )
        raise typer.Exit(1)
    return cfg


# ── Aliases ──────────────────────────────────────────────


def load_aliases() -> dict[str, str]:
    if ALIASES_FILE.exists():
        return json.loads(ALIASES_FILE.read_text())
    return {}


def save_aliases(aliases: dict[str, str]):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ALIASES_FILE.write_text(json.dumps(aliases, indent=2))


# ── Last results cache ───────────────────────────────────


def save_last_results(items: list[dict]):
    """Cache list results. Each item needs 'id' and 'name' keys."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cache = {
        "ids": [str(item["id"]) for item in items],
        "names": {item.get("name", "").lower(): str(item["id"]) for item in items if item.get("name")},
    }
    LAST_RESULTS_FILE.write_text(json.dumps(cache))


def load_last_results() -> dict:
    if LAST_RESULTS_FILE.exists():
        data = json.loads(LAST_RESULTS_FILE.read_text())
        # Handle old format (plain list)
        if isinstance(data, list):
            return {"ids": data, "names": {}}
        return data
    return {"ids": [], "names": {}}


# ── Universal resolver ───────────────────────────────────


def resolve_alias(name: str) -> str:
    """Resolve any reference to a UUID: @alias, row number, name, or passthrough UUID."""
    # @alias
    if name.startswith("@"):
        aliases = load_aliases()
        resolved = aliases.get(name[1:])
        if resolved:
            return resolved
        import typer
        from rich import print as rprint

        rprint(f"[red]Unknown alias: {name}[/red]")
        rprint(f"[dim]Set it with: observal config alias {name[1:]} <id>[/dim]")
        raise typer.Exit(1)

    cache = load_last_results()

    # Row number from last list
    if name.isdigit():
        idx = int(name)
        ids = cache.get("ids", [])
        if 1 <= idx <= len(ids):
            return ids[idx - 1]

    # Name match (case-insensitive)
    names = cache.get("names", {})
    resolved = names.get(name.lower())
    if resolved:
        return resolved

    # Partial name match: if exactly one result
    matches = [(n, uid) for n, uid in names.items() if name.lower() in n]
    if len(matches) == 1:
        return matches[0][1]

    return name
