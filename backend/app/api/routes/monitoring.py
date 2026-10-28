"""Live monitoring: worker control, verdicts, annotated output."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from app.api.deps import (
    CameraDep,
    CameraViaTicketDep,
    ManagerDep,
    WorkspaceDep,
    require_workspace_role,
)
from app.core.config import settings
from app.core.enums import WorkerState, WorkspaceRole
from app.core.exceptions import StreamError
from app.core.logging import get_logger
from app.core.security import create_stream_ticket
from app.schemas.auth import StreamTicket
from app.schemas.detection import CameraStatus, MonitoringActionResponse
from app.services import annotator
from app.utils.image import encode_jpeg, mjpeg_part

logger = get_logger(__name__)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

ViewerDep = Depends(require_workspace_role(WorkspaceRole.VIEWER))
MemberDep = Depends(require_workspace_role(WorkspaceRole.MEMBER))
AdminDep = Depends(require_workspace_role(WorkspaceRole.ADMIN))

# Each viewer costs one JPEG encode per frame. Unbounded viewers would compete
# with detection for CPU on exactly the hardware that has none to spare.
_viewers = asyncio.Semaphore(settings.MAX_MJPEG_CLIENTS)


@router.post(
    "/{camera_id}/start",
    response_model=MonitoringActionResponse,
    dependencies=[MemberDep],
)
async def start_monitoring(
    camera: CameraDep, manager: ManagerDep
) -> MonitoringActionResponse:
    worker = await manager.start(camera.id)
    return MonitoringActionResponse(
        camera_id=camera.id,
        worker_state=worker.state,
        message=f"Monitoring {camera.name} using {camera.strategy}",
    )


@router.post(
    "/{camera_id}/stop",
    response_model=MonitoringActionResponse,
    dependencies=[MemberDep],
)
async def stop_monitoring(
    camera: CameraDep, manager: ManagerDep
) -> MonitoringActionResponse:
    await manager.stop(camera.id)
    return MonitoringActionResponse(
        camera_id=camera.id,
        worker_state=WorkerState.STOPPED,
        message=f"Stopped monitoring {camera.name}",
    )


@router.post(
    "/{camera_id}/restart",
    response_model=MonitoringActionResponse,
    dependencies=[MemberDep],
)
async def restart_monitoring(
    camera: CameraDep, manager: ManagerDep
) -> MonitoringActionResponse:
    worker = await manager.restart(camera.id)
    return MonitoringActionResponse(
        camera_id=camera.id,
        worker_state=worker.state,
        message=f"Restarted monitoring {camera.name}",
    )


@router.get("/status", response_model=list[CameraStatus], dependencies=[ViewerDep])
async def all_status(ctx: WorkspaceDep, manager: ManagerDep) -> list[CameraStatus]:
    """Every monitored exit in this workspace — the dashboard poll."""
    return manager.statuses(workspace_id=ctx.workspace.id)


@router.get("/{camera_id}/status", response_model=CameraStatus, dependencies=[ViewerDep])
async def camera_status(camera: CameraDep, manager: ManagerDep) -> CameraStatus:
    return manager.require(camera.id).status()


@router.post(
    "/{camera_id}/stream-ticket", response_model=StreamTicket, dependencies=[ViewerDep]
)
async def issue_stream_ticket(camera: CameraDep, ctx: WorkspaceDep) -> StreamTicket:
    """A 60-second, single-camera credential for `<img src>` live view.

    `<img>` cannot send an Authorization header, so the frontend calls this
    first (with a normal bearer token) and puts the result on the image URL as
    `?ticket=...` instead of putting the real access token there.
    """
    ticket, expires_at = create_stream_ticket(
        user_id=ctx.user.id, workspace_id=ctx.workspace.id, camera_id=camera.id
    )
    return StreamTicket(
        ticket=ticket,
        camera_id=camera.id,
        expires_at=expires_at,
        expires_in=60,
    )


@router.get(
    "/{camera_id}/snapshot",
    responses={200: {"content": {"image/jpeg": {}}}},
    response_class=Response,
)
async def snapshot(
    camera: CameraViaTicketDep, manager: ManagerDep, annotated: bool = True
) -> Response:
    """Latest processed frame: door region, obstacles and the verdict drawn on."""
    worker = manager.require(camera.id)
    frame = worker.snapshot(annotated=annotated)
    if frame is None:
        frame = annotator.placeholder("Waiting for first frame...")
    jpeg = await asyncio.to_thread(encode_jpeg, frame)
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/{camera_id}/stream")
async def mjpeg_stream(
    camera: CameraViaTicketDep, manager: ManagerDep, request: Request
) -> StreamingResponse:
    """MJPEG live view — open it directly in a browser tab."""
    worker = manager.require(camera.id)
    interval = max(0.05, settings.process_interval_s)

    if _viewers.locked():
        raise StreamError(
            f"Too many live viewers (limit {settings.MAX_MJPEG_CLIENTS}). "
            "Close an existing stream, or poll /snapshot instead."
        )

    async def generate():
        # Held for the life of the response, released when the generator is
        # closed — which Starlette does on client disconnect.
        async with _viewers:
            while True:
                # Without this check a closed browser tab leaves the loop
                # encoding frames for a socket nobody is reading.
                if await request.is_disconnected():
                    break
                frame = worker.snapshot(annotated=True)
                if frame is None:
                    frame = annotator.placeholder("Waiting for first frame...")
                jpeg = await asyncio.to_thread(encode_jpeg, frame)
                yield mjpeg_part(jpeg)
                await asyncio.sleep(interval)

    return StreamingResponse(
        generate(), media_type="multipart/x-mixed-replace; boundary=frame"
    )
