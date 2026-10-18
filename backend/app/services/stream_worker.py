"""Per-camera monitoring worker.

One thread per camera. OpenCV capture and YOLO inference both block and both
release the GIL inside native code, so threads (not processes) keep this cheap
while leaving the event loop free.

The worker never touches the database. It publishes messages through a
callback; :mod:`app.services.stream_manager` drains them on the event loop and
does the persistence and alerting.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.enums import BlockageState, RiskLevel, WorkerState
from app.core.logging import get_logger
from app.core.redaction import redact_text, redact_url
from app.schemas.detection import CameraStatus, DetectionResult
from app.services import alerting, annotator, risk
from app.services.confidence import ConfidenceTracker
from app.services.detector.base import CameraContext
from app.services.detector.registry import strategy_for_camera
from app.services.temporal import TemporalFilter
from app.utils.image import encode_jpeg
from app.utils.timing import FpsMeter, RateLimiter, utcnow
from app.utils.video import VideoSource, backoff_delay

logger = get_logger(__name__)

EVENT_UPDATE_INTERVAL_S = 5.0


@dataclass
class PipelineMessage:
    """Something the persistence layer needs to know about."""

    kind: str  # "open" | "update" | "close" | "alert"
    camera_id: int
    payload: dict[str, Any] = field(default_factory=dict)
    snapshot: bytes | None = None


Publisher = Callable[[PipelineMessage], None]


class StreamWorker(threading.Thread):
    """Reads one stream, analyses it, and reports blockages."""

    def __init__(
        self,
        camera: CameraContext,
        source: str,
        publish: Publisher,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"worker-cam{camera.id}", daemon=True)
        self.camera = camera
        self.source = source
        self._publish = publish

        self.state: WorkerState = WorkerState.STOPPED
        self.error: str | None = None
        self.reconnects = 0
        self.frames_processed = 0
        self.current_event_id: int | None = None

        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._annotated: np.ndarray | None = None
        self._result: DetectionResult | None = None
        self._risk = risk.RiskAssessment(0.0, RiskLevel.LOW, "No action required")
        self._last_frame_at: datetime | None = None
        self._blocked_since_wall: datetime | None = None
        self._last_event_update = 0.0
        # Monotonic progress marker read by the manager's supervisor from
        # another thread. A blocked cv2.read() cannot notice its own stall, so
        # somebody outside this thread has to.
        self._last_progress_at = time.monotonic()

        self._fps = FpsMeter()
        self._temporal = TemporalFilter.for_camera(camera)
        self._policy = alerting.AlertPolicy()
        self._confidence = ConfidenceTracker()
        self._strategy = None  # built on the worker thread (model load is slow)

    # -- lifecycle --------------------------------------------------------
    def stop(self) -> None:
        self._stop_event.set()

    @property
    def stopping(self) -> bool:
        return self._stop_event.is_set()

    def update_camera(self, camera: CameraContext) -> None:
        """Apply edited camera settings without restarting the thread."""
        with self._lock:
            self.camera = camera
            self._temporal.confirm_seconds = camera.effective_confirm_seconds
            self._temporal.clear_seconds = camera.effective_clear_seconds

    @property
    def seconds_since_progress(self) -> float:
        """How long since a frame was last analysed. Safe to read cross-thread."""
        return time.monotonic() - self._last_progress_at

    # -- main loop --------------------------------------------------------
    def run(self) -> None:
        """Thread entrypoint. Nothing may escape here and kill the thread quietly.

        A worker that dies without recording why is invisible: the manager sees
        a missing thread and no reason, and the exit stops being monitored with
        nothing in the logs to explain it.
        """
        try:
            self._run()
        except Exception as exc:
            self.error = f"Worker crashed: {redact_text(str(exc))}"
            self.state = WorkerState.ERROR
            logger.exception("Camera %s: worker crashed", self.camera.id)
        else:
            self.state = WorkerState.STOPPED
        finally:
            self._close_open_event(reason="worker stopped")
            logger.info("Camera %s: worker exited (%s)", self.camera.id, self.state.value)

    def _run(self) -> None:  # noqa: C901 - the loop is linear, just long
        self.state = WorkerState.STARTING
        try:
            self._strategy = strategy_for_camera(self.camera, dedicated=True)
        except Exception as exc:
            raise RuntimeError(f"Could not initialise detector: {exc}") from exc

        limiter = RateLimiter(
            1.0 / self.camera.effective_process_fps
            if self.camera.effective_process_fps > 0
            else 0.0
        )
        video = VideoSource(self.source)
        try:
            self._capture_loop(video, limiter)
        finally:
            # Release even when the loop raises — a leaked VideoCapture holds
            # the RTSP connection open and the next attempt may be refused.
            video.release()

    def _capture_loop(self, video: VideoSource, limiter: RateLimiter) -> None:  # noqa: C901
        attempt = 0

        while not self.stopping:
            if not video.is_open:
                self.state = WorkerState.RECONNECTING if attempt else WorkerState.STARTING
                if not video.open():
                    attempt += 1
                    self.reconnects += 1
                    self.error = f"Cannot open source (attempt {attempt})"
                    delay = backoff_delay(attempt)
                    logger.warning(
                        "Camera %s: %s (%s) — retrying in %.1fs",
                        self.camera.id,
                        self.error,
                        redact_url(self.source),
                        delay,
                    )
                    if self._stop_event.wait(delay):
                        break
                    continue
                attempt = 0
                self._last_progress_at = time.monotonic()
                self.error = None
                self.state = WorkerState.RUNNING
                self._temporal.reset()
                if self._strategy is not None:
                    self._strategy.reset(self.camera.id)

            limiter.wait()
            if self.stopping:
                break

            video.drain()
            frame = video.read()
            if frame is None:
                # A live stream drops the odd frame; rebuilding the connection
                # for each one is expensive and throws away tracker state. Only
                # reconnect once nothing has arrived for STREAM_READ_TIMEOUT_S.
                # A file source that stops reading has simply ended.
                if video.is_file or video.is_stalled():
                    logger.info(
                        "Camera %s: stream ended or stalled after %.1fs",
                        self.camera.id,
                        video.seconds_since_frame,
                    )
                    video.release()
                    attempt += 1
                    self.reconnects += 1
                continue

            try:
                self._process(frame)
            except Exception as exc:
                self.error = redact_text(str(exc))
                logger.exception("Camera %s: frame processing failed", self.camera.id)

    # -- per-frame --------------------------------------------------------
    def _process(self, frame: np.ndarray) -> None:
        camera = self.camera
        result = self._strategy.analyze(frame, camera, track=settings.ENABLE_TRACKING)
        transition = self._temporal.update(result.raw_state)
        state = self._temporal.state
        duration = self._temporal.blocked_duration_s
        if transition.opened:
            self._confidence.reset()
        if self._temporal.blocked:
            self._confidence.sample(result.blocking_objects)

        assessment = risk.assess(
            state=state,
            accessibility_pct=result.accessibility_pct,
            blocked_duration_s=duration,
            blocking_objects=result.blocking_objects,
            people_count=result.people_count,
        )

        annotated = annotator.annotate(
            frame,
            result,
            state=state,
            camera_name=camera.name,
            risk_score=assessment.score,
            risk_level=assessment.level,
            blocked_duration_s=duration,
        )

        with self._lock:
            self._frame = frame
            self._annotated = annotated
            self._result = result
            self._risk = assessment
            self._last_frame_at = utcnow()
        self._fps.tick()
        self.frames_processed += 1
        self._last_progress_at = time.monotonic()
        self.error = None
        self.state = WorkerState.RUNNING

        self._handle_transition(transition, result, assessment, duration, annotated)
        self._maybe_alert(state, result, assessment, duration, annotated)

    def _handle_transition(
        self,
        transition,
        result: DetectionResult,
        assessment: risk.RiskAssessment,
        duration: float,
        annotated: np.ndarray,
    ) -> None:
        now = time.monotonic()

        if transition.opened:
            self._blocked_since_wall = utcnow()
            self._policy.reset()
            self._publish(
                PipelineMessage(
                    kind="open",
                    camera_id=self.camera.id,
                    payload=self._event_payload(result, assessment, duration),
                    snapshot=self._encode(annotated),
                )
            )
            self._last_event_update = now
            logger.info(
                "Camera %s: blockage OPENED (%s, %.1f%% accessible)",
                self.camera.id,
                transition.state.value,
                result.accessibility_pct,
            )
            return

        if transition.closed:
            self._publish(
                PipelineMessage(
                    kind="close",
                    camera_id=self.camera.id,
                    payload={
                        "event_id": self.current_event_id,
                        "duration_s": transition.duration_s,
                        "accessibility_pct": result.accessibility_pct,
                        **self._confidence.values,
                    },
                )
            )
            logger.info(
                "Camera %s: blockage CLEARED after %.1fs",
                self.camera.id,
                transition.duration_s,
            )
            self.current_event_id = None
            self._blocked_since_wall = None
            self._policy.reset()
            return

        due_for_update = now - self._last_event_update >= EVENT_UPDATE_INTERVAL_S
        if self._temporal.blocked and (transition.escalated or due_for_update):
            self._last_event_update = now
            self._publish(
                PipelineMessage(
                    kind="update",
                    camera_id=self.camera.id,
                    payload=self._event_payload(result, assessment, duration),
                )
            )

    def _maybe_alert(
        self,
        state: BlockageState,
        result: DetectionResult,
        assessment: risk.RiskAssessment,
        duration: float,
        annotated: np.ndarray,
    ) -> None:
        now = time.monotonic()
        if not self._policy.should_alert(state=state, duration_s=duration, now=now):
            return
        self._policy.mark_sent(state=state, now=now)
        payload = alerting.build_payload(
            camera_id=self.camera.id,
            camera_name=self.camera.name,
            location=self.camera.location,
            state=state,
            accessibility_pct=result.accessibility_pct,
            blocked_duration_s=duration,
            risk_score=assessment.score,
            risk_level=assessment.level.value,
            recommended_action=assessment.recommended_action,
            blocking_objects=[obj.model_dump() for obj in result.blocking_objects],
            strategy=result.strategy,
            event_id=self.current_event_id,
        )
        self._publish(
            PipelineMessage(
                kind="alert",
                camera_id=self.camera.id,
                payload={"alert": payload, "event_id": self.current_event_id},
                snapshot=self._encode(annotated),
            )
        )
        logger.warning(
            "Camera %s: ALERT %s blocked %.0fs risk %.0f",
            self.camera.id,
            state.value,
            duration,
            assessment.score,
        )

    def _event_payload(
        self, result: DetectionResult, assessment: risk.RiskAssessment, duration: float
    ) -> dict:
        return {
            "event_id": self.current_event_id,
            "state": self._temporal.state.value,
            "strategy": result.strategy,
            "accessibility_pct": result.accessibility_pct,
            "risk_score": assessment.score,
            "risk_level": assessment.level.value,
            "duration_s": duration,
            "blocking_objects": [obj.model_dump() for obj in result.blocking_objects],
            "started_at": self._blocked_since_wall or utcnow(),
            **self._confidence.values,
        }

    def _close_open_event(self, *, reason: str) -> None:
        if self.current_event_id is None:
            return
        self._publish(
            PipelineMessage(
                kind="close",
                camera_id=self.camera.id,
                payload={
                    "event_id": self.current_event_id,
                    "duration_s": self._temporal.blocked_duration_s,
                    "accessibility_pct": (
                        self._result.accessibility_pct if self._result else 0.0
                    ),
                    "reason": reason,
                },
            )
        )
        self.current_event_id = None

    @staticmethod
    def _encode(frame: np.ndarray) -> bytes | None:
        try:
            return encode_jpeg(frame)
        except Exception:  # pragma: no cover - defensive
            return None

    # -- read-side --------------------------------------------------------
    def snapshot(self, *, annotated: bool = True) -> np.ndarray | None:
        with self._lock:
            frame = self._annotated if annotated else self._frame
            return None if frame is None else frame.copy()

    def status(self) -> CameraStatus:
        with self._lock:
            result = self._result
            assessment = self._risk
            last_frame_at = self._last_frame_at
            blocked_since = self._blocked_since_wall
        state = self._temporal.state
        return CameraStatus(
            camera_id=self.camera.id,
            camera_name=self.camera.name,
            location=self.camera.location,
            worker_state=self.state,
            state=state,
            accessibility_pct=result.accessibility_pct if result else 100.0,
            occupied_pct=result.occupied_pct if result else 0.0,
            blocked=state.is_blocked(),
            blocked_since=blocked_since,
            blocked_duration_s=round(self._temporal.blocked_duration_s, 1),
            blocking_objects=result.blocking_objects if result else [],
            people_count=result.people_count if result else 0,
            risk_score=assessment.score,
            risk_level=assessment.level,
            recommended_action=assessment.recommended_action,
            strategy=result.strategy if result else self.camera.strategy,
            door_visible=result.door_visible if result else True,
            event_id=self.current_event_id,
            fps=round(self._fps.fps, 2),
            inference_ms=result.inference_ms if result else 0.0,
            last_frame_at=last_frame_at,
            frames_processed=self.frames_processed,
            reconnects=self.reconnects,
            error=self.error,
            warnings=result.warnings if result else [],
        )
