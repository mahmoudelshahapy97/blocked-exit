"""Analytics for the operations dashboard."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import ManagerDep, SessionDep, WorkspaceDep, require_workspace_role
from app.core.enums import WorkspaceRole
from app.schemas.analytics import (
    AnalyticsSummary,
    Breakdown,
    CameraIncidentCount,
    CameraTimeline,
    ConfidenceAudit,
    DailyReport,
    ExitBlockageStat,
    HeatmapCell,
    ResponseTimes,
    Trend,
)
from app.services import analytics
from app.services.filters import EventFilters, event_filters

router = APIRouter(prefix="/analytics", tags=["analytics"])

ViewerDep = [Depends(require_workspace_role(WorkspaceRole.VIEWER))]
FiltersDep = Annotated[EventFilters, Depends(event_filters)]


@router.get("/summary", response_model=AnalyticsSummary, dependencies=ViewerDep)
async def summary(
    ctx: WorkspaceDep,
    session: SessionDep,
    manager: ManagerDep,
    filters: FiltersDep,
    days: int = Query(7, ge=1, le=3650, description="Ignored when start_date is given"),
) -> AnalyticsSummary:
    return await analytics.summary(
        session,
        workspace_id=ctx.workspace.id,
        days=days,
        monitored_count=manager.running_count_for(ctx.workspace.id),
        filters=filters,
    )


@router.get(
    "/most-blocked", response_model=list[ExitBlockageStat], dependencies=ViewerDep
)
async def most_blocked(
    ctx: WorkspaceDep,
    session: SessionDep,
    filters: FiltersDep,
    days: int = Query(7, ge=1, le=3650, description="Ignored when start_date is given"),
    limit: int = Query(10, ge=1, le=100),
) -> list[ExitBlockageStat]:
    """Which exits are obstructed most often."""
    return await analytics.most_blocked(
        session, workspace_id=ctx.workspace.id, days=days, limit=limit, filters=filters
    )


@router.get("/daily-report", response_model=DailyReport, dependencies=ViewerDep)
async def daily_report(
    ctx: WorkspaceDep,
    session: SessionDep,
    filters: FiltersDep,
    report_date: date | None = Query(
        None, description="Defaults to today in REPORT_TIMEZONE"
    ),
) -> DailyReport:
    return await analytics.daily_report(
        session, workspace_id=ctx.workspace.id, report_date=report_date, filters=filters
    )


@router.get(
    "/incidents-per-camera",
    response_model=list[CameraIncidentCount],
    dependencies=ViewerDep,
)
async def incidents_per_camera(
    ctx: WorkspaceDep, session: SessionDep, filters: FiltersDep
) -> list[CameraIncidentCount]:
    """Incidents per camera, with how many were acknowledged and resolved."""
    return await analytics.incidents_per_camera(
        session, workspace_id=ctx.workspace.id, filters=filters
    )


@router.get("/confidence-audit", response_model=ConfidenceAudit, dependencies=ViewerDep)
async def confidence_audit(
    ctx: WorkspaceDep, session: SessionDep, filters: FiltersDep
) -> ConfidenceAudit:
    """Model accuracy and confidence audit of the blocking detections."""
    return await analytics.confidence_audit(
        session, workspace_id=ctx.workspace.id, filters=filters
    )


@router.get("/trend", response_model=Trend, dependencies=ViewerDep)
async def trend(
    ctx: WorkspaceDep,
    session: SessionDep,
    filters: FiltersDep,
    bucket: Literal["hour", "day"] | None = Query(
        None, description="Auto when omitted: hourly for spans of two days or less"
    ),
) -> Trend:
    """Incidents and resolved incidents per hour or day (report timezone)."""
    return await analytics.trend(
        session, workspace_id=ctx.workspace.id, filters=filters, bucket=bucket
    )


@router.get("/heatmap", response_model=list[HeatmapCell], dependencies=ViewerDep)
async def heatmap(
    ctx: WorkspaceDep, session: SessionDep, filters: FiltersDep
) -> list[HeatmapCell]:
    """Incidents per weekday (0 = Sunday) and hour; empty cells are omitted."""
    return await analytics.heatmap(
        session, workspace_id=ctx.workspace.id, filters=filters
    )


@router.get("/response-times", response_model=ResponseTimes, dependencies=ViewerDep)
async def response_times(
    ctx: WorkspaceDep, session: SessionDep, filters: FiltersDep
) -> ResponseTimes:
    """Median / 90th-percentile time to acknowledge and to resolve."""
    return await analytics.response_times(
        session, workspace_id=ctx.workspace.id, filters=filters
    )


@router.get("/breakdown", response_model=Breakdown, dependencies=ViewerDep)
async def breakdown(
    ctx: WorkspaceDep, session: SessionDep, filters: FiltersDep
) -> Breakdown:
    """Blocked time per camera, episode-duration histogram, top blocking objects."""
    return await analytics.breakdown(
        session, workspace_id=ctx.workspace.id, filters=filters
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
