"""The thread→loop bridge and the worker supervisor.

Both exist to survive things going wrong, so the tests drive them with stub
workers and a hand-filled queue rather than real cameras.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.core.enums import WorkerState
from app.services.stream_manager import QUEUE_MAXSIZE, StreamManager
from app.services.stream_worker import PipelineMessage


class StubWorker:
    """Enough of a StreamWorker for the supervisor to form an opinion about."""

    def __init__(
        self,
        camera_id: int = 1,
        *,
        alive: bool = True,
        state: WorkerState = WorkerState.RUNNING,
        seconds_since_progress: float = 0.0,
        error: str | None = None,
    ) -> None:
        self.camera = type("Cam", (), {"id": camera_id, "name": f"Exit {camera_id}"})()
        self._alive = alive
        self.state = state
        self.seconds_since_progress = seconds_since_progress
        self.error = error
        self.frames_processed = 0
        self.reconnects = 0

    def is_alive(self) -> bool:
        return self._alive


def message(kind: str, camera_id: int = 1) -> PipelineMessage:
    return PipelineMessage(kind=kind, camera_id=camera_id)


# -- queue shedding -------------------------------------------------------
def fill(manager: StreamManager, kind: str, count: int) -> None:
    for _ in range(count):
        manager._queue.put_nowait(message(kind))


@pytest.fixture
async def manager() -> StreamManager:
    instance = StreamManager()
    instance._queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
    instance._loop = asyncio.get_running_loop()
    return instance


async def settle() -> None:
    """Let the loop run the callback publish() scheduled from 'another thread'."""
    for _ in range(3):
        await asyncio.sleep(0)


async def test_updates_are_dropped_when_the_queue_is_full(manager: StreamManager):
    fill(manager, "update", QUEUE_MAXSIZE)

    manager.publish(message("update"))
    await settle()

    assert manager._queue.qsize() == QUEUE_MAXSIZE
    assert manager._dropped_updates == 1


async def test_an_open_evicts_an_update_rather_than_being_lost(manager: StreamManager):
    """Losing an 'open' orphans an event forever; losing an update costs one sample."""
    fill(manager, "update", QUEUE_MAXSIZE)

    manager.publish(message("open"))
    await settle()

    kinds = [manager._queue.get_nowait().kind for _ in range(manager._queue.qsize())]
    assert "open" in kinds
    assert kinds.count("update") == QUEUE_MAXSIZE - 1


async def test_eviction_preserves_arrival_order(manager: StreamManager):
    manager._queue = asyncio.Queue(maxsize=3)
    for kind in ("update", "close", "update"):
        manager._queue.put_nowait(message(kind))

    manager.publish(message("open"))
    await settle()

    kinds = [manager._queue.get_nowait().kind for _ in range(manager._queue.qsize())]
    assert kinds == ["close", "update", "open"]


async def test_a_queue_of_only_lifecycle_messages_reports_the_loss(
    manager: StreamManager, caplog
):
    manager._queue = asyncio.Queue(maxsize=2)
    fill(manager, "close", 2)

    manager.publish(message("open"))
    await settle()

    assert manager._queue.qsize() == 2
    assert any("was lost" in record.message for record in caplog.records)


async def test_eviction_keeps_the_join_accounting_intact(manager: StreamManager):
    """_drain() waits on queue.join(); mismatched task_done calls would hang it."""
    manager._queue = asyncio.Queue(maxsize=2)
    fill(manager, "update", 2)

    manager.publish(message("open"))
    await settle()

    while not manager._queue.empty():
        manager._queue.get_nowait()
        manager._queue.task_done()

    await asyncio.wait_for(manager._queue.join(), timeout=1.0)


async def test_publish_before_startup_is_a_no_op():
    """Workers may outlive the loop during shutdown; publishing must not raise."""
    StreamManager().publish(message("open"))


# -- supervisor health assessment -----------------------------------------
def test_a_healthy_worker_needs_no_intervention():
    worker = StubWorker()
    assert StreamManager._unhealthy_reason(worker, stall_after=45.0) is None


def test_a_dead_thread_is_unhealthy():
    worker = StubWorker(alive=False)
    assert "dead" in StreamManager._unhealthy_reason(worker, stall_after=45.0)


def test_an_errored_worker_is_unhealthy():
    worker = StubWorker(state=WorkerState.ERROR, error="detector failed to load")
    reason = StreamManager._unhealthy_reason(worker, stall_after=45.0)
    assert "error" in reason and "detector failed to load" in reason


def test_a_worker_that_stopped_producing_frames_is_unhealthy():
    """A blocked cv2.read() cannot notice its own stall — somebody outside must."""
    worker = StubWorker(seconds_since_progress=90.0)
    assert "no frame analysed" in StreamManager._unhealthy_reason(
        worker, stall_after=45.0
    )


def test_a_reconnecting_worker_is_given_time():
    """Reconnection has its own backoff; the supervisor must not fight it."""
    worker = StubWorker(state=WorkerState.RECONNECTING, seconds_since_progress=90.0)
    assert StreamManager._unhealthy_reason(worker, stall_after=45.0) is None


# -- supervisor restart policy --------------------------------------------
async def test_the_supervisor_restarts_an_unhealthy_worker(monkeypatch):
    manager = StreamManager()
    manager._workers = {1: StubWorker(alive=False)}
    restarted: list[int] = []

    async def fake_restart(camera_id: int):
        restarted.append(camera_id)

    monkeypatch.setattr(manager, "restart", fake_restart)
    await manager._check_workers()

    assert restarted == [1]
    assert manager._restarts[1] == 1


async def test_backoff_holds_off_a_second_immediate_restart(monkeypatch):
    manager = StreamManager()
    manager._workers = {1: StubWorker(alive=False)}
    restarted: list[int] = []

    async def fake_restart(camera_id: int):
        restarted.append(camera_id)

    monkeypatch.setattr(manager, "restart", fake_restart)
    monkeypatch.setattr(settings, "WORKER_RESTART_BACKOFF_BASE_S", 60.0)

    await manager._check_workers()
    await manager._check_workers()  # immediately again

    assert restarted == [1], "a camera that just restarted must be left alone"


async def test_backoff_is_capped(monkeypatch):
    manager = StreamManager()
    manager._workers = {1: StubWorker(alive=False)}
    monkeypatch.setattr(settings, "WORKER_RESTART_BACKOFF_BASE_S", 5.0)
    monkeypatch.setattr(settings, "WORKER_RESTART_BACKOFF_MAX_S", 20.0)

    async def fake_restart(camera_id: int):
        pass

    monkeypatch.setattr(manager, "restart", fake_restart)

    import time

    for _ in range(8):
        manager._retry_after[1] = time.monotonic() - 1  # pretend the wait elapsed
        await manager._check_workers()

    delay = manager._retry_after[1] - time.monotonic()
    assert delay <= 20.0 + 1.0


async def test_recovery_clears_the_backoff(monkeypatch):
    """An exit that flaps overnight must not be stuck on a long backoff by morning."""
    manager = StreamManager()
    manager._workers = {1: StubWorker(alive=False)}

    async def fake_restart(camera_id: int):
        pass

    monkeypatch.setattr(manager, "restart", fake_restart)
    await manager._check_workers()
    assert manager._restarts[1] == 1

    manager._workers = {1: StubWorker(alive=True)}
    await manager._check_workers()

    assert 1 not in manager._restarts


async def test_a_failing_restart_does_not_stop_the_supervisor(monkeypatch):
    manager = StreamManager()
    manager._workers = {1: StubWorker(alive=False), 2: StubWorker(alive=False)}
    seen: list[int] = []

    async def fake_restart(camera_id: int):
        seen.append(camera_id)
        if camera_id == 1:
            raise RuntimeError("camera 1 is unreachable")

    monkeypatch.setattr(manager, "restart", fake_restart)
    await manager._check_workers()

    assert seen == [1, 2]


# -- reporting ------------------------------------------------------------
def test_pipeline_health_reports_queue_pressure(manager: StreamManager):
    fill(manager, "update", 5)
    manager._dropped_updates = 3

    health = manager.pipeline_health()

    assert health["queue_depth"] == 5
    assert health["queue_capacity"] == QUEUE_MAXSIZE
    assert health["dropped_updates"] == 3
