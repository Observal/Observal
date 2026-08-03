# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Agent-scoped insight report routes."""

from fastapi import Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import check_listing_visibility_async, get_db, optional_current_user, require_role
from models.insight_report import InsightReport, InsightReportStatus
from models.user import User, UserRole
from schemas.insights import (
    ApplySuggestionsRequest,
    GenerateInsightRequest,
    InsightReportListItem,
    InsightReportResponse,
    RecommendedAddition,
    RecommendedAdditionsResponse,
)

from ._router import router


@router.get("/{agent_id}/insights/session-count")
async def agent_insight_session_count(
    agent_id: str,
    agent_version: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Return the number of sessions available for insight generation."""
    from api.routes.insights import agent_session_count

    return await agent_session_count(agent_id, agent_version, db, current_user)


@router.get("/{agent_id}/insights/reports", response_model=list[InsightReportListItem])
async def list_agent_insight_reports(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """List insight reports for an agent, newest first."""
    from api.routes.insights import list_reports

    return await list_reports(agent_id, db, current_user)


@router.post("/{agent_id}/insights/reports", response_model=InsightReportListItem)
async def create_agent_insight_report(
    agent_id: str,
    req: GenerateInsightRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Trigger generation of an insight report for an agent."""
    from api.routes.insights import generate_insight

    return await generate_insight(agent_id, req, db, current_user)


@router.get("/{agent_id}/insights/reports/{report_id}", response_model=InsightReportResponse)
async def get_agent_insight_report(
    agent_id: str,
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Get one insight report that belongs to an agent."""
    from api.routes.insights import _resolve_insights_agent, get_report

    agent = await _resolve_insights_agent(agent_id, db, current_user)
    report = await get_report(report_id, db, current_user)
    if report.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="Report not found for agent")
    return report


@router.post("/{agent_id}/insights/reports/{report_id}/apply")
async def apply_agent_insight_report_suggestions(
    agent_id: str,
    report_id: str,
    body: ApplySuggestionsRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Apply selected suggestions from an agent insight report."""
    from api.routes.insights import apply_report_suggestions

    await get_agent_insight_report(agent_id, report_id, db, current_user)
    return await apply_report_suggestions(report_id, body, db, current_user)


@router.get("/{agent_id}/insights/reports/{report_id}/export/html", response_class=HTMLResponse)
async def export_agent_insight_report_html(
    agent_id: str,
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Export an agent insight report as a self-contained HTML document."""
    from api.routes.insights import export_report_html

    await get_agent_insight_report(agent_id, report_id, db, current_user)
    return await export_report_html(report_id, db, current_user)


@router.delete("/{agent_id}/insights/reports")
async def delete_agent_insight_reports(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Delete all insight reports and cached data for an agent."""
    from api.routes.insights import clear_agent_reports

    return await clear_agent_reports(agent_id, db, current_user)


@router.get("/{agent_id}/insights/recommended-additions", response_model=RecommendedAdditionsResponse)
async def agent_recommended_additions(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    """Public, evidence-backed add-on recommendations for an agent.

    Returns the latest completed insight report's deterministic component
    shortlist (``registry_offer``) — public registry components the agent does
    not yet use but might benefit from based on observed usage. This is a
    *public* surface: unlike the full insight report, it exposes only public
    component references and never session telemetry, so it is available to
    anyone who can see the agent (including anonymous browsing).

    Empty ``items`` means no report exists, the offer was empty, or the feature
    was disabled at generation time. Callers hide the rail rather than erroring.
    """
    from api.routes.agent.helpers import _load_agent

    agent = await _load_agent(
        db,
        agent_id,
        prefer_user_id=current_user.id if current_user else None,
        current_user=current_user,
        include_all_statuses=False,
    )
    if not agent or not await check_listing_visibility_async(agent, current_user, db):
        raise HTTPException(status_code=404, detail="Agent not found")

    # Latest completed report for this agent. Only completed reports carry a
    # registry_offer; pending/running/failed rows are skipped.
    stmt = (
        select(InsightReport)
        .where(
            InsightReport.agent_id == agent.id,
            InsightReport.status == InsightReportStatus.completed,
        )
        .order_by(InsightReport.completed_at.desc().nulls_last())
        .limit(1)
    )
    report = (await db.execute(stmt)).scalar_one_or_none()

    empty = RecommendedAdditionsResponse(agent_id=agent.id)
    if not report:
        return empty

    offer = report.registry_offer
    if not isinstance(offer, dict) or not offer.get("enabled", True):
        return empty

    entries_by_type = offer.get("entries_by_type") or {}
    if not isinstance(entries_by_type, dict):
        return empty

    items: list[RecommendedAddition] = []
    for _type_plural, entries in entries_by_type.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # Each entry is a CatalogOffer.to_catalog_entry() dict: type, id,
            # qualified_name, name, description, category. Skip anything that
            # lacks the minimum fields needed to render a link.
            if not entry.get("id") or not entry.get("type"):
                continue
            items.append(
                RecommendedAddition(
                    type=str(entry["type"]),
                    id=str(entry["id"]),
                    qualified_name=str(entry.get("qualified_name") or entry.get("name") or entry["id"]),
                    name=str(entry.get("name") or entry.get("qualified_name") or entry["id"]),
                    description=entry.get("description"),
                    category=entry.get("category"),
                )
            )

    return RecommendedAdditionsResponse(
        agent_id=agent.id,
        items=items,
        source_report_id=report.id,
        generated_at=report.completed_at,
    )
