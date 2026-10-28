"""The audit log, for superadmins: filter, page, export."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.deps import SessionDep, require_superadmin
from app.services import audit

router = APIRouter(
    prefix="/audit-logs", tags=["audit"], dependencies=[Depends(require_superadmin)]
)


def _filters(
    action: str | None = Query(None, max_length=64),
    actor: str | None = Query(None, max_length=120, description="Part of the username"),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
) -> dict:
    return {"action": action, "actor": actor, "since": since, "until": until}


@router.get("")
async def list_audit_log(
    session: SessionDep,
    filters: dict = Depends(_filters),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Newest first: {items, total}."""
    return await audit.list_entries(session, filters, limit=limit, offset=offset)


@router.get("/export.csv")
async def export_audit_log(
    session: SessionDep, filters: dict = Depends(_filters)
) -> Response:
    return Response(
        content=await audit.export_csv(session, filters),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
    )
