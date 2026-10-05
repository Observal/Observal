# SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Public KeyManager behavior when its signing-key store fails at runtime."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import services.crypto as crypto
from services.crypto import KeyManager, KeyStoreUnavailableError


@pytest.fixture
def key_manager(tmp_path: Path) -> KeyManager:
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    manager = KeyManager(key_dir=str(key_dir))
    manager.initialize()
    return manager


def test_corrupt_active_key_fails_sign_and_verify_without_regenerating(key_manager: KeyManager, tmp_path: Path) -> None:
    token = key_manager.sign_token({"sub": "before-corruption"})
    signing_path = tmp_path / "keys" / "signing.pem"
    corrupt_pem = b"not a private key"
    signing_path.write_bytes(corrupt_pem)

    with pytest.raises(KeyStoreUnavailableError):
        key_manager.sign_token({"sub": "must-not-be-signed"})
    with pytest.raises(KeyStoreUnavailableError):
        key_manager.verify_token(token)

    assert signing_path.read_bytes() == corrupt_pem


def test_unreadable_active_key_fails_operationally_without_replacing(
    key_manager: KeyManager, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token = key_manager.sign_token({"sub": "before-read-failure"})
    signing_path = tmp_path / "keys" / "signing.pem"
    original_pem = signing_path.read_bytes()
    original_read_bytes = Path.read_bytes

    def deny_signing_key_read(path: Path) -> bytes:
        if path == signing_path:
            raise PermissionError("simulated unreadable signing key")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", deny_signing_key_read)

    with pytest.raises(KeyStoreUnavailableError):
        key_manager.sign_token({"sub": "must-not-be-signed"})
    with pytest.raises(KeyStoreUnavailableError):
        key_manager.verify_token(token)

    assert original_read_bytes(signing_path) == original_pem


def test_read_only_key_store_disappearance_fails_operationally(tmp_path: Path) -> None:
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    writable = KeyManager(key_dir=str(key_dir))
    writable.initialize()
    read_only = KeyManager(key_dir=str(key_dir), read_only=True)
    read_only.initialize()
    signing_path = key_dir / "signing.pem"
    signing_path.unlink()

    with pytest.raises(KeyStoreUnavailableError):
        read_only.sign_token({"sub": "must-not-be-signed"})
    assert not signing_path.exists()


def test_read_only_key_replacement_requires_restart(tmp_path: Path) -> None:
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    writable = KeyManager(key_dir=str(key_dir))
    writable.initialize()
    read_only = KeyManager(key_dir=str(key_dir), read_only=True)
    read_only.initialize()
    signing_path = key_dir / "signing.pem"
    original_pem = signing_path.read_bytes()

    writable.rotate_key()
    replacement_pem = signing_path.read_bytes()

    assert replacement_pem != original_pem
    with pytest.raises(KeyStoreUnavailableError):
        read_only.get_kid()
    assert signing_path.read_bytes() == replacement_pem


def test_missing_lock_file_is_reported_as_store_unavailable(key_manager: KeyManager, tmp_path: Path) -> None:
    lock_path = tmp_path / "keys" / ".signing.lock"
    lock_path.unlink()

    with pytest.raises(KeyStoreUnavailableError):
        key_manager.sign_token({"sub": "must-not-be-signed"})
    assert not lock_path.exists()


@pytest.mark.skipif(os.name != "posix", reason="Cross-process key-store locking is unavailable")
def test_contended_key_store_lock_fails_within_a_bounded_time(
    key_manager: KeyManager, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import fcntl

    monkeypatch.setattr(crypto, "KEY_STORE_LOCK_TIMEOUT_SECONDS", 0.1, raising=False)
    lock_path = tmp_path / "keys" / ".signing.lock"
    descriptor = os.open(lock_path, os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    executor = ThreadPoolExecutor(max_workers=1)
    started = time.monotonic()
    try:
        pending = executor.submit(key_manager.sign_token, {"sub": "blocked"})
        with pytest.raises(KeyStoreUnavailableError):
            pending.result(timeout=3)
        assert time.monotonic() - started < 3
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        executor.shutdown(wait=True, cancel_futures=True)
