# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Admin data migration routes."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import Depends, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger as optic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import services.dynamic_settings as ds
from api.deps import get_db, require_role
from models.migration_job import MigrationJob, MigrationOperation, MigrationScope, MigrationStatus
from models.user import User, UserRole
from schemas.migration import (
    ArtifactMeta,
    CurrentOrgResponse,
    DownloadTokenResponse,
    MigrationJobResponse,
    StartExportRequest,
)
from services.crypto import sign_token, verify_token
from services.redis import _get_arq_pool
from services.security_events import EventType, SecurityEvent, Severity, emit_security_event

from ._router import router
from .helpers import _get_user_org

# ── Constants ──────────────────────────────────────────────

_DEFAULT_MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB
_DOWNLOAD_TOKEN_TTL_SECONDS = 300  # 5 minutes

# Magic bytes for file validation
_MAGIC_TAR_GZ = b"\x1f\x8b"
_MAGIC_PARQUET = b"PAR1"


# ── Helpers ────────────────────────────────────────────────


async def _check_concurrency(
    db: AsyncSession, operation_type: MigrationOperation, data_scope: MigrationScope, org_id: uuid.UUID | None
) -> None:
    """Reject if a job with same operation+scope+org is already queued/running.

    Uses SELECT ... FOR UPDATE to prevent TOCTOU races between the check and
    the subsequent INSERT in the calling endpoint.
    """
    stmt = (
        select(MigrationJob)
        .where(
            MigrationJob.operation_type == operation_type,
            MigrationJob.data_scope == data_scope,
            MigrationJob.org_id == org_id,
            MigrationJob.status.in_([MigrationStatus.queued, MigrationStatus.running]),
        )
        .with_for_update(skip_locked=True)
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A {operation_type.value} job for scope '{data_scope.value}' is already {existing.status.value}",
        )


async def _validate_upload_files(files: list[UploadFile], scope: MigrationScope) -> None:
    """Validate uploaded files: size limit, magic bytes, scope consistency."""
    max_bytes = await ds.get_int("migration.max_upload_bytes", default=_DEFAULT_MAX_UPLOAD_BYTES)

    has_archive = False
    has_parquet = False

    for f in files:
        # Check file size via content-length header (may be None for chunked uploads)
        if f.size is not None and f.size > max_bytes:
            raise HTTPException(status_code=422, detail=f"File '{f.filename}' exceeds maximum upload size")

        # Read first 4 bytes for magic byte validation
        header = await f.read(4)
        await f.seek(0)

        if len(header) < 2:
            raise HTTPException(status_code=422, detail=f"File '{f.filename}' is too small to validate")

        if header[:2] == _MAGIC_TAR_GZ:
            has_archive = True
        elif header[:4] == _MAGIC_PARQUET:
            has_parquet = True
        else:
            raise HTTPException(
                status_code=422,
                detail=f"File '{f.filename}' has unsupported format (expected .tar.gz or .parquet)",
            )

    # Scope consistency check
    if scope == MigrationScope.postgres and has_parquet and not has_archive:
        raise HTTPException(status_code=422, detail="Scope is 'postgres' but only Parquet files were uploaded")
    if scope == MigrationScope.clickhouse and has_archive and not has_parquet:
        raise HTTPException(status_code=422, detail="Scope is 'clickhouse' but only archive files were uploaded")


