"""Analytics for the operations dashboard."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.deps import ManagerDep, SessionDep, WorkspaceDep, require_workspace_role
from app.core.enums import WorkspaceRole
from app.schemas.analytics import (
    AnalyticsSummary,
    CameraTimeline,
    DailyReport,
    ExitBlockageStat,
)
from app.services import analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])

ViewerDep = [Depends(require_workspace_role(WorkspaceRole.VIEWER))]


@router.get("/summary", response_model=AnalyticsSummary, dependencies=ViewerDep)
async def summary(
    ctx: WorkspaceDep,
    session: SessionDep,
    manager: ManagerDep,
    days: int = Query(7, ge=1, le=365),
) -> AnalyticsSummary:
    return await analytics.summary(
        session,
        workspace_id=ctx.workspace.id,
        days=days,
        monitored_count=manager.running_count_for(ctx.workspace.id),
    )


@router.get(
    "/most-blocked", response_model=list[ExitBlockageStat], dependencies=ViewerDep
)
async def most_blocked(
    ctx: WorkspaceDep,
    session: SessionDep,
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(10, ge=1, le=100),
) -> list[ExitBlockageStat]:
    """Which exits are obstructed most often — the heatmap data."""
    return await analytics.most_blocked(
        session, workspace_id=ctx.workspace.id, days=days, limit=limit
    )


@router.get("/daily-report", response_model=DailyReport, dependencies=ViewerDep)
async def daily_report(
    ctx: WorkspaceDep,
    session: SessionDep,
    report_date: date | None = Query(None, description="Defaults to today (UTC)"),
) -> DailyReport:
    return await analytics.daily_report(
        session, workspace_id=ctx.workspace.id, report_date=report_date
    )


@router.get(
    "/{camera_id}/timeline", response_model=CameraTimeline, dependencies=ViewerDep
)
async def camera_timeline(
    camera_id: int,
    ctx: WorkspaceDep,
    session: SessionDep,
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(200, ge=1, le=1000),
) -> CameraTimeline:
    return await analytics.timeline(
        session, camera_id, workspace_id=ctx.workspace.id, days=days, limit=limit
    )
