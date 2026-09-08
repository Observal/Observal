# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Shared resource limits and safe I/O for package discovery providers."""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from observal_cli.discovery.models import (
    DiagnosticCode,
    DiagnosticSeverity,
    DiscoveryEvidence,
    ProviderResult,
)
from observal_cli.discovery.redact import is_secret_value, make_diagnostic
from observal_cli.discovery.serialize import privacy_safe_path

if TYPE_CHECKING:
    from pathlib import Path
    from subprocess import Popen

SUBPROCESS_TIMEOUT_SECONDS = 5.0
PROVIDER_DEADLINE_SECONDS = 15.0
MAX_CAPTURED_OUTPUT_BYTES = 1024 * 1024
MAX_METADATA_FILE_BYTES = 1024 * 1024
MAX_PROVIDER_RECORDS = 2_000
MAX_METADATA_DEPTH = 3

_PORTABLE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PORTABLE_VERSION_RE = re.compile(r"^[0-9][A-Za-z0-9.!+_-]*$")


def safe_python_package_name(value: object) -> str | None:
    if not isinstance(value, str) or not _PORTABLE_NAME_RE.fullmatch(value) or is_secret_value(value):
        return None
    from observal_cli.discovery.normalize import canonicalize_python_package_name

    return canonicalize_python_package_name(value)


def safe_executable_name(value: object) -> str | None:
    if not isinstance(value, str) or not _PORTABLE_NAME_RE.fullmatch(value) or is_secret_value(value):
        return None
    return value


def safe_version(value: object) -> str | None:
    rendered = str(value) if isinstance(value, (str, int, float)) else ""
    return rendered if _PORTABLE_VERSION_RE.fullmatch(rendered) and not is_secret_value(rendered) else None


@dataclass(frozen=True)
class CommandOutput:
    stdout: bytes
    stderr: bytes = b""
    returncode: int = 0
    oversized: bool = False


CommandRunner = Callable[[Sequence[str], float], CommandOutput]


def _bounded_reader(stream, chunks: list[bytes], state: dict[str, int | bool], lock: threading.Lock) -> None:
    while block := stream.read(64 * 1024):
        with lock:
            remaining = MAX_CAPTURED_OUTPUT_BYTES + 1 - int(state["size"])
            if remaining > 0:
                chunks.append(block[:remaining])
                state["size"] = int(state["size"]) + min(len(block), remaining)
            if len(block) > remaining:
                state["oversized"] = True


