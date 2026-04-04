import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".observal"
CONFIG_FILE = CONFIG_DIR / "config.json"
ALIASES_FILE = CONFIG_DIR / "aliases.json"
LAST_RESULTS_FILE = CONFIG_DIR / "last_results.json"

DEFAULTS = {
    "output": "table",
    "color": True,
    "server_url": "",
    "api_key": "",
}


def load() -> dict:
    if CONFIG_FILE.exists():
        return {**DEFAULTS, **json.loads(CONFIG_FILE.read_text())}
    return dict(DEFAULTS)


def save(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = load()
    existing.update(data)
    CONFIG_FILE.write_text(json.dumps(existing, indent=2))


def get_or_exit() -> dict:
    cfg = load()
    if not cfg.get("server_url") or not cfg.get("api_key"):
        import typer
        from rich import print as rprint

        rprint("[red]Not configured.[/red] Run [bold]observal init[/bold] or [bold]observal login[/bold] first.")
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
