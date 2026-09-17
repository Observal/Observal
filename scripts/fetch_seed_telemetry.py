#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Copy telemetry from a source Observal instance into a target one.

Both instances must run the DuckDB analytics store. The script drives the
super-admin migration API end to end:

  source: start a telemetry export job -> poll it -> download the signed artifact
  target: upload that same artifact as a telemetry import job -> poll it

Usage:

  python scripts/fetch_seed_telemetry.py \
      --source-url https://internal.observal.io \
      --source-email you@example.com \
      --target-url http://localhost \
      --target-email super@demo.example \
      --out .seed-telemetry

Passwords come from --source-password/--target-password or from
SOURCE_PASSWORD/TARGET_PASSWORD. On a stack where TLS is not the answer, pass
--insecure. Nothing is written outside --out.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

POLL_INTERVAL_SECONDS = 3.0
POLL_TIMEOUT_SECONDS = 60 * 60


class ScriptError(RuntimeError):
    """A failure that should end the run with a message, not a traceback."""


def _ssl_context(insecure: bool) -> ssl.SSLContext:
    if insecure:
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json_body: dict | None = None,
    raw_body: bytes | None = None,
    content_type: str | None = None,
    context: ssl.SSLContext | None = None,
) -> tuple[int, bytes, dict]:
    data = None
    headers: dict[str, str] = {"Accept": "application/json"}
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif raw_body is not None:
        data = raw_body
        if content_type:
            headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, context=context, timeout=120) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        raise ScriptError(f"{method} {url} failed: HTTP {exc.code} {body[:400].decode(errors='replace')}") from exc
    except urllib.error.URLError as exc:
        raise ScriptError(f"{method} {url} failed: {exc.reason}") from exc


def login(base_url: str, email: str, password: str, context: ssl.SSLContext) -> str:
    status, body, _ = _request(
        "POST",
        f"{base_url.rstrip('/')}/api/v1/auth/login",
        json_body={"email": email, "password": password},
        context=context,
    )
    if status != 200:
        raise ScriptError(f"login failed: HTTP {status}")
    token = json.loads(body).get("access_token")
    if not token:
        raise ScriptError("login response carried no access_token")
    return token


def detect_backend(base_url: str, context: ssl.SSLContext) -> str:
    """Report whether the instance still stores telemetry in ClickHouse.

    Older builds answer /health with a ``clickhouse`` key; DuckDB builds answer
    with ``analytics``. The difference matters because old builds reject a
    telemetry-only export, so the request has to ask for both scopes.
    """
    try:
        _, body, _ = _request("GET", f"{base_url.rstrip('/')}/health", context=context)
        health = json.loads(body)
    except (ScriptError, json.JSONDecodeError) as error:
        raise ScriptError(f"could not read {base_url.rstrip('/')}/health: {error}") from error
    if "analytics" in health:
        return "duckdb"
    if "clickhouse" in health:
        return "clickhouse"
    raise ScriptError(f"unrecognised /health payload: {json.dumps(health)[:200]}")


def start_export(base_url: str, token: str, scope: str, context: ssl.SSLContext) -> str:
    _, body, _ = _request(
        "POST",
        f"{base_url.rstrip('/')}/api/v1/admin/migrate/export",
        token=token,
        json_body={"scope": scope},
        context=context,
    )
    job_id = json.loads(body).get("job_id")
    if not job_id:
        raise ScriptError("export request returned no job_id")
    return job_id


def job_state(base_url: str, token: str, job_id: str, context: ssl.SSLContext) -> dict:
    _, body, _ = _request(
        "GET",
        f"{base_url.rstrip('/')}/api/v1/admin/migrate/jobs/{job_id}",
        token=token,
        context=context,
    )
    return json.loads(body)