def run_bounded(command: Sequence[str], timeout: float) -> CommandOutput:
    """Run an argument-array command while bounding memory used for output."""

    if not command or not (executable := shutil.which(command[0])):
        raise FileNotFoundError(command[0] if command else "")
    resolved_command = [executable, *command[1:]]
    process: Popen[bytes] = subprocess.Popen(
        resolved_command,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    state: dict[str, int | bool] = {"size": 0, "oversized": False}
    lock = threading.Lock()
    threads = [
        threading.Thread(target=_bounded_reader, args=(process.stdout, stdout_chunks, state, lock), daemon=True),
        threading.Thread(target=_bounded_reader, args=(process.stderr, stderr_chunks, state, lock), daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise
    finally:
        for thread in threads:
            thread.join(timeout=1)
    return CommandOutput(
        stdout=b"".join(stdout_chunks),
        stderr=b"".join(stderr_chunks),
        returncode=returncode,
        oversized=bool(state["oversized"]),
    )


@dataclass
class ProviderContext:
    provider: str
    home: Path | None = None
    runner: CommandRunner = run_bounded
    clock: Callable[[], float] = time.monotonic
    deadline_seconds: float = PROVIDER_DEADLINE_SECONDS
    max_records: int = MAX_PROVIDER_RECORDS
    result: ProviderResult = field(default_factory=ProviderResult)
    deadline: float = field(init=False)
    _records: int = 0
    _limit_codes: set[DiagnosticCode] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.deadline = self.clock() + self.deadline_seconds

    def diagnostic(
        self,
        code: DiagnosticCode,
        message: str,
        *,
        source: Path | str | None = None,
        severity: DiagnosticSeverity = DiagnosticSeverity.WARNING,
        once: bool = False,
    ) -> None:
        if once and code in self._limit_codes:
            return
        if once:
            self._limit_codes.add(code)
        self.result.diagnostics.append(
            make_diagnostic(
                code=code,
                severity=severity,
                provider=self.provider,
                source=source,
                message=message,
            )
        )

    def check_deadline(self) -> bool:
        if self.clock() <= self.deadline:
            return True
        self.diagnostic(
            DiagnosticCode.ADAPTER_DEADLINE_EXCEEDED,
            "provider discovery deadline exceeded",
            once=True,
        )
        return False

    def command(self, command: Sequence[str]) -> str | None:
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            self.diagnostic(
                DiagnosticCode.ADAPTER_DEADLINE_EXCEEDED,
                "provider discovery deadline exceeded",
                once=True,
            )
            return None
        try:
            output = self.runner(command, min(SUBPROCESS_TIMEOUT_SECONDS, remaining))
        except FileNotFoundError:
            self.diagnostic(DiagnosticCode.EXECUTABLE_MISSING, "provider executable is unavailable", once=True)
            return None
        except subprocess.TimeoutExpired:
            self.diagnostic(DiagnosticCode.SUBPROCESS_TIMEOUT, "provider command timed out", once=True)
            return None
        except OSError:
            self.diagnostic(DiagnosticCode.SUBPROCESS_FAILED, "provider command could not be executed")
            return None
        if output.oversized or len(output.stdout) + len(output.stderr) > MAX_CAPTURED_OUTPUT_BYTES:
            self.diagnostic(
                DiagnosticCode.OUTPUT_TOO_LARGE, "provider command output exceeded the size limit", once=True
            )
            return None
        if output.returncode != 0:
            self.diagnostic(DiagnosticCode.SUBPROCESS_FAILED, "provider command failed")
            return None
        return output.stdout.decode("utf-8", errors="replace")

    def start_record(self) -> bool:
        if self._records >= self.max_records:
            self.diagnostic(DiagnosticCode.ITEM_LIMIT_REACHED, "provider item limit reached", once=True)
            return False
        if self.clock() > self.deadline:
            self.diagnostic(
                DiagnosticCode.ADAPTER_DEADLINE_EXCEEDED,
                "provider discovery deadline exceeded",
                once=True,
            )
            return False
        self._records += 1
        return True

    def add(self, evidence: DiscoveryEvidence) -> bool:
        if self.clock() > self.deadline:
            self.diagnostic(
                DiagnosticCode.ADAPTER_DEADLINE_EXCEEDED,
                "provider discovery deadline exceeded",
                once=True,
            )
            return False
        self.result.evidence.append(evidence)
        return True

    def read_metadata(self, root: Path, path: Path) -> str | None:
        """Read a bounded metadata file contained within an approved root."""

        if not self.check_deadline():
            return None
        try:
            resolved_root = root.expanduser().resolve(strict=True)
            resolved = path.expanduser().resolve(strict=True)
            relative = resolved.relative_to(resolved_root)
        except FileNotFoundError:
            return None
        except PermissionError:
            self.diagnostic(DiagnosticCode.PERMISSION_DENIED, "metadata path is not readable", source=path)
            return None
        except ValueError:
            code = DiagnosticCode.SYMLINK_ESCAPE if path.is_symlink() else DiagnosticCode.PATH_OUTSIDE_ROOT
            self.diagnostic(code, "metadata path resolves outside the approved root", source=path)
            return None
        except OSError:
            self.diagnostic(DiagnosticCode.METADATA_MALFORMED, "metadata path could not be resolved", source=path)
            return None
        if len(relative.parts) > MAX_METADATA_DEPTH:
            self.diagnostic(
                DiagnosticCode.RECURSION_LIMIT_REACHED,
                "provider metadata depth limit reached",
                source=path,
                once=True,
            )
            return None
        try:
            if not resolved.is_file():
                return None
            size = resolved.stat().st_size
            if size > MAX_METADATA_FILE_BYTES:
                self.diagnostic(DiagnosticCode.METADATA_TOO_LARGE, "metadata file exceeded the size limit", source=path)
                return None
            return resolved.read_bytes().decode("utf-8", errors="replace")
        except PermissionError:
            self.diagnostic(DiagnosticCode.PERMISSION_DENIED, "metadata file is not readable", source=path)
        except OSError:
            self.diagnostic(DiagnosticCode.METADATA_MALFORMED, "metadata file could not be read", source=path)
        return None

    def display_path(self, path: Path) -> str:
        return privacy_safe_path(path, home=self.home)


def sorted_children(root: Path, context: ProviderContext) -> list[Path]:
    if not context.check_deadline():
        return []
    try:
        return sorted(root.iterdir(), key=lambda path: path.name.casefold())
    except PermissionError:
        context.diagnostic(DiagnosticCode.PERMISSION_DENIED, "provider root is not readable", source=root)
    except OSError:
        context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "provider root could not be inspected", source=root)
    return []


def contained_directory(root: Path, candidate: Path, context: ProviderContext) -> Path | None:
    if not context.check_deadline():
        return None
    try:
        resolved_root = root.expanduser().resolve(strict=True)
        resolved = candidate.expanduser().resolve(strict=True)
        resolved.relative_to(resolved_root)
    except FileNotFoundError:
        return None
    except PermissionError:
        context.diagnostic(DiagnosticCode.PERMISSION_DENIED, "package path is not readable", source=candidate)
        return None
    except ValueError:
        code = DiagnosticCode.SYMLINK_ESCAPE if candidate.is_symlink() else DiagnosticCode.PATH_OUTSIDE_ROOT
        context.diagnostic(code, "package path resolves outside the approved root", source=candidate)
        return None
    except OSError:
        context.diagnostic(DiagnosticCode.METADATA_MALFORMED, "package path could not be resolved", source=candidate)
        return None
    return resolved if resolved.is_dir() else None
