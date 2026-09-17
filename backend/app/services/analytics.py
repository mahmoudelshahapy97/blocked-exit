"""Aggregation queries behind the analytics endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Float, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertStatus, BlockageState
from app.core.exceptions import NotFoundError
from app.models.alert import Alert
from app.models.camera import Camera
from app.models.event import BlockageEvent
from app.schemas.analytics import (
    AnalyticsSummary,
    CameraTimeline,
    DailyReport,
    DailyReportRow,
    ExitBlockageStat,
    TimelineEntry,
)
from app.utils.timing import utcnow


def _window(days: int, *, end: datetime | None = None) -> tuple[datetime, datetime]:
    window_end = end or utcnow()
    return window_end - timedelta(days=days), window_end


def _effective_duration():
    """Duration of an event, treating a still-open event as running until now."""
    return func.coalesce(
        BlockageEvent.duration_s,
        cast(
            func.extract("epoch", func.coalesce(BlockageEvent.ended_at, func.now()))
            - func.extract("epoch", BlockageEvent.started_at),
            Float,
        ),
    )


async def summary(
    session: AsyncSession, *, workspace_id: int, days: int = 7, monitored_count: int = 0
) -> AnalyticsSummary:
    start, end = _window(days)
    duration = _effective_duration()

    stats = (
        await session.execute(
            select(
                func.count(BlockageEvent.id),
                func.count(BlockageEvent.id).filter(BlockageEvent.ended_at.is_(None)),
                func.coalesce(func.avg(duration), 0.0),
                func.coalesce(func.max(duration), 0.0),
                func.coalesce(func.avg(BlockageEvent.min_accessibility_pct), 100.0),
            ).where(
                BlockageEvent.workspace_id == workspace_id,
                BlockageEvent.started_at >= start,
            )
        )
    ).one()

    cameras_total = (
        await session.execute(
            select(func.count(Camera.id)).where(Camera.workspace_id == workspace_id)
        )
    ).scalar_one()

    alerts_sent = (
        await session.execute(
            select(func.count(Alert.id)).where(
                and_(
                    Alert.workspace_id == workspace_id,
                    Alert.created_at >= start,
                    Alert.status == AlertStatus.SENT.value,
                )
            )
        )
    ).scalar_one()

    return AnalyticsSummary(
        window_start=start,
        window_end=end,
        cameras_total=int(cameras_total),
        cameras_monitored=monitored_count,
        currently_blocked=int(stats[1]),
        events_total=int(stats[0]),
        events_open=int(stats[1]),
        avg_duration_s=round(float(stats[2]), 1),
        max_duration_s=round(float(stats[3]), 1),
        avg_min_accessibility_pct=round(float(stats[4]), 1),
        alerts_sent=int(alerts_sent),
    )


async def most_blocked(
    session: AsyncSession, *, workspace_id: int, days: int = 7, limit: int = 10
) -> list[ExitBlockageStat]:
    start, _ = _window(days)
    duration = _effective_duration()

    rows = (
        await session.execute(
            select(
                Camera.id,
                Camera.name,
                Camera.location,
                func.count(BlockageEvent.id).label("event_count"),
                func.coalesce(func.sum(duration), 0.0).label("total_blocked"),
                func.coalesce(func.avg(duration), 0.0).label("avg_duration"),
                func.coalesce(func.max(duration), 0.0).label("max_duration"),
                func.coalesce(func.min(BlockageEvent.min_accessibility_pct), 100.0).label(
                    "min_access"
                ),
                func.coalesce(func.max(BlockageEvent.peak_risk_score), 0.0).label(
                    "peak_risk"
                ),
            )
            .join(BlockageEvent, BlockageEvent.camera_id == Camera.id)
            .where(
                Camera.workspace_id == workspace_id,
                BlockageEvent.started_at >= start,
            )
            .group_by(Camera.id, Camera.name, Camera.location)
            .order_by(func.count(BlockageEvent.id).desc(), func.sum(duration).desc())
            .limit(limit)
        )
    ).all()

    return [
        ExitBlockageStat(
            camera_id=row[0],
            camera_name=row[1],
            location=row[2],
            event_count=int(row[3]),
            total_blocked_s=round(float(row[4]), 1),
            avg_duration_s=round(float(row[5]), 1),
            max_duration_s=round(float(row[6]), 1),
            min_accessibility_pct=round(float(row[7]), 1),
            peak_risk_score=round(float(row[8]), 1),
        )
        for row in rows
    ]


async def timeline(
    session: AsyncSession,
    camera_id: int,
    *,
    workspace_id: int,
    days: int = 7,
    limit: int = 200,
) -> CameraTimeline:
    camera = await session.scalar(
        select(Camera).where(Camera.id == camera_id, Camera.workspace_id == workspace_id)
    )
    if camera is None:
        raise NotFoundError(f"Camera {camera_id} not found")

    start, end = _window(days)
    events = (
        (
            await session.execute(
                select(BlockageEvent)
                .where(
                    and_(
                        BlockageEvent.camera_id == camera_id,
                        BlockageEvent.started_at >= start,
                    )
                )
                .order_by(BlockageEvent.started_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    entries = [
        TimelineEntry(
            event_id=event.id,
            started_at=event.started_at,
            ended_at=event.ended_at,
            duration_s=event.duration_s,
            state=BlockageState(event.state),
            peak_state=BlockageState(event.peak_state),
            min_accessibility_pct=event.min_accessibility_pct,
            peak_risk_score=event.peak_risk_score,
            blocking_labels=sorted(
                {
                    obj.get("label", "")
                    for obj in (event.blocking_objects or [])
                    if obj.get("label")
                }
            ),
        )
        for event in events
    ]

    return CameraTimeline(
        camera_id=camera.id,
        camera_name=camera.name,
        window_start=start,
        window_end=end,
        entries=entries,
    )


async def daily_report(
    session: AsyncSession, *, workspace_id: int, report_date: date | None = None
) -> DailyReport:
    day = report_date or utcnow().date()
    start = datetime.combine(day, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    duration = _effective_duration()

    alerts_sent = (
        select(
            Alert.camera_id.label("camera_id"),
            func.count(Alert.id).label("sent"),
        )
        .where(
            and_(
                Alert.workspace_id == workspace_id,
                Alert.created_at >= start,
                Alert.created_at < end,
                Alert.status == AlertStatus.SENT.value,
            )
        )
        .group_by(Alert.camera_id)
        .subquery()
    )

    rows = (
        await session.execute(
            select(
                Camera.id,
                Camera.name,
                Camera.location,
                func.count(BlockageEvent.id),
                func.coalesce(func.sum(duration), 0.0),
                func.coalesce(func.avg(duration), 0.0),
                func.coalesce(func.max(duration), 0.0),
                func.coalesce(func.min(BlockageEvent.min_accessibility_pct), 100.0),
                func.coalesce(alerts_sent.c.sent, 0),
            )
            .where(Camera.workspace_id == workspace_id)
            .join(
                BlockageEvent,
                and_(
                    BlockageEvent.camera_id == Camera.id,
                    BlockageEvent.started_at >= start,
                    BlockageEvent.started_at < end,
                ),
                isouter=True,
            )
            .join(alerts_sent, alerts_sent.c.camera_id == Camera.id, isouter=True)
            .group_by(Camera.id, Camera.name, Camera.location, alerts_sent.c.sent)
            .order_by(func.count(BlockageEvent.id).desc(), Camera.name)
        )
    ).all()

    report_rows = [
        DailyReportRow(
            camera_id=row[0],
            camera_name=row[1],
            location=row[2],
            event_count=int(row[3]),
            total_blocked_s=round(float(row[4]), 1),
            avg_duration_s=round(float(row[5]), 1),
            longest_blockage_s=round(float(row[6]), 1),
            worst_accessibility_pct=round(float(row[7]), 1),
            alerts_sent=int(row[8]),
        )
        for row in rows
    ]

    totals = None
    if report_rows:
        total_events = sum(row.event_count for row in report_rows)
        total_blocked = sum(row.total_blocked_s for row in report_rows)
        totals = DailyReportRow(
            camera_id=0,
            camera_name="ALL EXITS",
            location=None,
            event_count=total_events,
            total_blocked_s=round(total_blocked, 1),
            avg_duration_s=round(total_blocked / total_events, 1)
            if total_events
            else 0.0,
            longest_blockage_s=max(row.longest_blockage_s for row in report_rows),
            worst_accessibility_pct=min(
                row.worst_accessibility_pct for row in report_rows
            ),
            alerts_sent=sum(row.alerts_sent for row in report_rows),
        )

    return DailyReport(
        report_date=day,
        generated_at=utcnow(),
        rows=report_rows,
        totals=totals,
    )
