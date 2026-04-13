"""Interactive prompt helpers for constrained fields.

Uses ``questionary`` for arrow-key selection when running in a TTY,
falls back to plain ``typer.prompt`` otherwise (CI, piped input, etc.).
"""

from __future__ import annotations

import sys


def _qstyle():
    """Consistent questionary style with visible selection indicators."""
    from prompt_toolkit.styles import Style

    return Style(
        [
            ("qmark", "fg:green bold"),
            ("question", "bold"),
            ("pointer", "fg:cyan bold"),
            ("highlighted", "fg:cyan bold"),
            ("selected", "fg:green"),
            ("instruction", "fg:ansigray"),
        ]
    )


def select_one(message: str, choices: list[str], default: str | None = None) -> str:
    """Arrow-key single selection. Falls back to typer.prompt in non-interactive mode."""
    if not sys.stdin.isatty():
        import typer

        return typer.prompt(message, default=default or choices[0])

    import questionary

    result = questionary.select(
        message,
        choices=choices,
        default=default,
        style=_qstyle(),
        instruction="(arrow keys, enter to confirm)",
    ).ask()
    if result is None:
        raise KeyboardInterrupt
    return result


def select_many(message: str, choices: list[str], defaults: list[str] | None = None) -> list[str]:
    """Arrow-key multi-selection (checkbox). Falls back to comma-separated input."""
    if not sys.stdin.isatty():
        import typer

        default_str = ",".join(defaults) if defaults else ",".join(choices)
        raw = typer.prompt(message, default=default_str)
        return [x.strip() for x in raw.split(",") if x.strip()]

    import questionary

    result = questionary.checkbox(
        message,
        choices=[questionary.Choice(c, checked=(c in (defaults or []))) for c in choices],
        style=_qstyle(),
        instruction="(space to toggle, enter to confirm)",
        pointer=">",
    ).ask()
    if result is None:
        raise KeyboardInterrupt
    return result
