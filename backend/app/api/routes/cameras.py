"""Camera CRUD, door polygon, and door-centric reference calibration."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.api.deps import (
    CameraDep,
    ManagerDep,
    SessionDep,
    WorkspaceDep,
    require_workspace_role,
)
from app.core.config import settings
from app.core.enums import WorkspaceRole
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.redaction import redact_url
from app.models.camera import Camera
from app.schemas.camera import (
    CameraCreate,
    CameraHierarchy,
    CameraRead,
    CameraUpdate,
    DoorPolygonUpdate,
    ProbeResult,
    ReferenceCaptureResponse,
)
from app.services import annotator, probe
from app.services.detector.door_centric import capture_reference
from app.services.filters import csv_values
from app.utils.image import encode_jpeg
from app.utils.timing import utcnow
from app.utils.video import grab_single_frame

router = APIRouter(prefix="/cameras", tags=["cameras"])

# Every route needs at least a viewer in the active workspace. Camera writes
# need a member; drawing the exit region is a workspace admin's call, as on the
# platform (PUT /blocked-exit/cameras/{id}/polygon).
ViewerDep = Depends(require_workspace_role(WorkspaceRole.VIEWER))
MemberDep = Depends(require_workspace_role(WorkspaceRole.MEMBER))
AdminDep = Depends(require_workspace_role(WorkspaceRole.ADMIN))


@router.post(
    "",
    response_model=CameraRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[MemberDep],
)
async def create_camera(
    payload: CameraCreate, ctx: WorkspaceDep, session: SessionDep, manager: ManagerDep
) -> Camera:
    existing = await session.scalar(
        select(Camera).where(
            Camera.workspace_id == ctx.workspace.id, Camera.name == payload.name
        )
    )
    if existing is not None:
        raise ConflictError(f"A camera named {payload.name!r} already exists")

    camera_count = await session.scalar(
        select(func.count(Camera.id)).where(Camera.workspace_id == ctx.workspace.id)
    )
    if int(camera_count or 0) >= ctx.workspace.camera_quota:
        raise ConflictError(
            f"Workspace camera quota reached ({ctx.workspace.camera_quota}). "
            "Ask a platform administrator to raise it."
        )

    camera = Camera(workspace_id=ctx.workspace.id, **payload.model_dump(mode="json"))
    session.add(camera)
    await session.commit()
    await session.refresh(camera)

    if camera.enabled:
        await manager.start(camera.id)
    return camera


def _read(camera: Camera, ctx: WorkspaceDep) -> CameraRead:
    """A viewer sees where a camera is, never the credentials in its URL --
    only members, who can edit the camera, need the URL as entered."""
    read = CameraRead.model_validate(camera)
    if not ctx.role.can_act_as(WorkspaceRole.MEMBER):
        read.rtsp_url = read.source_host
    return read


@router.get("", response_model=list[CameraRead], dependencies=[ViewerDep])
async def list_cameras(
    ctx: WorkspaceDep, session: SessionDep, enabled: bool | None = None
) -> list[CameraRead]:
    query = (
        select(Camera).where(Camera.workspace_id == ctx.workspace.id).order_by(Camera.id)
    )
    if enabled is not None:
        query = query.where(Camera.enabled.is_(enabled))
    return [_read(c, ctx) for c in (await session.execute(query)).scalars()]


@router.get("/hierarchy", response_model=CameraHierarchy, dependencies=[ViewerDep])
async def camera_hierarchy(
    ctx: WorkspaceDep,
    session: SessionDep,
    location: str | None = Query(None, description="Comma-separated"),
    area: str | None = Query(None, description="Comma-separated"),
    building: str | None = Query(None, description="Comma-separated"),
    floor_level: str | None = Query(None, description="Comma-separated"),
) -> CameraHierarchy:
    """The values each hierarchy level takes in this workspace, each narrowed
    by the levels chosen above it -- feeds the cascading filter selects (the
    platform's locations/areas/buildings/floor-levels/zones list endpoints)."""
    chosen = {
        "location": csv_values(location),
        "area": csv_values(area),
        "building": csv_values(building),
        "floor_level": csv_values(floor_level),
    }
    levels = ("location", "area", "building", "floor_level", "zone")

    async def distinct(level: str) -> list[str]:
        column = getattr(Camera, level)
        parents = levels[: levels.index(level)]
        query = (
            select(column)
            .where(
                Camera.workspace_id == ctx.workspace.id,
                column.is_not(None),
                *[getattr(Camera, p).in_(chosen[p]) for p in parents if chosen[p]],
            )
            .distinct()
            .order_by(column)
        )
        return list((await session.execute(query)).scalars())

    return CameraHierarchy(
        locations=await distinct("location"),
        areas=await distinct("area"),
        buildings=await distinct("building"),
        floor_levels=await distinct("floor_level"),
        zones=await distinct("zone"),
    )


@router.post("/probe-all", response_model=list[ProbeResult], dependencies=[MemberDep])
async def probe_all_cameras(ctx: WorkspaceDep, session: SessionDep) -> list[ProbeResult]:
    """Test the connection to every camera in the workspace. Runs concurrently,
    but the probe service caps how many sources are opened at once."""
    query = select(Camera).where(Camera.workspace_id == ctx.workspace.id)
    cameras = (await session.execute(query.order_by(Camera.id))).scalars().all()

    async def one(camera: Camera) -> ProbeResult:
        result = await probe.probe(camera.rtsp_url)
        return ProbeResult(camera_id=camera.id, camera_name=camera.name, **result)

    return list(await asyncio.gather(*(one(c) for c in cameras)))


@router.get("/{camera_id}", response_model=CameraRead, dependencies=[ViewerDep])
async def get_camera(camera: CameraDep, ctx: WorkspaceDep) -> CameraRead:
    return _read(camera, ctx)


@router.post("/{camera_id}/probe", response_model=ProbeResult, dependencies=[MemberDep])
async def probe_camera(camera: CameraDep) -> ProbeResult:
    """Open the camera's source and read one frame, without starting a worker:
    reachable, how long it took, and the resolution and frame rate it reports."""
    result = await probe.probe(camera.rtsp_url)
    return ProbeResult(camera_id=camera.id, camera_name=camera.name, **result)


@router.patch("/{camera_id}", response_model=CameraRead, dependencies=[MemberDep])
async def update_camera(
    payload: CameraUpdate, camera: CameraDep, session: SessionDep, manager: ManagerDep
) -> Camera:
    changes = payload.model_dump(mode="json", exclude_unset=True)
    for field, value in changes.items():
        setattr(camera, field, value)
    await session.commit()
    await session.refresh(camera)

    await manager.apply_camera_update(camera)
    if camera.enabled and manager.get(camera.id) is None:
        await manager.start(camera.id)
    return camera


@router.delete(
    "/{camera_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[MemberDep]
)
async def delete_camera(
    camera: CameraDep, session: SessionDep, manager: ManagerDep
) -> None:
    await manager.stop(camera.id)
    await session.delete(camera)
    await session.commit()


@router.get(
    "/{camera_id}/zone-editor",
    include_in_schema=False,
)
async def zone_editor(camera: CameraDep) -> RedirectResponse:
    """Memorable entry point for the browser-based exit-region editor."""
    if not settings.ENABLE_ZONE_EDITOR:
        raise NotFoundError("The zone editor is disabled (ENABLE_ZONE_EDITOR=false)")
    return RedirectResponse(url=f"/ui/zone-editor.html?camera_id={camera.id}")


@router.get(
    "/{camera_id}/calibration-frame",
    responses={200: {"content": {"image/jpeg": {}}}},
    response_class=Response,
    summary="Clean still frame for drawing the exit region on",
)
async def calibration_frame(camera: CameraDep, manager: ManagerDep) -> Response:
    """An unannotated frame plus the exact pixel dimensions it was captured at.

    The dimensions are the point: a client draws in the pixels of what it was
    shown, and sends them back with these values so the server can normalize.
    Overlays are deliberately omitted — banners and boxes obscure the doorway
    the operator is trying to trace.
    """
    worker = manager.get(camera.id)
    frame = worker.snapshot(annotated=False) if worker else None
    if frame is None:
        frame = await _grab_frame(camera.rtsp_url)
    if frame is None:
        raise ValidationError(
            f"Could not read a frame from {redact_url(camera.rtsp_url)!r}. "
            "Check the stream is reachable, or start monitoring first."
        )

    height, width = frame.shape[:2]
    return Response(
        content=encode_jpeg(frame),
        media_type="image/jpeg",
        headers={
            "X-Frame-Width": str(width),
            "X-Frame-Height": str(height),
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{camera_id}/door-polygon/preview",
    responses={200: {"content": {"image/jpeg": {}}}},
    response_class=Response,
    summary="The stored exit region drawn over the current frame",
)
async def preview_door_polygon(camera: CameraDep, manager: ManagerDep) -> Response:
    """Render the saved polygon so an operator can confirm what was stored."""
    worker = manager.get(camera.id)
    frame = worker.snapshot(annotated=False) if worker else None
    if frame is None:
        frame = await _grab_frame(camera.rtsp_url)
    if frame is None:
        frame = annotator.placeholder("Stream unavailable - showing region only")

    points = len(camera.door_polygon) if camera.door_polygon else 0
    caption = f"{camera.name} - {points} points" if points else camera.name
    preview = annotator.draw_zone(frame, camera.door_polygon, caption=caption)
    return Response(
        content=encode_jpeg(preview),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.put(
    "/{camera_id}/door-polygon", response_model=CameraRead, dependencies=[AdminDep]
)
async def set_door_polygon(
    payload: DoorPolygonUpdate,
    camera: CameraDep,
    session: SessionDep,
    manager: ManagerDep,
) -> Camera:
    """Define the exit region the zone-based strategy measures against.

    Accepts normalized [0,1] points, or pixel points together with the
    `frame_width`/`frame_height` they were drawn on.
    """
    camera.door_polygon = payload.door_polygon
    await session.commit()
    await session.refresh(camera)
    await manager.apply_camera_update(camera)
    return camera


@router.post(
    "/{camera_id}/reference",
    response_model=ReferenceCaptureResponse,
    dependencies=[AdminDep],
)
async def capture_reference_door(
    camera: CameraDep, session: SessionDep, manager: ManagerDep
) -> ReferenceCaptureResponse:
    """Store the current view as the unobstructed door reference.

    Call this while the exit is clear — the door-centric strategy measures every
    later frame against it (ICAART 2026 §4.3.2).
    """
    worker = manager.get(camera.id)
    frame = worker.snapshot(annotated=False) if worker else None
    if frame is None:
        frame = await _grab_frame(camera.rtsp_url)
    if frame is None:
        raise ValidationError(
            f"Could not read a frame from {redact_url(camera.rtsp_url)!r}. "
            "Check the stream is reachable."
        )

    detection = capture_reference(frame)
    if detection is None:
        raise ValidationError(
            "No door detected in the current frame. Configure DOOR_MODEL_PATH "
            "with door weights and make sure the door is visible and unobstructed."
        )

    bbox, confidence = detection
    camera.reference_bbox = [round(v, 6) for v in bbox]
    camera.reference_captured_at = utcnow()
    await session.commit()
    await session.refresh(camera)
    await manager.apply_camera_update(camera)

    return ReferenceCaptureResponse(
        camera_id=camera.id,
        reference_bbox=camera.reference_bbox,
        confidence=round(confidence, 3),
        captured_at=camera.reference_captured_at,
        message="Reference door captured. Set strategy='door_centric' to use it.",
    )


async def _grab_frame(source: str):
    """Grab one frame off the event loop — VideoCapture blocks."""
    import anyio

    return await anyio.to_thread.run_sync(lambda: grab_single_frame(source))
