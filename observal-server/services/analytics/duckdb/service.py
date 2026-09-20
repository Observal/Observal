# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""HTTP SQL service in front of the DuckDB analytics store.

This is the only process that writes ``DUCKDB_PATH``.  Every other Observal
service reaches analytics through this HTTP interface.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger as optic
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings
from starlette.background import BackgroundTask

from services.analytics.duckdb.migrations import run_migrations
from services.analytics.duckdb.storage import AnalyticsStore


class ServiceSettings(BaseSettings):
    """Boot-time settings for the DuckDB service container."""

    DUCKDB_PATH: str = "/data/analytics.duckdb"
    DUCKDB_ANALYTICS_TOKEN: str = ""
    DUCKDB_ALLOW_ANONYMOUS: bool = False
    DUCKDB_THREADS: int = 4
    DUCKDB_MEMORY_LIMIT: str = ""
    DUCKDB_READ_CONNECTIONS: int = 4
    DUCKDB_QUERY_TIMEOUT: float = 60.0
    DUCKDB_MAX_RESULT_ROWS: int = 100_000
    DUCKDB_MIGRATE_ON_START: bool = True
    DUCKDB_STAGING_DIR: str = "/data/staging"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def _resolve_token_file(self) -> ServiceSettings:
        """Accept DUCKDB_ANALYTICS_TOKEN_FILE alongside the direct value."""
        if not self.DUCKDB_ANALYTICS_TOKEN:
            from observal_shared.secrets import resolve_secret

            try:
                resolved = resolve_secret("DUCKDB_ANALYTICS_TOKEN")
            except ValueError as e:  # ambiguous or unreadable secret configuration
                raise ValueError(f"invalid DUCKDB_ANALYTICS_TOKEN configuration: {e}") from e
            if resolved:
                self.DUCKDB_ANALYTICS_TOKEN = resolved
        return self


def create_store(settings: ServiceSettings) -> AnalyticsStore:
    return AnalyticsStore(
        path=settings.DUCKDB_PATH,
        threads=settings.DUCKDB_THREADS,
        memory_limit=settings.DUCKDB_MEMORY_LIMIT,
        read_connections=settings.DUCKDB_READ_CONNECTIONS,
        query_timeout=settings.DUCKDB_QUERY_TIMEOUT,
        max_result_rows=settings.DUCKDB_MAX_RESULT_ROWS,
    )


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1)
    params: dict[str, Any] | list[Any] | None = None


class InsertRequest(BaseModel):
    table: str = Field(min_length=1)
    rows: list[dict[str, Any]] = Field(min_length=1)


class SummaryRefreshRequest(BaseModel):
    project_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    harness: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


class BackupRequest(BaseModel):
    destination: str = Field(min_length=1)


class PragmaRequest(BaseModel):
    pragmas: dict[str, str] = Field(min_length=1)


class LoadParquetRequest(BaseModel):
    table: str = Field(min_length=1)
    upload_ids: list[str] = Field(min_length=1)
    replace: bool = True


class ExportRequest(BaseModel):
    tables: list[str] | None = None


