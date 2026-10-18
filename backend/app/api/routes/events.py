"""Blockage event history."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select

from app.api.deps import PaginationDep, SessionDep, WorkspaceDep, require_workspace_role
from app.core.enums import BlockageState, WorkspaceRole
from app.core.exceptions import AppError, NotFoundError
from app.models.event import BlockageEvent
from app.schemas.event import BlockageEventRead, DeleteResult, Page
from app.services.filters import EventFilters, event_filters
from app.services.retention import unlink_files

router = APIRouter(prefix="/events", tags=["events"])

ViewerDep = [Depends(require_workspace_role(WorkspaceRole.VIEWER))]
AdminDep = [Depends(require_workspace_role(WorkspaceRole.ADMIN))]
FiltersDep = Annotated[EventFilters, Depends(event_filters)]


@router.get("", response_model=Page[BlockageEventRead], dependencies=ViewerDep)
async def list_events(
    ctx: WorkspaceDep,
    session: SessionDep,
    pagination: PaginationDep,
    event_filter: FiltersDep,
    state: BlockageState | None = None,
    open_only: bool = False,
    since: datetime | None = Query(None, description="Only events started after this"),
    until: datetime | None = None,
) -> Page[BlockageEventRead]:
    filters = event_filter.conditions(ctx.workspace.id)
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


async def _delete_events(session: SessionDep, conditions: list) -> DeleteResult:
    """Delete closed events matching `conditions` (their alerts cascade) and
    their snapshot files. Ongoing events are kept: a stream worker is still
    writing to them, and deleting one would orphan the blockage it records."""
    closed = [*conditions, BlockageEvent.ended_at.is_not(None)]
    paths = (
        await session.execute(
            select(BlockageEvent.snapshot_path).where(
                *closed, BlockageEvent.snapshot_path.is_not(None)
            )
        )
    ).scalars().all()
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
        raise AppError(
            "Give at least one filter, or use DELETE /events/all?confirm=true"
        )
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
    return await _delete_events(
        session, [BlockageEvent.workspace_id == ctx.workspace.id]
    )
