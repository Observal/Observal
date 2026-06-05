# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Layer snapshot upload and retrieval endpoint.

Stores full IDE layer manifests (with file contents) keyed by hash.
Used for version-aware insights: enables diffing between two layer states.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger as optic
from pydantic import BaseModel, Field

from api.deps import get_project_id, require_role
from api.ratelimit import limiter
from models.user import User, UserRole

router = APIRouter(prefix="/api/v1/layer-snapshots", tags=["layer-snapshots"])


class LayerFile(BaseModel):
    path: str = Field(..., max_length=500)
    hash: str = Field(..., max_length=100)
    size: int = Field(..., ge=0)
    source: str = Field("user", max_length=20)  # "user" or "observal"
    content: str = Field("", max_length=524288)  # 512KB max per file


_MAX_FILES_PER_SNAPSHOT = 200
_MAX_TOTAL_SIZE = 5 * 1024 * 1024  # 5MB


class LayerSnapshotRequest(BaseModel):
    hash: str = Field(..., min_length=8, max_length=64)
    ides: dict[str, list[LayerFile]] = Field(default_factory=dict)  # {ide_name: [files]}
    lockfile_hash: str = Field("", max_length=64)


class LayerSnapshotResponse(BaseModel):
    stored: bool
    hash: str
    file_count: int


class LayerSnapshotDetail(BaseModel):
    hash: str
    ide: str
    files: list[dict]
    lockfile_hash: str
    uploaded_at: str
    file_count: int
    total_size: int


class LayerDiffResponse(BaseModel):
    added: list[dict]
    removed: list[dict]
    modified: list[dict]
    unchanged_count: int


class BaselinePinRequest(BaseModel):
    agent_id: str = Field(..., max_length=100)
    layer_hash: str = Field(..., min_length=8, max_length=64)


class BaselinePinResponse(BaseModel):
    agent_id: str
    layer_hash: str
    pinned: bool