async def _store_upload_files(files: list[UploadFile], job_id: uuid.UUID) -> Path:
    """Store uploaded files to the artifact directory with restrictive permissions."""
    # Prefer env var (Docker volume), then dynamic setting, then fallback
    artifact_root = os.environ.get("MIGRATION_ARTIFACT_ROOT")
    if not artifact_root:
        artifact_root = await ds.get(
            "migration.artifact_root", default=str(Path.home() / ".observal" / "migration_artifacts")
        )
    job_dir = Path(artifact_root) / str(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(job_dir, 0o700)

    for f in files:
        # Sanitize filename to prevent path traversal
        raw_name = f.filename or f"upload_{uuid.uuid4().hex[:8]}"
        safe_name = Path(raw_name).name  # strip any directory components
        if not safe_name or safe_name in (".", ".."):
            safe_name = f"upload_{uuid.uuid4().hex[:8]}"
        dest = job_dir / safe_name
        content = await f.read()

        # Enforce size limit for files that didn't have Content-Length at validation time
        max_bytes = await ds.get_int("migration.max_upload_bytes", default=_DEFAULT_MAX_UPLOAD_BYTES)
        if len(content) > max_bytes:
            # Clean up the job directory on size violation
            import shutil

            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(status_code=422, detail=f"File '{safe_name}' exceeds maximum upload size")

        dest.write_bytes(content)
        os.chmod(dest, 0o600)

    return job_dir


def _job_to_response(job: MigrationJob) -> MigrationJobResponse:
    """Convert a MigrationJob ORM instance to the response schema."""
    artifacts = []
    if job.artifacts_json:
        for a in job.artifacts_json:
            artifacts.append(ArtifactMeta(**a))

    return MigrationJobResponse(
        id=str(job.id),
        operation_type=job.operation_type,
        data_scope=job.data_scope,
        status=job.status,
        progress_phase=job.progress_phase,
        progress_pct=job.progress_pct,
        progress_message=job.progress_message,
        error_message=job.error_message,
        created_at=job.created_at,
        finished_at=job.finished_at,
        artifacts=artifacts,
        result=job.result_json,
        schema_version=job.schema_version,
    )


# ── Start Endpoints ───────────────────────────────────────


@router.post("/migrate/export", status_code=202)
async def start_export(
    body: StartExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.super_admin)),
):
    """Start a data export job."""
    optic.debug("migration export requested scope={}", body.scope.value)

    # Reject clickhouse-only scope (Req 3.9)
    if body.scope == MigrationScope.clickhouse:
        raise HTTPException(
            status_code=422,
            detail="Standalone ClickHouse export is not supported; use 'both' or 'postgres'",
        )

    org = await _get_user_org(db, current_user)
    org_id = org.id

    await _check_concurrency(db, MigrationOperation.export, body.scope, org_id)

    job = MigrationJob(
        operation_type=MigrationOperation.export,
        data_scope=body.scope,
        status=MigrationStatus.queued,
        progress_phase="queued",
        progress_message="Export queued",
        created_by=current_user.id,
        org_id=org_id,
    )
    db.add(job)
    await db.flush()

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(job.id),
            target_type="migration_job",
            detail=f"Migration export started (scope={body.scope.value})",
            org_id=str(org_id),
        )
    )

    pool = await _get_arq_pool()
    await pool.enqueue_job("run_migration_job", str(job.id))
    await db.commit()

    return {"job_id": str(job.id)}


@router.post("/migrate/import", status_code=202)
async def start_import(
    files: list[UploadFile],
    scope: MigrationScope = MigrationScope.both,
    org_id: str | None = None,
    project_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.super_admin)),
):
    """Start a data import job with uploaded artifacts."""
    optic.debug("migration import requested scope={}", scope.value)

    await _validate_upload_files(files, scope)

    user_org = await _get_user_org(db, current_user)
    effective_org_id = user_org.id

    await _check_concurrency(db, MigrationOperation.import_, scope, effective_org_id)

    job = MigrationJob(
        operation_type=MigrationOperation.import_,
        data_scope=scope,
        status=MigrationStatus.queued,
        progress_phase="queued",
        progress_message="Import queued",
        created_by=current_user.id,
        org_id=effective_org_id,
    )
    db.add(job)
    await db.flush()

    # Store uploaded files
    job_dir = await _store_upload_files(files, job.id)
    job.artifact_dir = str(job_dir)

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(job.id),
            target_type="migration_job",
            detail=f"Migration import started (scope={scope.value}, files={len(files)})",
            org_id=str(effective_org_id),
        )
    )

    pool = await _get_arq_pool()
    await pool.enqueue_job("run_migration_job", str(job.id))
    await db.commit()

    return {"job_id": str(job.id)}


@router.post("/migrate/validate", status_code=202)
async def start_validate(
    files: list[UploadFile],
    scope: MigrationScope = MigrationScope.both,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.super_admin)),
):
    """Start a data validation job with uploaded artifacts."""
    optic.debug("migration validate requested scope={}", scope.value)

    await _validate_upload_files(files, scope)

    org = await _get_user_org(db, current_user)
    org_id = org.id

    await _check_concurrency(db, MigrationOperation.validate, scope, org_id)

    job = MigrationJob(
        operation_type=MigrationOperation.validate,
        data_scope=scope,
        status=MigrationStatus.queued,
        progress_phase="queued",
        progress_message="Validation queued",
        created_by=current_user.id,
        org_id=org_id,
    )
    db.add(job)
    await db.flush()

    # Store uploaded files
    job_dir = await _store_upload_files(files, job.id)
    job.artifact_dir = str(job_dir)

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(job.id),
            target_type="migration_job",
            detail=f"Migration validate started (scope={scope.value}, files={len(files)})",
            org_id=str(org_id),
        )
    )

    pool = await _get_arq_pool()
    await pool.enqueue_job("run_migration_job", str(job.id))
    await db.commit()

    return {"job_id": str(job.id)}