def wait_for_job(base_url: str, token: str, job_id: str, context: ssl.SSLContext, label: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    last_line = ""
    while True:
        job = job_state(base_url, token, job_id, context)
        status = job.get("status")
        line = f"  {label} {job.get('progress_phase') or status} {job.get('progress_pct') or 0}%"
        if line != last_line:
            print(line, flush=True)
            last_line = line
        if status == "completed":
            return job
        if status == "failed":
            raise ScriptError(f"{label} job failed: {job.get('error_message')}")
        if time.monotonic() > deadline:
            raise ScriptError(f"{label} job {job_id} did not finish within {POLL_TIMEOUT_SECONDS // 60} minutes")
        time.sleep(POLL_INTERVAL_SECONDS)


def download_artifacts(base_url: str, token: str, job: dict, out_dir: Path, context: ssl.SSLContext) -> list[Path]:
    artifacts = job.get("artifacts") or []
    if not artifacts:
        raise ScriptError("export job completed without artifacts")

    written: list[Path] = []
    for artifact in artifacts:
        name = artifact["name"]
        # The name comes from the source instance's job metadata, so it is
        # sanitized before being joined onto --out.
        safe_name = Path(name).name
        if not safe_name or safe_name in (".", ".."):
            raise ScriptError(f"unsafe artifact name from source: {name!r}")
        _, body, _ = _request(
            "POST",
            f"{base_url.rstrip('/')}/api/v1/admin/migrate/jobs/{job['id']}/artifacts/{urllib.parse.quote(name)}/token",
            token=token,
            context=context,
        )
        download_token = json.loads(body)["token"]
        _, payload, _ = _request(
            "GET",
            f"{base_url.rstrip('/')}/api/v1/admin/migrate/download?token={urllib.parse.quote(download_token)}",
            context=context,
        )
        digest = hashlib.sha256(payload).hexdigest()
        if artifact.get("sha256") and digest != artifact["sha256"]:
            raise ScriptError(f"{name}: checksum mismatch (expected {artifact['sha256']}, got {digest})")
        destination = out_dir / safe_name
        destination.write_bytes(payload)
        size_mb = len(payload) / (1024 * 1024)
        print(f"  downloaded {safe_name} ({size_mb:.1f} MiB, sha256 verified)", flush=True)
        written.append(destination)
    return written


def start_import(base_url: str, token: str, scope: str, files: list[Path], context: ssl.SSLContext) -> str:
    boundary = "----observal-seed-boundary"
    chunks: list[bytes] = []
    chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="scope"\r\n\r\n{scope}\r\n').encode())
    for path in files:
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="files"; filename="{path.name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
        )
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    payload = b"".join(chunks)

    _, body, _ = _request(
        "POST",
        f"{base_url.rstrip('/')}/api/v1/admin/migrate/import",
        token=token,
        raw_body=payload,
        content_type=f"multipart/form-data; boundary={boundary}",
        context=context,
    )
    job_id = json.loads(body).get("job_id")
    if not job_id:
        raise ScriptError("import request returned no job_id")
    return job_id


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-url", default=os.environ.get("SOURCE_URL", "https://internal.observal.io"))
    parser.add_argument("--source-email", default=os.environ.get("SOURCE_EMAIL"))
    parser.add_argument("--source-password", default=os.environ.get("SOURCE_PASSWORD"))
    parser.add_argument(
        "--source-token", default=os.environ.get("SOURCE_TOKEN"), help="use a JWT instead of a password"
    )
    parser.add_argument("--target-url", default=os.environ.get("TARGET_URL"))
    parser.add_argument("--target-email", default=os.environ.get("TARGET_EMAIL"))
    parser.add_argument("--target-password", default=os.environ.get("TARGET_PASSWORD"))
    parser.add_argument("--target-token", default=os.environ.get("TARGET_TOKEN"))
    parser.add_argument(
        "--scope",
        default="auto",
        choices=["auto", "telemetry", "both"],
        help=(
            "export scope on the source; 'auto' picks telemetry for DuckDB sources and both for ClickHouse "
            "sources (a registry-only export carries no telemetry to import, so it is not offered)"
        ),
    )
    parser.add_argument(
        "--include-registry",
        action="store_true",
        help="also import the PostgreSQL archive (only present when the export scope includes registry data)",
    )
    parser.add_argument("--out", default=".seed-telemetry", help="directory for downloaded artifacts")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification for self-signed stacks")
    parser.add_argument(
        "--keep-jobs",
        action="store_true",
        help="accepted for symmetry: jobs are always retained (artifacts are purged by the maintenance cron)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if not args.source_token and not (args.source_email and args.source_password):
        raise ScriptError("source credentials are required (--source-token or --source-email/--source-password)")
    if not args.target_url:
        raise ScriptError("target credentials are required (--target-url)")
    if not args.target_token and not (args.target_email and args.target_password):
        raise ScriptError("target credentials are required (--target-token or --target-email/--target-password)")

    context = _ssl_context(args.insecure)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    backend = detect_backend(args.source_url, context)
    scope = args.scope
    if scope == "auto":
        # Old ClickHouse builds reject a telemetry-only export, so ask for both
        # and import just the telemetry archive.
        scope = "both" if backend == "clickhouse" else "telemetry"

    print(f"source: {args.source_url} (analytics backend: {backend}, export scope: {scope})")
    source_token = args.source_token or login(args.source_url, args.source_email, args.source_password, context)
    export_job = start_export(args.source_url, source_token, scope, context)
    print(f"  export job {export_job} queued")
    completed = wait_for_job(args.source_url, source_token, export_job, context, "export")
    files = download_artifacts(args.source_url, source_token, completed, out_dir, context)

    telemetry_files = [path for path in files if path.name.startswith("telemetry")]
    registry_files = [path for path in files if not path.name.startswith("telemetry")]
    if not telemetry_files:
        raise ScriptError("the export produced no telemetry archive")
    if registry_files and not args.include_registry:
        print(f"  skipping {len(registry_files)} registry artifact(s); pass --include-registry to import them")
    upload = telemetry_files + (registry_files if args.include_registry else [])
    target_scope = "both" if registry_files and args.include_registry else "telemetry"

    print(f"target: {args.target_url}")
    target_token = args.target_token or login(args.target_url, args.target_email, args.target_password, context)
    import_job = start_import(args.target_url, target_token, target_scope, upload, context)
    print(f"  import job {import_job} queued")
    imported = wait_for_job(args.target_url, target_token, import_job, context, "import")

    if not args.keep_jobs:
        print("  (delete the finished jobs from Admin -> Data Migration when the data is verified)")
    print(json.dumps(imported.get("result") or {}, indent=2, sort_keys=True))
    print(f"done: {len(upload)} of {len(files)} artifact(s) imported from {out_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ScriptError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
