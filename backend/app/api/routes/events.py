"""Blockage event history and the operator workflow around it.

Each event moves detected -> acknowledged -> resolved (the platform's event
lifecycle), independently of the blockage itself, which ends on its own when
the exit clears (`ended_at`).
"""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import aliased

from app.api.deps import (
    ManagerDep,
    PaginationDep,
    SessionDep,
    WorkspaceDep,
    require_workspace_role,
)
from app.core.enums import BlockageState, EventStatus, RiskLevel, WorkspaceRole
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.models.camera import Camera
from app.models.event import BlockageEvent
from app.models.user import User
from app.schemas.event import (
    BlockageEventRead,
    DeleteResult,
    EventAcknowledge,
    EventOverview,
    EventResolve,
    Page,
)
from app.services.audit import csv_safe
from app.services.filters import EventFilters, csv_values, event_filters
from app.services.retention import unlink_files
from app.utils.timing import utcnow

router = APIRouter(prefix="/events", tags=["events"])

ViewerDep = [Depends(require_workspace_role(WorkspaceRole.VIEWER))]
MemberDep = [Depends(require_workspace_role(WorkspaceRole.MEMBER))]
AdminDep = [Depends(require_workspace_role(WorkspaceRole.ADMIN))]
FiltersDep = Annotated[EventFilters, Depends(event_filters)]

_AckUser = aliased(User)
_ResUser = aliased(User)
_RISK_RANK = case(
    {level.value: rank for rank, level in enumerate(RiskLevel)},
    value=BlockageEvent.risk_level,
    else_=-1,
)
HIGH_RISK = (RiskLevel.HIGH.value, RiskLevel.CRITICAL.value)


def _event_rows():
    """Events with the names an operator reads instead of ids."""
    return (
        select(BlockageEvent, Camera.name, _AckUser.username, _ResUser.username)
        .join(Camera, Camera.id == BlockageEvent.camera_id)
        .outerjoin(_AckUser, _AckUser.id == BlockageEvent.acknowledged_by_id)
        .outerjoin(_ResUser, _ResUser.id == BlockageEvent.resolved_by_id)
    )


def _read(row) -> BlockageEventRead:
    event, camera_name, acknowledged_by, resolved_by = row
    read = BlockageEventRead.model_validate(event)
    read.camera_name = camera_name
    read.acknowledged_by = acknowledged_by
    read.resolved_by = resolved_by
    return read


def _enum_list(value: str | None, enum, name: str) -> list[str]:
    try:
        return [enum(v).value for v in csv_values(value)]
    except ValueError as exc:
        allowed = ", ".join(m.value for m in enum)
        raise AppError(f"{name} must be one or more of: {allowed}") from exc


def _list_filters(
    ctx,
    event_filter,
    status: str | None,
    risk_level: str | None,
    state: BlockageState | None,
    open_only: bool,
    since: datetime | None,
    until: datetime | None,
) -> list:
    filters = event_filter.conditions(ctx.workspace.id)
    if statuses := _enum_list(status, EventStatus, "status"):
        filters.append(BlockageEvent.status.in_(statuses))
    if levels := _enum_list(risk_level, RiskLevel, "risk_level"):
        filters.append(BlockageEvent.risk_level.in_(levels))
    if state is not None:
        filters.append(BlockageEvent.peak_state == state.value)
    if open_only:
        filters.append(BlockageEvent.ended_at.is_(None))
    if since is not None:
        filters.append(BlockageEvent.started_at >= since)
    if until is not None:
        filters.append(BlockageEvent.started_at <= until)
    return filters


