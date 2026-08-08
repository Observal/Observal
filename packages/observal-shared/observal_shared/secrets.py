# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Bounded file-backed secret resolution shared by the CLI and server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_SECRET_BYTES = 64 * 1024


def read_secret_file(path: str | os.PathLike[str], max_bytes: int = MAX_SECRET_BYTES) -> str:
    """Read one UTF-8 secret file, rejecting non-files and oversized values."""
    secret_path = Path(path).expanduser()
    if not secret_path.is_file():
        raise ValueError(f"Secret file is not a regular file: {secret_path}")
    try:
        with secret_path.open("rb") as handle:
            value = handle.read(max_bytes + 1)
    except OSError as exc:
        raise ValueError(f"Cannot read secret file {secret_path}: {exc}") from exc
    if len(value) > max_bytes:
        raise ValueError(f"Secret file exceeds {max_bytes} bytes: {secret_path}")
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Secret file is not valid UTF-8: {secret_path}") from exc
    if text.endswith("\r\n"):
        return text[:-2]
    if text.endswith(("\n", "\r")):
        return text[:-1]
    return text


def resolve_secret(
    name: str,
    environ: Mapping[str, str] | None = None,
    max_bytes: int = MAX_SECRET_BYTES,
) -> str | None:
    """Resolve NAME or NAME_FILE and reject ambiguous configuration."""
    values = os.environ if environ is None else environ
    file_name = f"{name}_FILE"
    has_value = name in values
    has_file = file_name in values
    if has_value and has_file:
        raise ValueError(f"Set only one of {name} and {file_name}")
    if has_file:
        path = values[file_name]
        if not path:
            raise ValueError(f"{file_name} must not be empty")
        return read_secret_file(path, max_bytes=max_bytes)
    return values.get(name) if has_value else None