# ── Status + Download Endpoints ───────────────────────────


@router.get("/migrate/jobs/{job_id}")
async def get_migration_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.super_admin)),
) -> MigrationJobResponse:
    """Get a specific migration job by ID."""
    try:
        uid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid job ID format")

    job = (await db.execute(select(MigrationJob).where(MigrationJob.id == uid))).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Migration job not found")

    return _job_to_response(job)


@router.get("/migrate/jobs")
async def list_migration_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.super_admin)),
) -> list[MigrationJobResponse]:
    """List migration jobs with pagination."""
    stmt = select(MigrationJob).order_by(MigrationJob.created_at.desc()).limit(limit).offset(offset)
    jobs = (await db.execute(stmt)).scalars().all()
    return [_job_to_response(j) for j in jobs]


@router.post("/migrate/jobs/{job_id}/artifacts/{name}/token")
async def create_artifact_download_token(
    job_id: str,
    name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.super_admin)),
) -> DownloadTokenResponse:
    """Mint a short-lived download token for a migration artifact."""
    try:
        uid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid job ID format")

    job = (await db.execute(select(MigrationJob).where(MigrationJob.id == uid))).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Migration job not found")

    # Verify artifact exists in metadata
    if not job.artifacts_json:
        raise HTTPException(status_code=404, detail="No artifacts available for this job")

    artifact_names = [a["name"] for a in job.artifacts_json]
    if name not in artifact_names:
        raise HTTPException(status_code=404, detail=f"Artifact '{name}' not found")

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=_DOWNLOAD_TOKEN_TTL_SECONDS)

    token = sign_token(
        {
            "typ": "migration_artifact",
            "job_id": str(uid),
            "artifact": name,
            "sub": str(current_user.id),
            "exp": int(expires_at.timestamp()),
        }
    )

    return DownloadTokenResponse(token=token, expires_at=expires_at)


@router.get("/migrate/download")
async def download_artifact(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Download a migration artifact using a signed token."""
    import time as _time

    try:
        claims = verify_token(token)
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid or expired download token")

    if claims.get("typ") != "migration_artifact":
        raise HTTPException(status_code=403, detail="Invalid token type")

    # Explicitly check token expiration (defense-in-depth: the JWT library
    # may or may not enforce exp depending on PyJWT availability)
    exp = claims.get("exp")
    if exp is None or _time.time() > float(exp):
        raise HTTPException(status_code=403, detail="Download token has expired")

    job_id = claims.get("job_id")
    artifact_name = claims.get("artifact")
    user_id = claims.get("sub")

    if not job_id or not artifact_name:
        raise HTTPException(status_code=403, detail="Malformed token")

    try:
        uid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid token")

    job = (await db.execute(select(MigrationJob).where(MigrationJob.id == uid))).scalar_one_or_none()
    if not job or not job.artifact_dir:
        raise HTTPException(status_code=404, detail="Artifact not found or purged")

    # Path traversal protection: keep CodeQL-visible normalization and
    # prefix validation before touching the filesystem.
    artifact_dir = os.path.realpath(job.artifact_dir)
    artifact_path = os.path.realpath(os.path.join(artifact_dir, str(artifact_name)))
    artifact_dir_prefix = artifact_dir + os.sep
    if artifact_path != artifact_dir and not artifact_path.startswith(artifact_dir_prefix):
        raise HTTPException(status_code=403, detail="Invalid artifact name")

    if not os.path.isfile(artifact_path):
        raise HTTPException(status_code=404, detail="Artifact file not found (may have been purged)")

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.INFO,
            outcome="success",
            actor_id=user_id or "",
            target_id=str(uid),
            target_type="migration_artifact",
            detail=f"Artifact downloaded: {artifact_name}",
        )
    )

    def _stream():
        with open(artifact_path, "rb") as fh:
            while chunk := fh.read(64 * 1024):
                yield chunk

    return StreamingResponse(
        _stream(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{os.path.basename(artifact_path)}"'},
    )


@router.get("/migrate/current-org")
async def get_current_org(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.super_admin)),
) -> CurrentOrgResponse:
    """Return the current org_id and project_id for pre-filling import fields."""
    org = await _get_user_org(db, current_user)
    return CurrentOrgResponse(org_id=str(org.id), project_id=str(org.id))
