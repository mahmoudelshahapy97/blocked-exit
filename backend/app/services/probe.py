"""Connection checks ("Test connection"), like the platform's rtsp_probe.

Opening a capture blocks, so each probe runs in a worker thread under a hard
timeout, and a semaphore caps how many sources are opened at once -- probing a
whole workspace must not hammer every camera (or the NVR behind them) in the
same instant.
"""

from __future__ import annotations

import asyncio
import time
import weakref

import anyio

from app.core.config import settings
from app.core.redaction import redact_text
from app.utils.video import VideoSource

MAX_READ_ATTEMPTS = 3
MAX_ERROR_CHARS = 300


_semaphores: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _semaphore() -> asyncio.Semaphore:
    # One per event loop: an asyncio primitive cannot be shared across loops.
    loop = asyncio.get_running_loop()
    if loop not in _semaphores:
        _semaphores[loop] = asyncio.Semaphore(max(1, settings.PROBE_CONCURRENCY))
    return _semaphores[loop]


def _probe_blocking(source: str) -> dict:
    started = time.monotonic()
    video = VideoSource(source, loop_files=False)
    try:
        if not video.open():
            return {"reachable": False, "error": "Could not open the stream"}
        frame = None
        for _ in range(MAX_READ_ATTEMPTS):
            frame = video.read()
            if frame is not None:
                break
        if frame is None:
            return {"reachable": False, "error": "Opened, but no frame arrived"}
        height, width = frame.shape[:2]
        fps = video.fps
        return {
            "reachable": True,
            "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
            "width": int(width),
            "height": int(height),
            # Containers report 0 or absurd values when they do not know.
            "fps": round(float(fps), 2) if 0 < fps <= 1000 else None,
        }
    finally:
        video.release()


async def probe(source: str) -> dict:
    """{reachable, latency_ms, width, height, fps, error}; never raises."""
    async with _semaphore():
        try:
            with anyio.fail_after(settings.PROBE_TIMEOUT_S):
                # abandon_on_cancel: a capture stuck in a TCP read cannot be
                # interrupted; let the thread finish on its own.
                result = await anyio.to_thread.run_sync(
                    _probe_blocking, source, abandon_on_cancel=True
                )
        except TimeoutError:
            result = {"reachable": False, "error": "timed out"}
        except Exception as exc:  # pragma: no cover - defensive
            result = {"reachable": False, "error": str(exc)}
    if result.get("error"):
        result["error"] = redact_text(result["error"])[:MAX_ERROR_CHARS]
    return result
