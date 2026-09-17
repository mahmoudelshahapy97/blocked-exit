"""Alert log, acknowledgement, and delivery testing."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import PaginationDep, SessionDep, WorkspaceDep, require_workspace_role
from app.core.enums import AlertChannel, AlertStatus, BlockageState, WorkspaceRole
from app.core.exceptions import NotFoundError
from app.models.alert import Alert
from app.models.camera import Camera
from app.schemas.event import AlertAcknowledge, AlertRead, AlertTestRequest, Page
from app.services import alerting
from app.utils.timing import utcnow

router = APIRouter(prefix="/alerts", tags=["alerts"])

ViewerDep = [Depends(require_workspace_role(WorkspaceRole.VIEWER))]
OperatorDep = [Depends(require_workspace_role(WorkspaceRole.OPERATOR))]


@router.get("", response_model=Page[AlertRead], dependencies=ViewerDep)
async def list_alerts(
    ctx: WorkspaceDep,
    session: SessionDep,
    pagination: PaginationDep,
    camera_id: int | None = None,
    status: AlertStatus | None = None,
    channel: AlertChannel | None = None,
    unacknowledged_only: bool = False,
) -> Page[AlertRead]:
    filters = [Alert.workspace_id == ctx.workspace.id]
    if camera_id is not None:
        filters.append(Alert.camera_id == camera_id)
    if status is not None:
        filters.append(Alert.status == status.value)
    if channel is not None:
        filters.append(Alert.channel == channel.value)
    if unacknowledged_only:
        filters.append(Alert.acknowledged_at.is_(None))

    total = await session.scalar(select(func.count(Alert.id)).where(*filters))
    rows = (
        (
            await session.execute(
                select(Alert)
                .where(*filters)
                .order_by(Alert.created_at.desc())
                .limit(pagination.limit)
                .offset(pagination.offset)
            )
        )
        .scalars()
        .all()
    )

    return Page[AlertRead](
        items=[AlertRead.model_validate(row) for row in rows],
        total=int(total or 0),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.post("/{alert_id}/ack", response_model=AlertRead, dependencies=OperatorDep)
async def acknowledge_alert(
    alert_id: int, payload: AlertAcknowledge, ctx: WorkspaceDep, session: SessionDep
) -> Alert:
    alert = await session.scalar(
        select(Alert).where(Alert.id == alert_id, Alert.workspace_id == ctx.workspace.id)
    )
    if alert is None:
        raise NotFoundError(f"Alert {alert_id} not found")
    alert.acknowledged_at = utcnow()
    alert.acknowledged_by = payload.acknowledged_by
    await session.commit()
    await session.refresh(alert)
    return alert


@router.post("/test", response_model=list[AlertRead], dependencies=OperatorDep)
async def test_alert(
    payload: AlertTestRequest, ctx: WorkspaceDep, session: SessionDep
) -> list[Alert]:
    """Fire a synthetic alert to verify webhook/SMTP configuration."""
    camera = await session.scalar(
        select(Camera).where(
            Camera.id == payload.camera_id, Camera.workspace_id == ctx.workspace.id
        )
    )
    if camera is None:
        raise NotFoundError(f"Camera {payload.camera_id} not found")

    body = alerting.build_payload(
        camera_id=camera.id,
        camera_name=camera.name,
        location=camera.location,
        state=BlockageState.FULL,
        accessibility_pct=12.5,
        blocked_duration_s=42.0,
        risk_score=91.0,
        risk_level="CRITICAL",
        recommended_action="Clear Exit Immediately",
        blocking_objects=[
            {"label": "chair", "confidence": 0.91, "area_pct": 54.2, "track_id": 7}
        ],
        strategy=camera.strategy,
    )
    body["event"] = "alert_test"

    rows = await alerting.dispatch(
        body,
        workspace_id=ctx.workspace.id,
        camera_id=camera.id,
        channels=payload.channels,
    )
    if not rows:
        raise NotFoundError(
            "No alert channel is configured. Set WEBHOOK_URL and/or SMTP_HOST "
            "plus ALERT_EMAIL_TO in .env"
        )
    # Re-read so the response reflects committed rows.
    ids = [row.id for row in rows]
    result = await session.execute(select(Alert).where(Alert.id.in_(ids)))
    return list(result.scalars().all())
