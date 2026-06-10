# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""Enterprise audit log query and export endpoints.

Compliance-grade audit trail with tamper-detection chain hashes,
sensitivity classification, and outcome tracking.
"""

import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import require_role
from models.user import User, UserRole
from services.clickhouse import _query

router = APIRouter(prefix="/api/v1/admin/audit-log", tags=["audit"])

_ALL_COLUMNS = (
    "event_id, timestamp, actor_id, actor_email, actor_role, "
    "action, resource_type, resource_id, resource_name, http_method, "
    "http_path, status_code, ip_address, user_agent, detail, "
    "org_id, sensitivity, request_id, outcome, duration_ms, chain_hash, source"
)


class AuditLogEntry(BaseModel):
    event_id: str
    timestamp: str
    actor_id: str
    actor_email: str
    actor_role: str
    action: str
    resource_type: str
    resource_id: str
    resource_name: str
    http_method: str
    http_path: str
    status_code: int
    ip_address: str
    user_agent: str
    detail: str
    org_id: str = ""
    sensitivity: str = "standard"
    request_id: str = ""
    outcome: str = ""
    duration_ms: float = 0.0
    chain_hash: str = ""
    source: str = "server"


@router.get("", response_model=list[AuditLogEntry])
async def list_audit_logs(
    actor: str | None = Query(None, description="Filter by actor email"),
    action: str | None = Query(None, description="Filter by action"),
    resource_type: str | None = Query(None, description="Filter by resource type"),
    sensitivity: str | None = Query(None, description="Filter by sensitivity level"),
    outcome: str | None = Query(None, description="Filter by outcome"),
    source: str | None = Query(None, description="Filter by source (server/cli)"),
    start_date: datetime | None = Query(None, description="Start date filter"),
    end_date: datetime | None = Query(None, description="End date filter"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Query audit log entries with optional filters."""
    conditions = []
    params = {}

    if actor:
        conditions.append("actor_email = {actor:String}")
        params["param_actor"] = actor
    if action:
        conditions.append("action = {action:String}")
        params["param_action"] = action
    if resource_type:
        conditions.append("resource_type = {rtype:String}")
        params["param_rtype"] = resource_type
    if sensitivity:
        conditions.append("sensitivity = {sens:String}")
        params["param_sens"] = sensitivity
    if outcome:
        conditions.append("outcome = {outc:String}")
        params["param_outc"] = outcome
    if source:
        conditions.append("source = {src:String}")
        params["param_src"] = source
    if start_date:
        conditions.append("timestamp >= {start:String}")
        params["param_start"] = start_date.strftime("%Y-%m-%d %H:%M:%S")
    if end_date:
        conditions.append("timestamp <= {end:String}")
        params["param_end"] = end_date.strftime("%Y-%m-%d %H:%M:%S")

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""SELECT {_ALL_COLUMNS}
              FROM audit_log
              WHERE {where_clause}
              ORDER BY timestamp DESC
              LIMIT {{lim:UInt32}} OFFSET {{off:UInt32}}
              FORMAT JSONEachRow"""
    params["param_lim"] = str(limit)
    params["param_off"] = str(offset)

    resp = await _query(sql, params)
    if resp.status_code != 200:
        return []

    rows = []
    for line in resp.text.strip().split("\n"):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


@router.get("/export")
async def export_audit_logs(
    actor: str | None = Query(None),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    sensitivity: str | None = Query(None),
    outcome: str | None = Query(None),
    source: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    format: str = Query("csv", description="Export format: csv or json"),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Export audit log for compliance review.

    Supports CSV (default) and JSON formats. Column headers follow the
    standard audit trail schema.
    """
    conditions = []
    params = {}

    if actor:
        conditions.append("actor_email = {actor:String}")
        params["param_actor"] = actor
    if action:
        conditions.append("action = {action:String}")
        params["param_action"] = action
    if resource_type:
        conditions.append("resource_type = {rtype:String}")
        params["param_rtype"] = resource_type
    if sensitivity:
        conditions.append("sensitivity = {sens:String}")
        params["param_sens"] = sensitivity
    if outcome:
        conditions.append("outcome = {outc:String}")
        params["param_outc"] = outcome
    if source:
        conditions.append("source = {src:String}")
        params["param_src"] = source
    if start_date:
        conditions.append("timestamp >= {start:String}")
        params["param_start"] = start_date.strftime("%Y-%m-%d %H:%M:%S")
    if end_date:
        conditions.append("timestamp <= {end:String}")
        params["param_end"] = end_date.strftime("%Y-%m-%d %H:%M:%S")

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""SELECT {_ALL_COLUMNS}
              FROM audit_log WHERE {where_clause}
              ORDER BY timestamp DESC LIMIT 10000
              FORMAT JSONEachRow"""

    resp = await _query(sql, params)

    rows = []
    if resp.status_code == 200:
        for line in resp.text.strip().split("\n"):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if format == "json":
        return StreamingResponse(
            iter(
                [
                    json.dumps(
                        {"audit_trail": rows, "exported_at": datetime.utcnow().isoformat(), "record_count": len(rows)},
                        indent=2,
                    )
                ]
            ),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=observal_audit-log_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
            },
        )

    # CSV export with standard column headers
    output = io.StringIO()
    fieldnames = [
        "event_id",
        "timestamp",
        "actor_id",
        "actor_email",
        "actor_role",
        "action",
        "resource_type",
        "resource_id",
        "resource_name",
        "http_method",
        "http_path",
        "status_code",
        "ip_address",
        "user_agent",
        "detail",
        "org_id",
        "sensitivity",
        "request_id",
        "outcome",
        "duration_ms",
        "chain_hash",
        "source",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=observal_audit-log_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.csv"
        },
    )
