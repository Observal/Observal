# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Download and manage dependency binaries (PostgreSQL, ClickHouse, Redis).

Handles platform-specific downloads, checksum verification, and extraction.
"""

from __future__ import annotations

import hashlib
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TransferSpeedColumn,
)

from observal_cli.server.constants import (
    BIN_DIR,
    DEPS_RELEASE_TAG,
    GITHUB_REPO,
    get_bin_paths,
    get_dep_urls,
)

console = Console()


def _checksum_url() -> str:
    """Get URL for the dependency checksums file."""
    return f"https://github.com/{GITHUB_REPO}/releases/download/{DEPS_RELEASE_TAG}/checksums.txt"


def _download_file(url: str, dest: Path, label: str) -> None:
    """Download a file with progress bar."""
    with (
        Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
        ) as progress,
        httpx.stream("GET", url, follow_redirects=True, timeout=300) as response,
    ):
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        task = progress.add_task(label, total=total or None)

        with dest.open("wb") as f:
            for chunk in response.iter_bytes(chunk_size=65536):
                f.write(chunk)
                progress.update(task, advance=len(chunk))


def _verify_checksum(file_path: Path, expected_checksums: dict[str, str]) -> bool:
    """Verify SHA256 checksum of a downloaded file."""
    filename = file_path.name
    if filename not in expected_checksums:
        console.print(f"[yellow]Warning:[/yellow] No checksum found for {filename}, skipping verification")
        return True

    sha256 = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)

    actual = sha256.hexdigest()
    expected = expected_checksums[filename]

    if actual != expected:
        console.print(f"[red]Checksum mismatch for {filename}![/red]")
        console.print(f"  Expected: {expected}")
        console.print(f"  Got:      {actual}")
        return False

    return True


def _fetch_checksums() -> dict[str, str]:
    """Download and parse the checksums file."""
    url = _checksum_url()
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError:
        console.print("[yellow]Warning:[/yellow] Could not fetch checksums, skipping verification")
        return {}

    checksums = {}
    for line in resp.text.strip().splitlines():
        parts = line.split()
        if len(parts) == 2:
            checksums[parts[1]] = parts[0]
    return checksums


def _extract_tarball(tarball: Path, dest_dir: Path) -> None:
    """Extract a .tar.gz archive to destination directory."""
    with tarfile.open(tarball, "r:gz") as tf:
        tf.extractall(path=dest_dir)


def _make_executable(path: Path) -> None:
    """Make a file executable."""
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def is_installed(service: str) -> bool:
    """Check if a service's binaries are already installed."""
    bins = get_bin_paths()
    if service == "postgres":
        return bins["postgres"].exists() and bins["initdb"].exists()
    elif service == "clickhouse":
        return bins["clickhouse"].exists()
    elif service == "redis":
        return bins["redis_server"].exists()
    return False


def all_installed() -> bool:
    """Check if all dependency binaries are installed."""
    return all(is_installed(svc) for svc in ("postgres", "clickhouse", "redis"))


def install_dependencies(force: bool = False) -> None:
    """Download and install all dependency binaries.

    Args:
        force: Re-download even if already installed.
    """
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    urls = get_dep_urls()
    checksums = _fetch_checksums()

    for service, url in urls.items():
        if not force and is_installed(service):
            console.print(f"[green]\u2713[/green] {service} already installed")
            continue

        console.print(f"[blue]==>[/blue] Downloading {service}...")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            filename = url.rsplit("/", 1)[-1]
            download_path = tmp_path / filename

            _download_file(url, download_path, f"  {service}")

            if checksums and not _verify_checksum(download_path, checksums):
                raise RuntimeError(f"Checksum verification failed for {service}")

            # Extract to a staging dir, then move binaries
            staging = tmp_path / "staging"
            staging.mkdir()
            _extract_tarball(download_path, staging)

            # Move all extracted binaries to BIN_DIR
            for item in staging.rglob("*"):
                if item.is_file():
                    dest = BIN_DIR / item.name
                    shutil.move(str(item), str(dest))
                    _make_executable(dest)

        console.print(f"[green]\u2713[/green] {service} installed")


def install_single(service: str, force: bool = False) -> None:
    """Download and install a single service's binaries.

    Args:
        service: One of "postgres", "clickhouse", "redis".
        force: Re-download even if already installed.
    """
    if not force and is_installed(service):
        console.print(f"[green]\u2713[/green] {service} already installed")
        return

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    urls = get_dep_urls()
    checksums = _fetch_checksums()

    if service not in urls:
        raise ValueError(f"Unknown service: {service}")

    url = urls[service]
    console.print(f"[blue]==>[/blue] Downloading {service}...")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        filename = url.rsplit("/", 1)[-1]
        download_path = tmp_path / filename

        _download_file(url, download_path, f"  {service}")

        if checksums and not _verify_checksum(download_path, checksums):
            raise RuntimeError(f"Checksum verification failed for {service}")

        staging = tmp_path / "staging"
        staging.mkdir()
        _extract_tarball(download_path, staging)

        for item in staging.rglob("*"):
            if item.is_file():
                dest = BIN_DIR / item.name
                shutil.move(str(item), str(dest))
                _make_executable(dest)

    console.print(f"[green]\u2713[/green] {service} installed")