@router.get("", response_model=Page[BlockageEventRead], dependencies=ViewerDep)
async def list_events(
    ctx: WorkspaceDep,
    session: SessionDep,
    pagination: PaginationDep,
    event_filter: FiltersDep,
    status: str | None = Query(
        None, description="detected, acknowledged, resolved (comma-separated)"
    ),
    risk_level: str | None = Query(
        None, description="LOW, MEDIUM, HIGH, CRITICAL (comma-separated)"
    ),
    state: BlockageState | None = Query(None, description="Worst state reached"),
    open_only: bool = Query(False, description="Only blockages still ongoing"),
    sort: str = Query("time", pattern="^(time|risk)$"),
    since: datetime | None = Query(None, description="Only events started after this"),
    until: datetime | None = None,
) -> Page[BlockageEventRead]:
    filters = _list_filters(
        ctx, event_filter, status, risk_level, state, open_only, since, until
    )

    order = (
        [_RISK_RANK.desc(), BlockageEvent.peak_risk_score.desc()]
        if sort == "risk"
        else []
    )
    total = await session.scalar(select(func.count(BlockageEvent.id)).where(*filters))
    rows = await session.execute(
        _event_rows()
        .where(*filters)
        .order_by(*order, BlockageEvent.started_at.desc(), BlockageEvent.id.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return Page[BlockageEventRead](
        items=[_read(row) for row in rows.all()],
        total=int(total or 0),
        limit=pagination.limit,
        offset=pagination.offset,
    )


EXPORT_LIMIT = 50_000
_EXPORT_COLUMNS = [
    "id", "started_at", "ended_at", "camera_name", "peak_state", "risk_level",
    "peak_risk_score",
    "min_accessibility_pct", "duration_s", "status", "acknowledged_at", "acknowledged_by",
    "resolved_at", "resolved_by",
]


@router.get("/export.csv", dependencies=ViewerDep)
async def export_events(
    ctx: WorkspaceDep,
    session: SessionDep,
    event_filter: FiltersDep,
    status: str | None = Query(None),
    risk_level: str | None = Query(None),
    state: BlockageState | None = Query(None),
    open_only: bool = Query(False),
    since: datetime | None = Query(None),
    until: datetime | None = None,
) -> Response:
    """The Events list's filters as CSV, newest first, up to 50,000 rows."""
    filters = _list_filters(
        ctx, event_filter, status, risk_level, state, open_only, since, until
    )
    rows = await session.execute(
        _event_rows().where(*filters).order_by(BlockageEvent.started_at.desc()).limit(EXPORT_LIMIT)
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(_EXPORT_COLUMNS)
    for row in rows.all():
        data = _read(row).model_dump(mode="json")
        writer.writerow([data.get(column) for column in _EXPORT_COLUMNS])
    return Response(
        content=csv_safe(out.getvalue()),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="events.csv"'},
    )


@router.get("/overview", response_model=EventOverview, dependencies=ViewerDep)
async def overview(
    ctx: WorkspaceDep, session: SessionDep, manager: ManagerDep
) -> EventOverview:
    """Counters for the dashboard, plus the six latest events."""
    ws = BlockageEvent.workspace_id == ctx.workspace.id
    unresolved = BlockageEvent.status != EventStatus.RESOLVED.value
    ongoing = BlockageEvent.ended_at.is_(None)
    counts = (
        await session.execute(
            select(
                func.count().filter(
                    BlockageEvent.started_at >= utcnow() - timedelta(hours=24)
                ),
                func.count().filter(unresolved),
                func.count().filter(BlockageEvent.status == EventStatus.DETECTED.value),
                func.count().filter(ongoing),
                func.count().filter(unresolved, BlockageEvent.risk_level.in_(HIGH_RISK)),
                func.count(func.distinct(BlockageEvent.camera_id)).filter(ongoing),
            ).where(ws)
        )
    ).one()
    cameras_total = await session.scalar(
        select(func.count(Camera.id)).where(Camera.workspace_id == ctx.workspace.id)
    )
    latest = await session.execute(
        _event_rows().where(ws).order_by(BlockageEvent.started_at.desc()).limit(6)
    )
    return EventOverview(
        events_24h=counts[0],
        open_events=counts[1],
        unacknowledged_events=counts[2],
        ongoing_events=counts[3],
        high_risk_open_events=counts[4],
        currently_blocked=counts[5],
        cameras_total=int(cameras_total or 0),
        cameras_monitored=manager.running_count_for(ctx.workspace.id),
        latest_events=[_read(row) for row in latest.all()],
    )


async def _require_event(session: SessionDep, ctx: WorkspaceDep, event_id: int):
    row = (
        await session.execute(
            _event_rows().where(
                BlockageEvent.id == event_id,
                BlockageEvent.workspace_id == ctx.workspace.id,
            )
        )
    ).first()
    if row is None:
        raise NotFoundError(f"Event {event_id} not found")
    return row


@router.get("/{event_id}", response_model=BlockageEventRead, dependencies=ViewerDep)
async def get_event(
    event_id: int, ctx: WorkspaceDep, session: SessionDep
) -> BlockageEventRead:
    return _read(await _require_event(session, ctx, event_id))


@router.get("/{event_id}/snapshot", dependencies=ViewerDep)
async def get_event_snapshot(
    event_id: int, ctx: WorkspaceDep, session: SessionDep
) -> Response:
    """The annotated frame captured when the blockage was confirmed."""
    event = (await _require_event(session, ctx, event_id))[0]
    path = Path(event.snapshot_path) if event.snapshot_path else None
    if path is None:
        raise NotFoundError("This event has no snapshot")
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except OSError as exc:
        raise NotFoundError(
            "The snapshot file is gone (retention may have removed it)"
        ) from exc
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


async def _advance(
    session: SessionDep,
    ctx: WorkspaceDep,
    event_id: int,
    target: EventStatus,
    note: str | None,
) -> BlockageEventRead:
    event = (await _require_event(session, ctx, event_id))[0]
    now = utcnow()
    current = EventStatus(event.status)
    if current is EventStatus.RESOLVED:
        raise ConflictError(f"Event {event_id} is already resolved")

    # Resolving straight from detected acknowledges it too, so the response-
    # time analytics see when somebody first acted.
    if event.acknowledged_at is None:
        event.acknowledged_at = now
        event.acknowledged_by_id = ctx.user.id
    if target is EventStatus.RESOLVED:
        event.resolved_at = now
        event.resolved_by_id = ctx.user.id
    if note:
        event.resolution_note = note
    event.status = target.value
    await session.commit()
    return _read(await _require_event(session, ctx, event_id))


@router.post(
    "/{event_id}/acknowledge", response_model=BlockageEventRead, dependencies=MemberDep
)
async def acknowledge_event(
    event_id: int,
    ctx: WorkspaceDep,
    session: SessionDep,
    payload: EventAcknowledge | None = None,
) -> BlockageEventRead:
    """Someone has seen it. Idempotent until the event is resolved."""
    return await _advance(
        session,
        ctx,
        event_id,
        EventStatus.ACKNOWLEDGED,
        payload.note if payload else None,
    )


@router.post(
    "/{event_id}/resolve", response_model=BlockageEventRead, dependencies=MemberDep
)
async def resolve_event(
    event_id: int, payload: EventResolve, ctx: WorkspaceDep, session: SessionDep
) -> BlockageEventRead:
    """Close the incident (or, with status=acknowledged, just acknowledge it)."""
    return await _advance(
        session, ctx, event_id, EventStatus(payload.status), payload.note
    )


async def _delete_events(session: SessionDep, conditions: list) -> DeleteResult:
    """Delete closed events matching `conditions` (their alerts cascade) and
    their snapshot files. Ongoing events are kept: a stream worker is still
    writing to them, and deleting one would orphan the blockage it records."""
    closed = [*conditions, BlockageEvent.ended_at.is_not(None)]
    paths = (
        (
            await session.execute(
                select(BlockageEvent.snapshot_path).where(
                    *closed, BlockageEvent.snapshot_path.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )
    skipped = await session.scalar(
        select(func.count(BlockageEvent.id)).where(
            *conditions, BlockageEvent.ended_at.is_(None)
        )
    )
    result = await session.execute(delete(BlockageEvent).where(*closed))
    await session.commit()
    await asyncio.to_thread(unlink_files, [Path(p) for p in paths])
    return DeleteResult(deleted=int(result.rowcount or 0), skipped_open=int(skipped or 0))


@router.delete("", response_model=DeleteResult, dependencies=AdminDep)
async def delete_events(
    ctx: WorkspaceDep, session: SessionDep, event_filter: FiltersDep
) -> DeleteResult:
    """Delete the events matching the filters (workspace admins only).

    At least one filter is required -- deleting everything is a separate,
    explicitly confirmed call, so an empty filter form can never wipe history.
    """
    if event_filter.is_empty:
        raise AppError("Give at least one filter, or use DELETE /events/all?confirm=true")
    return await _delete_events(session, event_filter.conditions(ctx.workspace.id))


@router.delete("/all", response_model=DeleteResult, dependencies=AdminDep)
async def delete_all_events(
    ctx: WorkspaceDep,
    session: SessionDep,
    confirm: bool = Query(False, description="Must be true"),
) -> DeleteResult:
    """Delete every closed event in the workspace (workspace admins only)."""
    if not confirm:
        raise AppError("Confirmation required: pass confirm=true to delete all events")
    return await _delete_events(session, [BlockageEvent.workspace_id == ctx.workspace.id])
