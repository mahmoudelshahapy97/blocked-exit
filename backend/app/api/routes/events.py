"""Blockage event history."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import PaginationDep, SessionDep, WorkspaceDep, require_workspace_role
from app.core.enums import BlockageState, WorkspaceRole
from app.core.exceptions import NotFoundError
from app.models.event import BlockageEvent
from app.schemas.event import BlockageEventRead, Page

router = APIRouter(prefix="/events", tags=["events"])

ViewerDep = [Depends(require_workspace_role(WorkspaceRole.VIEWER))]


@router.get("", response_model=Page[BlockageEventRead], dependencies=ViewerDep)
async def list_events(
    ctx: WorkspaceDep,
    session: SessionDep,
    pagination: PaginationDep,
    camera_id: int | None = None,
    state: BlockageState | None = None,
    open_only: bool = False,
    since: datetime | None = Query(None, description="Only events started after this"),
    until: datetime | None = None,
) -> Page[BlockageEventRead]:
    filters = [BlockageEvent.workspace_id == ctx.workspace.id]
    if camera_id is not None:
        filters.append(BlockageEvent.camera_id == camera_id)
    if state is not None:
        filters.append(BlockageEvent.state == state.value)
    if open_only:
        filters.append(BlockageEvent.ended_at.is_(None))
    if since is not None:
        filters.append(BlockageEvent.started_at >= since)
    if until is not None:
        filters.append(BlockageEvent.started_at <= until)

    total = await session.scalar(select(func.count(BlockageEvent.id)).where(*filters))
    rows = (
        (
            await session.execute(
                select(BlockageEvent)
                .where(*filters)
                .order_by(BlockageEvent.started_at.desc())
                .limit(pagination.limit)
                .offset(pagination.offset)
            )
        )
        .scalars()
        .all()
    )

    return Page[BlockageEventRead](
        items=[BlockageEventRead.model_validate(row) for row in rows],
        total=int(total or 0),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/{event_id}", response_model=BlockageEventRead, dependencies=ViewerDep)
async def get_event(
    event_id: int, ctx: WorkspaceDep, session: SessionDep
) -> BlockageEvent:
    event = await session.scalar(
        select(BlockageEvent).where(
            BlockageEvent.id == event_id, BlockageEvent.workspace_id == ctx.workspace.id
        )
    )
    if event is None:
        raise NotFoundError(f"Event {event_id} not found")
    return event
