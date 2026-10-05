# SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Local JWT key-store microbenchmark; no production latency or throughput claims.

Run with the server environment, e.g.:
    observal-server/.venv/bin/python scripts/benchmark_jwt_keys.py

The read-only, pre-provisioned manager is a cached-key baseline. The managed
measurements include shared-file locking and disk refresh. Rotation times also
include key generation, serialization and durable publication. Two spawned
workers measure contention on the same temporary store. No keys or tokens are
printed or persisted outside that store.
"""

from __future__ import annotations

import argparse
import math
import multiprocessing
import os
import statistics
import sys
import tempfile
import time
from functools import partial
from pathlib import Path

import jwt
from loguru import logger as optic


def _server_imports() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "observal-server"))


def _sample(operation, iterations: int) -> list[int]:
    samples = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        operation()
        samples.append(time.perf_counter_ns() - start)
    return samples


def _format(samples: list[int]) -> str:
    ordered = sorted(samples)
    p95 = ordered[math.ceil(len(ordered) * 0.95) - 1]
    return f"median={statistics.median(ordered) / 1_000:.0f}us p95={p95 / 1_000:.0f}us"


def _reject_unknown(manager, token: str) -> None:
    try:
        manager.verify_token(token)
    except jwt.InvalidTokenError:
        return
    raise AssertionError("unknown key ID was accepted")


def _worker(key_dir: str, algorithm: str, iterations: int, rotations: int, barrier, results) -> None:
    optic.remove()
    _server_imports()
    from services.crypto import KeyManager

    try:
        manager = KeyManager(key_dir=key_dir, algorithm=algorithm)
        manager.initialize()
        token = manager.sign_token({"sub": "benchmark"})
        unknown = jwt.encode(
            {"sub": "benchmark"}, manager.get_private_key(), algorithm=algorithm, headers={"kid": "0" * 16}
        )
        barrier.wait(timeout=30)
        sign = _sample(lambda: manager.sign_token({"sub": "benchmark"}), iterations)
        verify = _sample(lambda: manager.verify_token(token), iterations)
        rotate = _sample(manager.rotate_key, rotations)
        retired = _sample(lambda: manager.verify_token(token), iterations)
        unknown_kid = _sample(lambda: _reject_unknown(manager, unknown), iterations)
        results.put({"sign": sign, "verify": verify, "rotate": rotate, "retired": retired, "unknown": unknown_kid})
    except BaseException as exc:
        results.put({"error": repr(exc)})
        raise


def _bench_workers(key_dir: str, algorithm: str, iterations: int, rotations: int, worker_count: int) -> None:
    if os.name == "nt":
        print("  multi-worker: skipped (Windows multi-process coordination unsupported)")
        return

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(worker_count + 1)
    results = context.Queue()
    workers = [
        context.Process(target=_worker, args=(key_dir, algorithm, iterations, rotations, barrier, results))
        for _ in range(worker_count)
    ]
    try:
        for worker in workers:
            worker.start()
        barrier.wait(timeout=30)
        measurements = [results.get(timeout=120) for _ in workers]
        errors = [measurement["error"] for measurement in measurements if "error" in measurement]
        if errors:
            raise RuntimeError(f"JWT benchmark worker failed: {errors}")
        for worker in workers:
            worker.join(timeout=30)
            if worker.exitcode != 0:
                raise RuntimeError(f"JWT benchmark worker did not exit successfully: {worker.exitcode}")
        for label, field in (
            ("managed sign", "sign"),
            ("managed verify", "verify"),
            ("rotations", "rotate"),
            ("retired verify", "retired"),
            ("unknown kid", "unknown"),
        ):
            samples = [value for measurement in measurements for value in measurement[field]]
            print(f"  {worker_count}-worker {label:<16} {_format(samples)}")
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            if worker.pid is not None:
                worker.join(timeout=5)
        results.close()
        results.join_thread()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=200, help="sign/verify samples per worker")
    parser.add_argument("--rotations", type=int, default=4, help="rotation samples per worker")
    parser.add_argument("--workers", type=int, default=2, help="concurrent workers for contention samples")
    args = parser.parse_args()
    if min(args.iterations, args.rotations) < 1 or args.workers < 2:
        parser.error("iterations and rotations must be positive; workers must be at least 2")

    optic.remove()
    _server_imports()
    from services.crypto import KeyManager

    print("Local microbenchmark only; timings include process/filesystem effects, not production estimates.")
    for algorithm in ("ES256", "RS256"):
        with tempfile.TemporaryDirectory(prefix="observal-jwt-bench-") as key_dir:
            managed = KeyManager(key_dir=key_dir, algorithm=algorithm)
            managed.initialize()
            cached = KeyManager(key_dir=key_dir, algorithm=algorithm, read_only=True)
            cached.initialize()
            payload = {"sub": "benchmark"}
            token = cached.sign_token(payload)
            unknown = jwt.encode(payload, cached.get_private_key(), algorithm=algorithm, headers={"kid": "0" * 16})
            print(algorithm)
            print(
                f"  cached sign (no refresh): {_format(_sample(partial(cached.sign_token, payload), args.iterations))}"
            )
            print(
                f"  managed sign:            {_format(_sample(partial(managed.sign_token, payload), args.iterations))}"
            )
            print(
                f"  cached verify:           {_format(_sample(partial(cached.verify_token, token), args.iterations))}"
            )
            print(
                f"  managed verify:          {_format(_sample(partial(managed.verify_token, token), args.iterations))}"
            )
            print(f"  managed rotations:       {_format(_sample(managed.rotate_key, args.rotations))}")
            print(
                f"  retired verification:    {_format(_sample(partial(managed.verify_token, token), args.iterations))}"
            )
            print(
                f"  unknown kid rejection:   {_format(_sample(partial(_reject_unknown, managed, unknown), args.iterations))}"
            )
            _bench_workers(key_dir, algorithm, args.iterations, args.rotations, args.workers)


if __name__ == "__main__":
    main()
