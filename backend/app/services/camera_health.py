"""Camera health notifications: "camera offline" when a camera's worker has
been reconnecting (or in error) for CAMERA_OFFLINE_AFTER_S, and "back online"
once it runs again. One of each per outage, to everyone who can see the
camera's workspace.

It only reads the stream manager's statuses, so it never touches a stream. A
stopped camera is not offline: it is forgotten, and starts fresh when it runs
again.
"""

from __future__ import annotations

import asyncio
import time

from app.core.config import settings
from app.core.database import session_scope
from app.core.enums import WorkerState
from app.core.logging import get_logger
from app.models.camera import Camera
from app.services import inbox

logger = get_logger(__name__)

_task: asyncio.Task | None = None
_DOWN = {WorkerState.RECONNECTING, WorkerState.ERROR}


class CameraHealthWatch:
    def __init__(self) -> None:
        # camera id -> "online" | "offline"; judged only once seen online.
        self.state: dict[int, str] = {}
        self._down_since: dict[int, float] = {}

    async def check(self, statuses, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        seen = set()
        for status in statuses:
            worker_state = WorkerState(status.worker_state)
            if worker_state is WorkerState.STOPPED:
                continue
            camera_id = status.camera_id
            seen.add(camera_id)
            previous = self.state.get(camera_id)
            if worker_state is WorkerState.RUNNING:
                self._down_since.pop(camera_id, None)
                if previous == "offline":
                    await self._notify(camera_id, online=True)
                self.state[camera_id] = "online"
                continue
            if worker_state not in _DOWN or previous != "online":
                continue
            since = self._down_since.setdefault(camera_id, now)
            if now - since < settings.CAMERA_OFFLINE_AFTER_S:
                continue
            self.state[camera_id] = "offline"
            await self._notify(camera_id, online=False)
        for gone in set(self.state) - seen:
            self.state.pop(gone, None)
            self._down_since.pop(gone, None)

    async def _notify(self, camera_id: int, online: bool) -> None:
        async with session_scope() as session:
            camera = await session.get(Camera, camera_id)
            if camera is None:
                return
            name, workspace_id = camera.name, camera.workspace_id
        await inbox.notify_workspace(
            workspace_id,
            kind="camera_online" if online else "camera_offline",
            severity="info" if online else "high",
            title=f"{name} is back online" if online else f"{name} is offline",
            message=(
                "Frames are arriving again and monitoring has resumed."
                if online
                else f"No frames for over {int(settings.CAMERA_OFFLINE_AFTER_S)} s. "
                "Monitoring is paused until the source answers."
            ),
            link=f"/cameras/{camera_id}",
            camera_id=camera_id,
            camera_name=name,
        )
        logger.info("Camera %s %s", name, "back online" if online else "offline")


watch = CameraHealthWatch()


async def _loop() -> None:
    from app.services.stream_manager import stream_manager

    while True:
        try:
            await watch.check(stream_manager.statuses())
        except Exception:
            logger.exception("Camera health check failed")
        await asyncio.sleep(max(1.0, settings.CAMERA_HEALTH_INTERVAL_S))


def start() -> None:
    global _task
    if _task is None:
        _task = asyncio.create_task(_loop(), name="camera-health")


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