@router.post("", response_model=LayerSnapshotResponse)
@limiter.limit("10/minute")
async def upload_layer_snapshot(
    req: LayerSnapshotRequest,
    request: Request,
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Upload a layer snapshot (full IDE config state).

    Called by the CLI when layer_hash changes. Idempotent: uploading
    the same hash again is a no-op.
    """
    optic.trace("user_id={}, hash={}", current_user.id, req.hash)
    project_id = get_project_id(current_user)
    user_id = str(current_user.id)

    # Enforce server-side caps (match CLI limits)
    total_files = sum(len(v) for v in req.ides.values())
    if total_files > _MAX_FILES_PER_SNAPSHOT:
        raise HTTPException(
            status_code=422,
            detail=f"Snapshot exceeds {_MAX_FILES_PER_SNAPSHOT} file limit ({total_files} files)",
        )
    total_content_size = sum(len(f.content) for files in req.ides.values() for f in files)
    if total_content_size > _MAX_TOTAL_SIZE:
        raise HTTPException(
            status_code=422,
            detail=f"Snapshot exceeds {_MAX_TOTAL_SIZE // (1024 * 1024)}MB total content limit",
        )

    import json

    # Check if this hash already exists for this project
    from services.clickhouse.client import _query as ch_query
    from services.clickhouse.insert import insert_layer_snapshot

    check_sql = """
        SELECT count() as cnt
        FROM layer_snapshots FINAL
        WHERE project_id = {project_id:String}
          AND hash = {hash:String}
        FORMAT JSON
    """
    try:
        result = await ch_query(
            check_sql,
            {
                "param_project_id": project_id,
                "param_hash": req.hash,
            },
        )
        result.raise_for_status()
        data = result.json().get("data", [])
        if data and int(data[0].get("cnt", 0)) > 0:
            optic.debug("layer snapshot already exists: hash={}", req.hash)
            return LayerSnapshotResponse(
                stored=False,
                hash=req.hash,
                file_count=sum(len(v) for v in req.ides.values()),
            )
    except Exception as e:
        optic.warning("failed to check existing snapshot: {}", e)
        # Proceed with insert anyway (ReplacingMergeTree handles duplicates)

    # Redact secrets from file contents before storage
    from services.secrets_redactor import redact_secrets

    redacted_ides: dict[str, list[dict]] = {}
    total_file_count = 0
    total_size = 0
    for ide_name, files in req.ides.items():
        redacted_files = []
        for f in files:
            fd = f.model_dump()
            if fd.get("content"):
                fd["content"] = redact_secrets(fd["content"])
            redacted_files.append(fd)
            total_size += f.size
            total_file_count += 1
        redacted_ides[ide_name] = redacted_files

    # Serialize the full manifest (with redacted content)
    content_json = json.dumps(
        {
            "ides": redacted_ides,
            "lockfile_hash": req.lockfile_hash,
        }
    )

    row = {
        "hash": req.hash,
        "project_id": project_id,
        "user_id": user_id,
        "ide": ",".join(req.ides.keys()),
        "content": content_json,
        "file_count": total_file_count,
        "total_size": total_size,
        "lockfile_hash": req.lockfile_hash,
    }

    await insert_layer_snapshot(row)

    optic.info(
        "layer snapshot stored: hash={}, files={}, size={}",
        req.hash,
        total_file_count,
        total_size,
    )

    return LayerSnapshotResponse(
        stored=True,
        hash=req.hash,
        file_count=sum(len(v) for v in req.ides.values()),
    )


@router.get("/{snapshot_hash}", response_model=LayerSnapshotDetail)
@limiter.limit("30/minute")
async def get_layer_snapshot(
    snapshot_hash: str,
    request: Request,
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Retrieve a layer snapshot by hash."""
    optic.trace("user_id={}, hash={}", current_user.id, snapshot_hash)
    project_id = get_project_id(current_user)

    from services.clickhouse.client import _query as ch_query

    sql = """
        SELECT hash, ide, content, uploaded_at, file_count, total_size, lockfile_hash
        FROM layer_snapshots FINAL
        WHERE project_id = {project_id:String}
          AND hash = {hash:String}
        LIMIT 1
        FORMAT JSON
    """
    result = await ch_query(
        sql,
        {
            "param_project_id": project_id,
            "param_hash": snapshot_hash,
        },
    )
    result.raise_for_status()
    rows = result.json().get("data", [])

    if not rows:
        raise HTTPException(status_code=404, detail="Layer snapshot not found")

    import json

    row = rows[0]
    content = json.loads(row["content"])

    # Flatten ides structure into a flat file list for the response
    flat_files = []
    ide_names = []
    for ide_name, files in (content.get("ides") or {}).items():
        ide_names.append(ide_name)
        for f in files:
            flat_files.append(f)

    return LayerSnapshotDetail(
        hash=row["hash"],
        ide=",".join(ide_names) if ide_names else row.get("ide", ""),
        files=flat_files,
        lockfile_hash=content.get("lockfile_hash", row.get("lockfile_hash", "")),
        uploaded_at=row.get("uploaded_at", ""),
        file_count=int(row.get("file_count", 0)),
        total_size=int(row.get("total_size", 0)),
    )


@router.get("/{hash_a}/diff/{hash_b}", response_model=LayerDiffResponse)
@limiter.limit("20/minute")
async def diff_layer_snapshots(
    hash_a: str,
    hash_b: str,
    request: Request,
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Diff two layer snapshots to show what changed.

    Returns added, removed, and modified files between snapshot A and B.
    """
    optic.trace("user_id={}, hash_a={}, hash_b={}", current_user.id, hash_a, hash_b)
    project_id = get_project_id(current_user)

    import json

    from services.clickhouse.client import _query as ch_query

    sql = """
        SELECT hash, content
        FROM layer_snapshots FINAL
        WHERE project_id = {project_id:String}
          AND hash IN ({hash_a:String}, {hash_b:String})
        FORMAT JSON
    """
    result = await ch_query(
        sql,
        {
            "param_project_id": project_id,
            "param_hash_a": hash_a,
            "param_hash_b": hash_b,
        },
    )
    result.raise_for_status()
    rows = result.json().get("data", [])

    snapshots = {row["hash"]: json.loads(row["content"]) for row in rows}

    if hash_a not in snapshots:
        raise HTTPException(status_code=404, detail=f"Snapshot {hash_a} not found")
    if hash_b not in snapshots:
        raise HTTPException(status_code=404, detail=f"Snapshot {hash_b} not found")

    # Flatten {ides: {name: [files]}} to {"ide/path": file_dict}
    def _flatten_snapshot(snap: dict) -> dict[str, dict]:
        flat = {}
        for ide_name, files in (snap.get("ides") or {}).items():
            for f in files:
                flat[f"{ide_name}/{f['path']}"] = f
        return flat

    files_a = _flatten_snapshot(snapshots[hash_a])
    files_b = _flatten_snapshot(snapshots[hash_b])

    paths_a = set(files_a.keys())
    paths_b = set(files_b.keys())

    added = [files_b[p] for p in paths_b - paths_a]
    removed = [files_a[p] for p in paths_a - paths_b]
    modified = []
    unchanged = 0

    for path in paths_a & paths_b:
        if files_a[path]["hash"] != files_b[path]["hash"]:
            modified.append(
                {
                    "path": path,
                    "before": files_a[path],
                    "after": files_b[path],
                }
            )
        else:
            unchanged += 1

    return LayerDiffResponse(
        added=added,
        removed=removed,
        modified=modified,
        unchanged_count=unchanged,
    )


@router.post("/baseline", response_model=BaselinePinResponse)
@limiter.limit("10/minute")
async def pin_baseline(
    req: BaselinePinRequest,
    request: Request,
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Pin a layer_hash as the baseline for an agent.

    Used for long-term comparison: all future layer states are
    measured against this baseline in insights.
    """
    optic.trace("user_id={}, agent_id={}, hash={}", current_user.id, req.agent_id, req.layer_hash)
    project_id = get_project_id(current_user)
    user_id = str(current_user.id)

    import json

    from services.clickhouse.client import _query as ch_query

    # Store/update baseline pin (use a dedicated table or settings)
    # For now, store in layer_snapshots with a special marker
    sql = """
        INSERT INTO layer_snapshots (hash, project_id, user_id, ide, content, file_count, total_size, lockfile_hash)
        VALUES (
            {hash:String},
            {project_id:String},
            {user_id:String},
            'baseline',
            {content:String},
            0, 0, ''
        )
    """
    content = json.dumps({"agent_id": req.agent_id, "baseline": True, "pinned_hash": req.layer_hash})

    try:
        await ch_query(
            sql,
            {
                "param_hash": f"baseline:{req.agent_id}",
                "param_project_id": project_id,
                "param_user_id": user_id,
                "param_content": content,
            },
        )
    except Exception as e:
        optic.error("failed to pin baseline: {}", e)
        raise HTTPException(status_code=500, detail="Failed to pin baseline")

    return BaselinePinResponse(
        agent_id=req.agent_id,
        layer_hash=req.layer_hash,
        pinned=True,
    )
