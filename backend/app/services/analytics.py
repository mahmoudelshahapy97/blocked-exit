"""Aggregation queries behind the analytics endpoints."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import Float, and_, case, cast, func, literal_column, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AlertStatus, BlockageState, EventStatus
from app.core.exceptions import NotFoundError
from app.models.alert import Alert
from app.models.camera import Camera
from app.models.event import BlockageEvent
from app.schemas.analytics import (
    AnalyticsSummary,
    Breakdown,
    CameraBlockage,
    CameraConfidence,
    CameraIncidentCount,
    CameraResponseTimes,
    CameraTimeline,
    ConfidenceAudit,
    ConfidenceBin,
    ConfidenceSummary,
    DailyReport,
    DailyReportRow,
    EventConfidence,
    ExitBlockageStat,
    HeatmapCell,
    HistogramBin,
    ObjectCount,
    ResponseTimes,
    ResponseTimeStats,
    TimelineEntry,
    Trend,
    TrendPoint,
)
from app.services.filters import EventFilters, local_ts, report_tz
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


def _windowed(
    filters: EventFilters | None, workspace_id: int, days: int
) -> tuple[list, datetime, datetime]:
    """Conditions for the rolling-window reports: the shared filters, plus the
    last `days` days unless the filters name a start date of their own."""
    filters = filters or EventFilters()
    start, end = _window(days)
    conditions = filters.conditions(workspace_id)
    window_start, window_end = filters.window
    if window_start is None:
        conditions.append(BlockageEvent.started_at >= start)
    return conditions, window_start or start, min(window_end or end, end)


async def summary(
    session: AsyncSession,
    *,
    workspace_id: int,
    days: int = 7,
    monitored_count: int = 0,
    filters: EventFilters | None = None,
) -> AnalyticsSummary:
    conditions, start, end = _windowed(filters, workspace_id, days)
    duration = _effective_duration()

    stats = (
        await session.execute(
            select(
                func.count(BlockageEvent.id),
                func.count(BlockageEvent.id).filter(BlockageEvent.ended_at.is_(None)),
                func.coalesce(func.avg(duration), 0.0),
                func.coalesce(func.max(duration), 0.0),
                func.coalesce(func.avg(BlockageEvent.min_accessibility_pct), 100.0),
            ).where(*conditions)
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
    session: AsyncSession,
    *,
    workspace_id: int,
    days: int = 7,
    limit: int = 10,
    filters: EventFilters | None = None,
) -> list[ExitBlockageStat]:
    conditions, _, _ = _windowed(filters, workspace_id, days)
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
            .where(*conditions)
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
    session: AsyncSession,
    *,
    workspace_id: int,
    report_date: date | None = None,
    filters: EventFilters | None = None,
) -> DailyReport:
    """One row per camera (cameras without events included) for one day in
    REPORT_TIMEZONE. Only the camera and location filters apply: the day is
    the date range."""
    tz = report_tz()
    day = report_date or utcnow().astimezone(tz).date()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    camera_conditions = (filters or EventFilters()).camera_conditions(workspace_id)
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
            .where(*camera_conditions)
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


# --- extended analytics --------------------------------------------------------
# The platform's blocked-exit charts. Each takes the shared EventFilters, so a
# chart and the event list it drills into always count the same rows.

DURATION_EDGES = (0.0, 30.0, 60.0, 300.0, 900.0)
CONFIDENCE_BINS = 10
AUDIT_EVENT_LIMIT = 200
TOP_OBJECTS = 10
HOURLY_SPAN = timedelta(days=2)

_acknowledged = BlockageEvent.acknowledged_at.is_not(None)
_resolved = BlockageEvent.status == EventStatus.RESOLVED.value


def _round(value, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def _seconds_between(later, earlier):
    return func.extract("epoch", later - earlier)


async def incidents_per_camera(
    session: AsyncSession, *, workspace_id: int, filters: EventFilters
) -> list[CameraIncidentCount]:
    rows = await session.execute(
        select(
            Camera.id,
            Camera.name,
            Camera.location,
            Camera.area,
            Camera.building,
            Camera.floor_level,
            Camera.zone,
            func.count(BlockageEvent.id),
            func.count(BlockageEvent.id).filter(_acknowledged),
            func.count(BlockageEvent.id).filter(_resolved),
        )
        .join(Camera, Camera.id == BlockageEvent.camera_id)
        .where(*filters.conditions(workspace_id))
        .group_by(Camera.id)
        .order_by(func.count(BlockageEvent.id).desc(), Camera.name)
    )
    return [
        CameraIncidentCount(
            camera_id=r[0],
            camera_name=r[1],
            location=r[2],
            area=r[3],
            building=r[4],
            floor_level=r[5],
            zone=r[6],
            events=r[7],
            acknowledged=r[8],
            resolved=r[9],
        )
        for r in rows.all()
    ]


async def confidence_audit(
    session: AsyncSession, *, workspace_id: int, filters: EventFilters
) -> ConfidenceAudit:
    """How confident the detector was in the objects that blocked exits.

    `confidence` is each episode's peak; "low" means under the detector's
    threshold + 0.1 -- barely past the line the model draws, so the incidents
    most worth a second look.
    """
    threshold = round(float(settings.CONF_THRESHOLD), 4)
    cutoff = round(min(1.0, threshold + 0.1), 4)
    conditions = filters.conditions(workspace_id)
    conf = BlockageEvent.confidence
    low = and_(conf.is_not(None), conf < cutoff)

    s = (
        await session.execute(
            select(
                func.count(BlockageEvent.id),
                func.count(conf),
                func.avg(conf),
                func.min(conf),
                func.max(conf),
                func.count(BlockageEvent.id).filter(low),
                func.count(BlockageEvent.id).filter(_acknowledged),
                func.count(BlockageEvent.id).filter(_resolved),
            ).where(*conditions)
        )
    ).one()
    summary_ = ConfidenceSummary(
        events=s[0],
        scored_events=s[1],
        avg_confidence=_round(s[2]),
        min_confidence=_round(s[3]),
        max_confidence=_round(s[4]),
        low_confidence=s[5],
        low_confidence_share=round(s[5] / s[1], 4) if s[1] else None,
        acknowledged=s[6],
        resolved=s[7],
        threshold=threshold,
        low_confidence_cutoff=cutoff,
    )

    scored = [*conditions, conf.is_not(None)]
    per_camera = await session.execute(
        select(
            Camera.id,
            Camera.name,
            func.count(BlockageEvent.id),
            func.avg(conf),
            func.min(conf),
            func.max(conf),
            func.count(BlockageEvent.id).filter(conf < cutoff),
        )
        .join(Camera, Camera.id == BlockageEvent.camera_id)
        .where(*scored)
        .group_by(Camera.id)
        .order_by(func.avg(conf).desc(), Camera.name)
    )

    # 1.0 belongs in the last bin, not an eleventh one.
    bucket = func.least(
        func.width_bucket(conf, 0.0, 1.0, CONFIDENCE_BINS), CONFIDENCE_BINS
    )
    counts = dict(
        (
            await session.execute(
                select(bucket, func.count()).where(*scored).group_by(bucket)
            )
        ).all()
    )
    histogram = []
    for i in range(1, CONFIDENCE_BINS + 1):
        lo, hi = (i - 1) / CONFIDENCE_BINS, i / CONFIDENCE_BINS
        histogram.append(
            ConfidenceBin(
                bucket=f"{lo:.1f}-{hi:.1f}", min=lo, max=hi, count=counts.get(i, 0)
            )
        )

    events = await session.execute(
        select(BlockageEvent, Camera.name)
        .join(Camera, Camera.id == BlockageEvent.camera_id)
        .where(*scored)
        .order_by(BlockageEvent.started_at.desc(), BlockageEvent.id.desc())
        .limit(AUDIT_EVENT_LIMIT)
    )
    return ConfidenceAudit(
        summary=summary_,
        per_camera=[
            CameraConfidence(
                camera_id=r[0],
                camera_name=r[1],
                events=r[2],
                avg_confidence=_round(r[3]),
                min_confidence=_round(r[4]),
                max_confidence=_round(r[5]),
                low_confidence=r[6],
            )
            for r in per_camera.all()
        ],
        histogram=histogram,
        per_event=[
            EventConfidence(
                event_id=e.id,
                started_at=e.started_at,
                camera_id=e.camera_id,
                camera_name=name,
                confidence=e.confidence,
                avg_confidence=e.avg_confidence,
                status=e.status,
                risk_level=e.risk_level,
            )
            for e, name in events.all()
        ],
    )


def _floor(moment: datetime, bucket: str) -> datetime:
    moment = moment.replace(minute=0, second=0, microsecond=0)
    return moment.replace(hour=0) if bucket == "day" else moment


async def trend(
    session: AsyncSession,
    *,
    workspace_id: int,
    filters: EventFilters,
    bucket: str | None = None,
) -> Trend:
    """Incidents and resolved incidents per hour or day, in local time.

    The series spans the requested date range when there is one (so an empty
    stretch shows as zeros, not as nothing), otherwise the data's own span.
    `bucket` defaults to hourly for spans of two days or less.
    """
    conditions = filters.conditions(workspace_id)
    tz = report_tz()
    first, last = (
        await session.execute(
            select(
                func.min(BlockageEvent.started_at), func.max(BlockageEvent.started_at)
            ).where(*conditions)
        )
    ).one()
    range_start, range_end = filters.window
    span_start = range_start or (first.astimezone(tz) if first else None)
    now = utcnow().astimezone(tz)
    span_end = min(range_end or (last.astimezone(tz) if last else now), now)

    if bucket not in ("hour", "day"):
        hourly = span_start is not None and span_end - span_start <= HOURLY_SPAN
        bucket = "hour" if hourly else "day"
    if span_start is None:
        return Trend(bucket=bucket, timezone=settings.REPORT_TIMEZONE, points=[])

    truncated = func.date_trunc(bucket, local_ts())
    counts = {
        row[0]: (row[1], row[2])
        for row in (
            await session.execute(
                select(
                    truncated,
                    func.count(BlockageEvent.id),
                    func.count(BlockageEvent.id).filter(_resolved),
                )
                .where(*conditions)
                .group_by(truncated)
            )
        ).all()
    }
    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    cursor = _floor(span_start.astimezone(tz).replace(tzinfo=None), bucket)
    stop = _floor(span_end.astimezone(tz).replace(tzinfo=None), bucket)
    points = []
    while cursor <= stop:
        incidents, resolved = counts.get(cursor, (0, 0))
        points.append(
            TrendPoint(bucket_start=cursor, incidents=incidents, resolved=resolved)
        )
        cursor += step
    return Trend(bucket=bucket, timezone=settings.REPORT_TIMEZONE, points=points)


async def heatmap(
    session: AsyncSession, *, workspace_id: int, filters: EventFilters
) -> list[HeatmapCell]:
    """Incidents per weekday (0 = Sunday) and local hour; empty cells omitted."""
    weekday = cast(func.extract("dow", local_ts()), Float)
    hour = cast(func.extract("hour", local_ts()), Float)
    rows = await session.execute(
        select(weekday, hour, func.count(BlockageEvent.id))
        .where(*filters.conditions(workspace_id))
        .group_by(weekday, hour)
        .order_by(weekday, hour)
    )
    return [
        HeatmapCell(weekday=int(w), hour=int(h), incidents=n) for w, h, n in rows.all()
    ]


def _response_columns():
    ack = _seconds_between(BlockageEvent.acknowledged_at, BlockageEvent.started_at)
    res = _seconds_between(BlockageEvent.resolved_at, BlockageEvent.started_at)
    return (
        func.count(BlockageEvent.id),
        func.count(BlockageEvent.acknowledged_at),
        func.count(BlockageEvent.resolved_at),
        func.count(BlockageEvent.id).filter(BlockageEvent.resolved_at.is_(None)),
        func.percentile_cont(0.5).within_group(ack),
        func.percentile_cont(0.9).within_group(ack),
        func.percentile_cont(0.5).within_group(res),
        func.percentile_cont(0.9).within_group(res),
    )


def _response_stats(row) -> dict:
    return {
        "incidents": row[0],
        "acknowledged": row[1],
        "resolved": row[2],
        "open": row[3],
        "ack_median_s": _round(row[4], 1),
        "ack_p90_s": _round(row[5], 1),
        "resolve_median_s": _round(row[6], 1),
        "resolve_p90_s": _round(row[7], 1),
    }


async def response_times(
    session: AsyncSession, *, workspace_id: int, filters: EventFilters
) -> ResponseTimes:
    """Median and 90th percentile time from an incident to its acknowledgement
    and to its resolution (percentile_cont: interpolated), overall and per camera."""
    conditions = filters.conditions(workspace_id)
    overall = (
        await session.execute(select(*_response_columns()).where(*conditions))
    ).one()
    per_camera = await session.execute(
        select(Camera.id, Camera.name, *_response_columns())
        .join(Camera, Camera.id == BlockageEvent.camera_id)
        .where(*conditions)
        .group_by(Camera.id)
        .order_by(func.count(BlockageEvent.id).desc(), Camera.name)
    )
    return ResponseTimes(
        summary=ResponseTimeStats(**_response_stats(overall)),
        per_camera=[
            CameraResponseTimes(
                camera_id=r[0], camera_name=r[1], **_response_stats(r[2:])
            )
            for r in per_camera.all()
        ],
    )


async def breakdown(
    session: AsyncSession, *, workspace_id: int, filters: EventFilters
) -> Breakdown:
    """Blocked time per camera, the spread of episode lengths, and the objects
    found blocking exits most often. Ongoing episodes count up to now."""
    conditions = filters.conditions(workspace_id)
    duration = _effective_duration()

    per_camera = await session.execute(
        select(
            Camera.id,
            Camera.name,
            func.count(BlockageEvent.id),
            func.coalesce(func.sum(duration), 0.0),
            func.coalesce(func.avg(duration), 0.0),
            func.coalesce(func.max(duration), 0.0),
            func.coalesce(func.min(BlockageEvent.min_accessibility_pct), 100.0),
            func.count(BlockageEvent.id).filter(
                BlockageEvent.peak_state == BlockageState.FULL.value
            ),
        )
        .join(Camera, Camera.id == BlockageEvent.camera_id)
        .where(*conditions)
        .group_by(Camera.id)
        .order_by(func.sum(duration).desc(), func.count(BlockageEvent.id).desc())
    )

    edges = DURATION_EDGES
    bin_of = case(
        *[(duration < edges[i + 1], i) for i in range(len(edges) - 1)],
        else_=len(edges) - 1,
    )
    bins = dict(
        (
            await session.execute(
                select(bin_of, func.count()).where(*conditions).group_by(bin_of)
            )
        ).all()
    )
    histogram = [
        HistogramBin(
            min=edges[i],
            max=edges[i + 1] if i + 1 < len(edges) else None,
            count=bins.get(i, 0),
        )
        for i in range(len(edges))
    ]

    element = (
        func.jsonb_array_elements(
            func.coalesce(BlockageEvent.blocking_objects, literal_column("'[]'::jsonb"))
        )
        .table_valued("value")
        .lateral()
    )
    label = element.c.value.op("->>")("label")
    objects = await session.execute(
        select(label, func.count(func.distinct(BlockageEvent.id)))
        .select_from(BlockageEvent)
        .join(element, true())
        .where(*conditions, label.is_not(None))
        .group_by(label)
        .order_by(func.count(func.distinct(BlockageEvent.id)).desc(), label)
        .limit(TOP_OBJECTS)
    )

    return Breakdown(
        per_camera=[
            CameraBlockage(
                camera_id=r[0],
                camera_name=r[1],
                episodes=r[2],
                total_blocked_s=round(float(r[3]), 1),
                avg_duration_s=round(float(r[4]), 1),
                max_duration_s=round(float(r[5]), 1),
                worst_accessibility_pct=round(float(r[6]), 1),
                fully_blocked=r[7],
            )
            for r in per_camera.all()
        ],
        duration_histogram=histogram,
        top_objects=[ObjectCount(object=o, episodes=n) for o, n in objects.all()],
    )
