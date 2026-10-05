# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-License-Identifier: Apache-2.0

"""Public-interface regressions for JWT key retention and JWKS freshness."""

from __future__ import annotations

import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING
from unittest.mock import patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization

from services.crypto import KeyManager

if TYPE_CHECKING:
    from multiprocessing.queues import Queue
    from multiprocessing.synchronize import Barrier, Event
    from pathlib import Path


def _prune_after_barrier_worker(
    key_dir: str,
    ready_queue: Queue,
    start_event: Event,
    barrier: Barrier,
    expired_now: float,
) -> None:
    manager = KeyManager(key_dir=key_dir, retired_key_retention_days=1)
    manager.initialize()
    ready_queue.put(True)
    if not start_event.wait(timeout=30):
        raise TimeoutError("cleanup worker was not released")
    with patch("services.crypto.time.time", return_value=expired_now):
        barrier.wait(timeout=30)
        manager.initialize()


def _observe_after_barrier(manager: KeyManager, barrier: Barrier) -> dict:
    barrier.wait(timeout=30)
    return manager.get_jwks()


def test_active_key_is_not_duplicated_by_a_retired_record(tmp_path: Path) -> None:
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    manager = KeyManager(key_dir=str(key_dir))
    manager.initialize()
    active_kid = manager.get_kid()
    active_public_pem = manager.get_public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    (key_dir / f"retired_{active_kid}.pem").write_bytes(active_public_pem)

    kids = [key["kid"] for key in manager.get_jwks()["keys"]]

    assert kids == [active_kid]


@pytest.mark.skipif(os.name == "nt", reason="Windows multi-process key-store coordination is unsupported")
def test_expired_retired_key_is_excluded_after_another_worker_prunes_it(tmp_path: Path) -> None:
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    observer = KeyManager(key_dir=str(key_dir), retired_key_retention_days=1)
    cleaner = KeyManager(key_dir=str(key_dir), retired_key_retention_days=1)
    observer.initialize()
    cleaner.initialize()

    retired_kid = observer.get_kid()
    retained_token = observer.sign_token({"sub": "retained", "exp": int(time.time()) + 10 * 86400})
    observer.rotate_key()
    retired_path = key_dir / f"retired_{retired_kid}.pem"
    retired_at = retired_path.stat().st_mtime
    assert observer.verify_token(retained_token)["sub"] == "retained"

    # Start another worker while the retired key is still eligible. It will wait
    # until the parent expires the record before racing cleanup against a read.
    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    start_event = context.Event()
    barrier = context.Barrier(2)
    worker = context.Process(
        target=_prune_after_barrier_worker,
        args=(str(key_dir), ready_queue, start_event, barrier, retired_at + 2 * 86400),
    )
    try:
        worker.start()
        assert ready_queue.get(timeout=30) is True

        expired_now = retired_at + 2 * 86400
        with patch("services.crypto.time.time", return_value=expired_now):
            # An observation excludes expired material but leaves coordinated cleanup to a writer.
            cleaner_keys = cleaner.get_jwks()["keys"]
            assert retired_kid not in {key["kid"] for key in cleaner_keys}
            assert retired_path.exists()

            # Race a public-key observation against another process performing cleanup.
            start_event.set()
            with ThreadPoolExecutor(max_workers=1) as pool:
                concurrent_keys = pool.submit(_observe_after_barrier, cleaner, barrier).result(timeout=30)["keys"]
            worker.join(timeout=30)
            assert not worker.is_alive(), "cleanup worker did not exit"
            assert worker.exitcode == 0
    finally:
        start_event.set()
        if worker.is_alive():
            worker.terminate()
        if worker.pid is not None:
            worker.join(timeout=5)
        ready_queue.close()
        ready_queue.join_thread()

    assert not retired_path.exists()
    assert retired_kid not in {key["kid"] for key in concurrent_keys}
    with patch("services.crypto.time.time", return_value=retired_at + 2 * 86400):
        # The observer's first post-expiry lookup happens after the peer has pruned the file.
        assert observer.find_public_key(retired_kid) is None
        assert retired_kid not in {key["kid"] for key in observer.get_jwks()["keys"]}
        with pytest.raises(pyjwt.InvalidTokenError, match="Unknown key id"):
            observer.verify_token(retained_token)
    expired_token = observer.sign_token({"sub": "jwt-expired", "exp": int(time.time()) - 1})
    with pytest.raises(pyjwt.ExpiredSignatureError):
        observer.verify_token(expired_token)
