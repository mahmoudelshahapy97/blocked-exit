"""Worker lifecycle and the bridge from worker threads to the database.

Workers run on threads; SQLAlchemy async sessions belong to the event loop. The
manager owns that boundary: workers hand messages to :meth:`publish` (thread
safe), and a single consumer task on the loop performs every write.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.database import session_scope
from app.core.enums import BlockageState, RiskLevel, WorkerState
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.camera import Camera
from app.models.event import BlockageEvent
from app.schemas.detection import CameraStatus
from app.services import alerting
from app.services.detector.base import CameraContext
from app.services.stream_worker import PipelineMessage, StreamWorker
from app.utils.timing import utcnow

logger = get_logger(__name__)

QUEUE_MAXSIZE = 512

# Messages that define an event's lifecycle. Losing one leaves the database
# permanently inconsistent — an event that never opens, or never closes — so
# these are never the ones dropped under pressure.
CRITICAL_KINDS = frozenset({"open", "close", "alert"})

# A worker that has produced nothing for this multiple of the read timeout is
# wedged inside a blocking read and cannot recover on its own.
STALL_TIMEOUT_MULTIPLIER = 3.0


class StreamManager:
    """Singleton coordinating all camera workers."""

    def __init__(self) -> None:
        self._workers: dict[int, StreamWorker] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[PipelineMessage] | None = None
        self._consumer: asyncio.Task | None = None
        self._supervisor: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._dropped_updates = 0
        # camera_id -> (restart count, monotonic time of the next allowed retry)
        self._restarts: dict[int, int] = {}
        self._retry_after: dict[int, float] = {}

    # -- lifecycle --------------------------------------------------------
    async def startup(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._consumer = asyncio.create_task(self._consume(), name="pipeline-consumer")
        await self._close_orphaned_events()
        await self._autostart_enabled_cameras()
        if settings.WORKER_SUPERVISION_ENABLED:
            self._supervisor = asyncio.create_task(
                self._supervise(), name="worker-supervisor"
            )

    async def shutdown(self) -> None:
        await _cancel(self._supervisor)
        self._supervisor = None

        workers = list(self._workers.values())
        for worker in workers:
            worker.stop()
        # join() blocks; on the event loop it would freeze every request for up
        # to 5s per camera, so hand each one to a thread and wait on them together.
        if workers:
            await asyncio.gather(
                *(asyncio.to_thread(worker.join, 5.0) for worker in workers),
                return_exceptions=True,
            )
        for worker in workers:
            if worker.is_alive():
                logger.warning(
                    "Camera %s: worker did not stop within 5s", worker.camera.id
                )
        self._workers.clear()

        if self._consumer is not None:
            # Drain first: workers publish a closing message on their way out
            # and losing it would orphan the event they were reporting.
            await self._drain()
            await _cancel(self._consumer)
            self._consumer = None
        logger.info("All stream workers stopped")

    async def _close_orphaned_events(self) -> None:
        """Close events left open by a process that died mid-blockage.

        `ended_at IS NULL` means "still happening". After an unclean shutdown
        those rows say a blockage from last week is ongoing, and the analytics
        duration maths (which measures open events up to `now()`) inflates every
        aggregate for as long as the row survives.
        """
        try:
            async with session_scope() as session:
                ended_at = utcnow()
                result = await session.execute(
                    update(BlockageEvent)
                    .where(BlockageEvent.ended_at.is_(None))
                    .values(
                        ended_at=ended_at,
                        duration_s=func.extract(
                            "epoch", ended_at - BlockageEvent.started_at
                        ),
                        state=BlockageState.UNKNOWN.value,
                    )
                )
                closed = result.rowcount or 0
            if closed:
                logger.warning(
                    "Closed %d blockage event(s) left open by a previous run", closed
                )
        except Exception as exc:
            logger.warning("Could not reconcile open events: %s", exc)

    async def _autostart_enabled_cameras(self) -> None:
        """Bring monitoring back up after a restart, without manual intervention."""
        try:
            async with session_scope() as session:
                result = await session.execute(
                    select(Camera.id).where(Camera.enabled.is_(True))
                )
                camera_ids = list(result.scalars())
        except Exception as exc:
            logger.warning("Could not autostart cameras: %s", exc)
            return

        for camera_id in camera_ids:
            try:
                await self.start(camera_id)
            except Exception as exc:
                logger.warning("Autostart failed for camera %s: %s", camera_id, exc)

    # -- supervision ------------------------------------------------------
    async def _supervise(self) -> None:
        """Restart workers that died, errored, or wedged.

        Without this a worker that fails to initialise its detector, or blocks
        forever inside a read on a half-open TCP connection, simply stops
        monitoring its exit — silently, and until somebody notices by hand.
        """
        interval = max(1.0, settings.WORKER_SUPERVISION_INTERVAL_S)
        while True:
            try:
                await asyncio.sleep(interval)
                await self._check_workers()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker supervisor iteration failed")

    async def _check_workers(self) -> None:
        now = time.monotonic()
        stall_after = settings.STREAM_READ_TIMEOUT_S * STALL_TIMEOUT_MULTIPLIER

        for camera_id, worker in list(self._workers.items()):
            reason = self._unhealthy_reason(worker, stall_after)
            if reason is None:
                # A spell of health earns back a clean slate, so an exit that
                # flaps overnight is not stuck on a 5-minute backoff by morning.
                self._restarts.pop(camera_id, None)
                self._retry_after.pop(camera_id, None)
                continue

            if now < self._retry_after.get(camera_id, 0.0):
                continue

            attempt = self._restarts.get(camera_id, 0) + 1
            delay = min(
                settings.WORKER_RESTART_BACKOFF_BASE_S * (2 ** (attempt - 1)),
                settings.WORKER_RESTART_BACKOFF_MAX_S,
            )
            self._restarts[camera_id] = attempt
            self._retry_after[camera_id] = now + delay

            logger.warning(
                "Camera %s: %s — restarting (attempt %d, next retry in %.0fs)",
                camera_id,
                reason,
                attempt,
                delay,
            )
            try:
                await self.restart(camera_id)
            except Exception as exc:
                logger.warning("Camera %s: restart failed: %s", camera_id, exc)

    @staticmethod
    def _unhealthy_reason(worker: StreamWorker, stall_after: float) -> str | None:
        if not worker.is_alive():
            return "worker thread is dead"
        if worker.state is WorkerState.ERROR:
            return f"worker is in error state ({worker.error})"
        if (
            worker.state is WorkerState.RUNNING
            and worker.seconds_since_progress > stall_after
        ):
            return (
                f"no frame analysed for {worker.seconds_since_progress:.0f}s "
                f"(threshold {stall_after:.0f}s)"
            )
        return None

    # -- worker control ---------------------------------------------------
    async def start(self, camera_id: int) -> StreamWorker:
        async with self._lock:
            worker = self._workers.get(camera_id)
            if worker is not None and worker.is_alive():
                return worker

            async with session_scope() as session:
                camera = await session.get(Camera, camera_id)
                if camera is None:
                    raise NotFoundError(f"Camera {camera_id} not found")
                context = CameraContext.from_orm(camera)
                source = camera.rtsp_url

            worker = StreamWorker(context, source, self.publish)
            self._workers[camera_id] = worker
            worker.start()
            logger.info("Camera %s: worker started (%s)", camera_id, context.strategy)
            return worker

    async def stop(self, camera_id: int) -> None:
        async with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker is None:
            return
        worker.stop()
        await asyncio.to_thread(worker.join, 5.0)
        logger.info("Camera %s: worker stopped", camera_id)

    async def restart(self, camera_id: int) -> StreamWorker:
        await self.stop(camera_id)
        return await self.start(camera_id)

    async def apply_camera_update(self, camera: Camera) -> None:
        """Reflect an edited camera on its running worker."""
        worker = self._workers.get(camera.id)
        if worker is None:
            return
        # Source and strategy are bound at thread start; everything else
        # (polygon, thresholds) can be swapped in place.
        needs_restart = (
            worker.source != camera.rtsp_url or worker.camera.strategy != camera.strategy
        )
        if not camera.enabled:
            await self.stop(camera.id)
        elif needs_restart:
            await self.restart(camera.id)
        else:
            worker.update_camera(CameraContext.from_orm(camera))

    # -- read-side --------------------------------------------------------
    def get(self, camera_id: int) -> StreamWorker | None:
        return self._workers.get(camera_id)

    def require(self, camera_id: int) -> StreamWorker:
        worker = self._workers.get(camera_id)
        if worker is None:
            raise NotFoundError(
                f"Camera {camera_id} is not being monitored. "
                f"POST {settings.API_V1_PREFIX}/monitoring/{camera_id}/start first."
            )
        return worker

    def statuses(self, *, workspace_id: int | None = None) -> list[CameraStatus]:
        return [
            worker.status()
            for worker in self._workers.values()
            if workspace_id is None or worker.camera.workspace_id == workspace_id
        ]

    def worker_health(self, *, workspace_id: int | None = None) -> list[dict]:
        return [
            {
                "camera_id": worker.camera.id,
                "camera_name": worker.camera.name,
                "state": worker.state.value,
                "alive": worker.is_alive(),
                "frames_processed": worker.frames_processed,
                "reconnects": worker.reconnects,
                "supervisor_restarts": self._restarts.get(worker.camera.id, 0),
                "seconds_since_frame": round(worker.seconds_since_progress, 1),
                "error": worker.error,
            }
            for worker in self._workers.values()
            if workspace_id is None or worker.camera.workspace_id == workspace_id
        ]

    def pipeline_health(self) -> dict:
        queue = self._queue
        return {
            "queue_depth": queue.qsize() if queue is not None else 0,
            "queue_capacity": QUEUE_MAXSIZE,
            "dropped_updates": self._dropped_updates,
            "consumer_running": self._consumer is not None and not self._consumer.done(),
            "supervisor_running": self._supervisor is not None
            and not self._supervisor.done(),
        }

    @property
    def running_count(self) -> int:
        return sum(
            1 for worker in self._workers.values() if worker.state is WorkerState.RUNNING
        )

    def running_count_for(self, workspace_id: int) -> int:
        return sum(
            1
            for worker in self._workers.values()
            if worker.state is WorkerState.RUNNING
            and worker.camera.workspace_id == workspace_id
        )

    # -- thread -> loop bridge --------------------------------------------
    def publish(self, message: PipelineMessage) -> None:
        """Called from worker threads. Never blocks the worker."""
        loop, queue = self._loop, self._queue
        if loop is None or queue is None:
            return

        def _put() -> None:
            try:
                queue.put_nowait(message)
                return
            except asyncio.QueueFull:
                pass

            # Under pressure, shed progress updates rather than lifecycle
            # messages: a lost "update" costs one sample of a live event, a lost
            # "open" or "close" corrupts the event history permanently.
            if message.kind not in CRITICAL_KINDS:
                self._dropped_updates += 1
                logger.warning(
                    "Pipeline queue full — dropping %s from camera %s (%d dropped)",
                    message.kind,
                    message.camera_id,
                    self._dropped_updates,
                )
                return

            if self._evict_one_update(queue):
                queue.put_nowait(message)
                logger.warning(
                    "Pipeline queue full — evicted an update to keep %s from camera %s",
                    message.kind,
                    message.camera_id,
                )
            else:
                logger.error(
                    "Pipeline queue full of lifecycle messages — %s from camera "
                    "%s was lost; event history may be incomplete",
                    message.kind,
                    message.camera_id,
                )

        try:
            loop.call_soon_threadsafe(_put)
        except RuntimeError:  # loop closed during shutdown
            pass

    @staticmethod
    def _evict_one_update(queue: asyncio.Queue[PipelineMessage]) -> bool:
        """Drop the oldest sheddable message to make room for a critical one.

        Cycles the queue rather than touching its internals, keeping FIFO order
        and the get/task_done accounting that :meth:`_drain` relies on intact.
        """
        held: list[PipelineMessage] = []
        evicted = False
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            queue.task_done()
            if not evicted and item.kind not in CRITICAL_KINDS:
                evicted = True
                continue
            held.append(item)
        for item in held:
            queue.put_nowait(item)
        return evicted

    async def _drain(self) -> None:
        if self._queue is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=5.0)
        except TimeoutError:
            logger.warning("Pipeline queue did not drain in time")

    async def _consume(self) -> None:
        assert self._queue is not None
        while True:
            message = await self._queue.get()
            try:
                await self._handle(message)
            except Exception:
                logger.exception(
                    "Failed to handle %s for camera %s",
                    message.kind,
                    message.camera_id,
                )
            finally:
                self._queue.task_done()

    async def _handle(self, message: PipelineMessage) -> None:
        handler = {
            "open": self._on_open,
            "update": self._on_update,
            "close": self._on_close,
            "alert": self._on_alert,
        }.get(message.kind)
        if handler is None:
            logger.warning("Unknown pipeline message kind: %s", message.kind)
            return
        await handler(message)

    # -- persistence ------------------------------------------------------
    async def _on_open(self, message: PipelineMessage) -> None:
        payload = message.payload
        state = BlockageState(payload["state"])
        started_at = payload.get("started_at") or utcnow()
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)

        # Disk I/O off the event loop — a slow or full volume must not stall
        # every other request while an event is being recorded.
        snapshot_path = await asyncio.to_thread(
            _write_snapshot, message.snapshot, message.camera_id, "open"
        )

        worker = self._workers.get(message.camera_id)
        workspace_id = worker.camera.workspace_id if worker is not None else None

        async with session_scope() as session:
            event = BlockageEvent(
                workspace_id=workspace_id,
                camera_id=message.camera_id,
                started_at=started_at,
                state=state.value,
                peak_state=state.value,
                strategy=payload.get("strategy", "zone_based"),
                min_accessibility_pct=payload["accessibility_pct"],
                last_accessibility_pct=payload["accessibility_pct"],
                peak_risk_score=payload.get("risk_score", 0.0),
                risk_level=payload.get("risk_level"),
                confidence=payload.get("confidence"),
                avg_confidence=payload.get("avg_confidence"),
                blocking_objects=payload.get("blocking_objects"),
                snapshot_path=snapshot_path,
            )
            session.add(event)
            await session.flush()
            event_id = event.id

        if worker is not None:
            worker.current_event_id = event_id

    async def _on_update(self, message: PipelineMessage) -> None:
        payload = message.payload
        event_id = payload.get("event_id") or self._current_event_id(message.camera_id)
        if event_id is None:
            return
        state = BlockageState(payload["state"])

        async with session_scope() as session:
            event = await session.get(BlockageEvent, event_id)
            if event is None or event.ended_at is not None:
                return
            accessibility = payload["accessibility_pct"]
            event.last_accessibility_pct = accessibility
            event.min_accessibility_pct = min(event.min_accessibility_pct, accessibility)
            event.peak_risk_score = max(
                event.peak_risk_score, payload.get("risk_score", 0.0)
            )
            event.state = state.value
            if state.severity > BlockageState(event.peak_state).severity:
                event.peak_state = state.value
            if payload.get("blocking_objects"):
                event.blocking_objects = payload["blocking_objects"]
            event.risk_level = _worse_risk(event.risk_level, payload.get("risk_level"))
            _apply_confidence(event, payload)

    async def _on_close(self, message: PipelineMessage) -> None:
        payload = message.payload
        event_id = payload.get("event_id") or self._current_event_id(message.camera_id)
        if event_id is None:
            return
        async with session_scope() as session:
            event = await session.get(BlockageEvent, event_id)
            if event is None or event.ended_at is not None:
                return
            ended_at = utcnow()
            event.ended_at = ended_at
            event.duration_s = (
                payload.get("duration_s") or (ended_at - event.started_at).total_seconds()
            )
            event.last_accessibility_pct = payload.get(
                "accessibility_pct", event.last_accessibility_pct
            )
            event.state = BlockageState.CLEAR.value
            _apply_confidence(event, payload)

    async def _on_alert(self, message: PipelineMessage) -> None:
        payload = message.payload["alert"]
        event_id = message.payload.get("event_id") or self._current_event_id(
            message.camera_id
        )
        payload["event_id"] = event_id
        worker = self._workers.get(message.camera_id)
        workspace_id = worker.camera.workspace_id if worker is not None else None
        await alerting.dispatch(
            payload,
            workspace_id=workspace_id,
            camera_id=message.camera_id,
            event_id=event_id,
            snapshot=message.snapshot,
        )

    def _current_event_id(self, camera_id: int) -> int | None:
        worker = self._workers.get(camera_id)
        return worker.current_event_id if worker else None


async def _cancel(task: asyncio.Task | None) -> None:
    """Cancel a background task and wait for it to actually finish."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Background task raised while shutting down")


_RISK_ORDER = [level.value for level in RiskLevel]  # LOW .. CRITICAL


def _worse_risk(current: str | None, new: str | None) -> str | None:
    """An event keeps the worst risk band it ever reached."""
    if current is None or new is None:
        return current or new
    return max(current, new, key=_RISK_ORDER.index)


def _apply_confidence(event: BlockageEvent, payload: dict) -> None:
    """The worker's running peak/mean, when it has any samples yet."""
    if payload.get("confidence") is not None:
        event.confidence = payload["confidence"]
        event.avg_confidence = payload.get("avg_confidence")


def _write_snapshot(data: bytes | None, camera_id: int, tag: str) -> str | None:
    if not data:
        return None
    try:
        directory = Path(settings.SNAPSHOT_DIR) / f"camera_{camera_id}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{tag}_{utcnow():%Y%m%dT%H%M%S%f}.jpg"
        path.write_bytes(data)
        return str(path)
    except Exception as exc:  # pragma: no cover - disk issues must not break flow
        logger.warning("Could not write snapshot: %s", exc)
        return None


stream_manager = StreamManager()