def create_app(store: AnalyticsStore | None = None, settings: ServiceSettings | None = None) -> FastAPI:
    settings = settings or ServiceSettings()
    store = store or create_store(settings)
    token = settings.DUCKDB_ANALYTICS_TOKEN
    staging_root = Path(settings.DUCKDB_STAGING_DIR)
    if staging_root == Path("/data/staging") and Path(settings.DUCKDB_PATH).parent != Path("/data"):
        staging_root = Path(settings.DUCKDB_PATH).parent / "staging"

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if not token and not settings.DUCKDB_ALLOW_ANONYMOUS:
            raise RuntimeError("DUCKDB_ANALYTICS_TOKEN is required unless DUCKDB_ALLOW_ANONYMOUS is enabled")
        staging = staging_root
        database_path = Path(settings.DUCKDB_PATH).resolve()
        if database_path == staging.resolve() or database_path.is_relative_to(staging.resolve()):
            raise RuntimeError("DUCKDB_STAGING_DIR must not contain the DuckDB database file")
        await store.start()
        try:
            # Staging files are disposable transfer artifacts. No transfer can
            # be active after this process has acquired the database lock, so
            # clear leftovers from crashes/restarts.
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)
            if settings.DUCKDB_MIGRATE_ON_START:
                await run_migrations(store)
            yield
        finally:
            await store.close()

    app = FastAPI(title="Observal DuckDB analytics service", lifespan=lifespan)
    app.state.store = store
    uploads: dict[str, list[Path]] = {}

    async def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if settings.DUCKDB_ALLOW_ANONYMOUS and not token:
            return
        presented = ""
        if authorization and authorization.lower().startswith("bearer "):
            presented = authorization[7:].strip()
        if not token or not hmac.compare_digest(presented, token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid analytics token")

    @app.get("/health")
    async def health() -> dict:
        ok = await store.health()
        return {
            "status": "ok" if ok else "error",
            "database": "ok" if ok else "error",
            "schema_version": await store.schema_version(),
            "pid": os.getpid(),
        }

    @app.get("/version", dependencies=[Depends(require_token)])
    async def version() -> dict:
        import duckdb

        _, rows = await store.query("SELECT version()")
        return {
            "duckdb": str(rows[0][0]) if rows else duckdb.__version__,
            "schema_version": await store.schema_version(),
        }

    @app.post("/query", dependencies=[Depends(require_token)])
    async def query(payload: QueryRequest) -> dict:
        try:
            columns, rows = await store.query(payload.sql, payload.params)
        except TimeoutError as e:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)[:500]) from e
        return {"data": [dict(zip(columns, row, strict=False)) for row in rows], "row_count": len(rows)}

    @app.post("/execute", dependencies=[Depends(require_token)])
    async def execute(payload: QueryRequest) -> dict:
        try:
            affected = await store.execute(payload.sql, payload.params)
        except TimeoutError as e:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)[:500]) from e
        return {"row_count": affected}

    @app.post("/insert", dependencies=[Depends(require_token)])
    async def insert(payload: InsertRequest) -> dict:
        try:
            inserted = await store.insert(payload.table, payload.rows)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        except TimeoutError as e:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)[:500]) from e
        return {"row_count": inserted}

    @app.post("/refresh_session_summary", dependencies=[Depends(require_token)])
    async def refresh_session_summary(payload: SummaryRefreshRequest) -> dict:
        try:
            await store.refresh_session_summary(
                payload.project_id, payload.user_id, payload.harness, payload.session_id
            )
        except TimeoutError as e:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)[:500]) from e
        return {"status": "ok"}

    @app.post("/admin/checkpoint", dependencies=[Depends(require_token)])
    async def checkpoint() -> dict:
        await store.checkpoint()
        return {"status": "ok"}

    @app.post("/admin/pragmas", dependencies=[Depends(require_token)])
    async def pragmas(payload: PragmaRequest) -> dict:
        applied = await store.apply_pragmas(payload.pragmas)
        return {"status": "ok", "applied": sorted(applied)}

    @app.post("/admin/upload", dependencies=[Depends(require_token)])
    async def upload(files: Annotated[list[UploadFile], File()]) -> dict:
        upload_id = uuid4().hex
        staging = staging_root / f"upload-{upload_id}"
        staging.mkdir(parents=True, exist_ok=False)
        saved: list[str] = []
        try:
            for upload_file in files:
                name = Path(upload_file.filename or "upload.parquet").name
                if not name.endswith(".parquet"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST, detail=f"{name}: only .parquet uploads"
                    )
                target = staging / name
                with target.open("wb") as handle:
                    while chunk := await upload_file.read(1024 * 1024):
                        handle.write(chunk)
                saved.append(str(target))
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        uploads[upload_id] = [Path(path) for path in saved]
        return {"upload_id": upload_id, "files": [Path(path).name for path in saved], "count": len(saved)}

    @app.post("/admin/load_parquet", dependencies=[Depends(require_token)])
    async def load_parquet(payload: LoadParquetRequest) -> dict:
        if len(set(payload.upload_ids)) != len(payload.upload_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="duplicate upload id")
        groups = [uploads.get(upload_id) for upload_id in payload.upload_ids]
        if any(group is None for group in groups):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found or already consumed")
        paths = [path for group in groups if group is not None for path in group]
        for upload_id in payload.upload_ids:
            uploads.pop(upload_id)
        try:
            loaded = await store.load_parquet(payload.table, [str(path) for path in paths], replace=payload.replace)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)[:500]) from e
        finally:
            staging = staging_root.resolve()
            parents: set[Path] = set()
            for path in paths:
                candidate = path.resolve()
                if candidate.is_relative_to(staging) and candidate.is_file():
                    candidate.unlink(missing_ok=True)
                    parents.add(candidate.parent)
            for parent in parents:
                if parent != staging:
                    try:
                        parent.rmdir()
                    except OSError:
                        pass
        return {"table": payload.table, "rows_loaded": loaded}

    @app.post("/admin/export", dependencies=[Depends(require_token)])
    async def export(payload: ExportRequest) -> dict:
        """Write the telemetry tables to monthly Parquet files under the staging dir."""
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = staging_root / f"export-{stamp}-{uuid4().hex}"
        try:
            counts = await store.export_parquet(str(destination), payload.tables)
        except TimeoutError as e:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)[:500]) from e
        files = []
        for path in sorted(destination.glob("*.parquet")):
            hasher = hashlib.sha256()
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    hasher.update(chunk)
            files.append({"name": path.name, "size_bytes": path.stat().st_size, "sha256": hasher.hexdigest()})
        return {"destination": str(destination), "files": files, "row_counts": counts}

    @app.get("/admin/file", dependencies=[Depends(require_token)])
    async def download(path: str) -> FileResponse:
        """Serve a file from the staging directory (export downloads).

        Candidate files come from walking the staging directory, and the request
        value is only ever compared against them, so a crafted ``path`` can
        neither escape the staging root nor name a file that is not already
        there. Callers pass either the absolute path returned by /admin/export,
        a path relative to staging, or a bare file name.
        """
        configured = staging_root
        staging = configured.resolve()
        for candidate in staging.rglob("*"):
            if not candidate.is_file() or not candidate.resolve().is_relative_to(staging):
                continue
            relative = candidate.relative_to(staging)
            forms = {candidate.name, str(candidate), str(relative)}
            if configured != staging:
                # Exports report the configured root, which may be a symlink.
                forms.add(str(configured / relative))
            if path in forms:

                def cleanup(file_path: Path = candidate) -> None:
                    file_path.unlink(missing_ok=True)
                    if file_path.parent != staging:
                        try:
                            file_path.parent.rmdir()
                        except OSError:
                            pass

                return FileResponse(
                    candidate,
                    media_type="application/octet-stream",
                    filename=candidate.name,
                    background=BackgroundTask(cleanup),
                )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")

    @app.post("/admin/backup", dependencies=[Depends(require_token)])
    async def backup(payload: BackupRequest) -> dict:
        try:
            await store.backup(payload.destination)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)[:500]) from e
        return {"status": "ok", "destination": payload.destination}

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception):  # pragma: no cover - safety net
        optic.exception("unhandled analytics service error: {}", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "internal analytics service error"},
        )

    return app


app = create_app()
