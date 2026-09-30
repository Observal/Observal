# SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Read plaintext chunks from JSONL files or committed checksummed Zstd frames."""

from __future__ import annotations

import tempfile
from typing import TYPE_CHECKING

import zstandard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_CHUNK = 64 * 1024


def source_chunks(path: Path, *, offset: int = 0, complete: list[bool] | None = None) -> Iterator[bytes]:
    """Yield bounded plaintext chunks, withholding each frame until checksum validation.

    Plain files seek directly to the requested offset. Compressed offsets are
    logical plaintext offsets, handled by the caller after decoding from the start.
    """
    with path.open("rb") as file:
        if not path.name.endswith(".jsonl.zstd"):
            file.seek(offset)
            while chunk := file.read(_CHUNK):
                yield chunk
            return
        size = file.seek(0, 2)
        file.seek(0)
        pending = b""
        while pending or file.tell() < size:
            start = file.tell() - len(pending)
            while len(pending) < 18 and file.tell() < size:
                more = file.read(min(_CHUNK, size - file.tell()))
                if not more:
                    if complete is not None:
                        complete[0] = False
                    return
                pending += more
            if len(pending) < 4:
                if complete is not None:
                    complete[0] = False
                return
            if not pending.startswith(zstandard.FRAME_HEADER):
                raise ValueError(f"corrupt Zstandard session log: invalid frame magic at byte {start}")
            try:
                params = zstandard.get_frame_parameters(pending)
            except zstandard.ZstdError as exc:
                if len(pending) < 18 and "not enough data" in str(exc):
                    if complete is not None:
                        complete[0] = False
                    return
                raise ValueError(f"corrupt Zstandard session log: frame header at byte {start}") from exc
            if not params.has_checksum:
                raise ValueError(f"corrupt Zstandard session log: frame without checksum at byte {start}")
            decoder = zstandard.ZstdDecompressor().decompressobj()
            with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as decoded:
                while not decoder.eof:
                    if not pending:
                        pending = file.read(min(_CHUNK, size - file.tell()))
                        if not pending:
                            if complete is not None:
                                complete[0] = False
                            return
                    try:
                        decoded.write(decoder.decompress(pending))
                    except zstandard.ZstdError as exc:
                        raise ValueError(f"corrupt Zstandard session log: frame at byte {start}") from exc
                    pending = decoder.unused_data if decoder.eof else b""
                decoded.seek(0)
                while chunk := decoded.read(_CHUNK):
                    yield chunk


def source_size(path: Path) -> tuple[int, bool]:
    """Return complete-newline logical bytes and whether the source tail is committed."""
    if not path.name.endswith(".jsonl.zstd"):
        with path.open("rb") as file:
            size = file.seek(0, 2)
            if not size:
                return 0, True
            file.seek(size - 1)
            if file.read(1) == b"\n":
                return size, True
            end = size
            while end:
                start = max(0, end - _CHUNK)
                file.seek(start)
                chunk = file.read(end - start)
                newline = chunk.rfind(b"\n")
                if newline >= 0:
                    return start + newline + 1, False
                end = start
            return 0, False
    complete = [True]
    decoded_bytes = 0
    committed = 0
    for chunk in source_chunks(path, complete=complete):
        newline = chunk.rfind(b"\n")
        if newline >= 0:
            committed = decoded_bytes + newline + 1
        decoded_bytes += len(chunk)
    return committed, complete[0] and committed == decoded_bytes
