"""RTSP / video capture with reconnect and stale-frame dropping."""

from __future__ import annotations

import os
import time
from pathlib import Path

import cv2
import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redaction import redact_url

logger = get_logger(__name__)


def configure_ffmpeg_transport() -> None:
    """Force TCP for RTSP — UDP drops frames badly on busy networks.

    Must be set before the first VideoCapture is created.
    """
    os.environ.setdefault(
        "OPENCV_FFMPEG_CAPTURE_OPTIONS",
        f"rtsp_transport;{settings.RTSP_TRANSPORT}|stimeout;5000000",
    )


def is_file_source(source: str) -> bool:
    """True when the source is a local video file rather than a live stream."""
    lowered = source.lower()
    if lowered.startswith(("rtsp://", "rtmp://", "http://", "https://", "udp://")):
        return False
    if source.isdigit():  # webcam index
        return False
    return Path(source).exists()


class VideoSource:
    """A resilient capture wrapper.

    Live streams are read with grab/retrieve so the worker always analyses the
    most recent frame instead of falling behind a buffered queue. Local files
    are read frame by frame (and optionally looped) so test clips play at their
    natural pace.
    """

    def __init__(self, source: str, *, loop_files: bool | None = None) -> None:
        configure_ffmpeg_transport()
        self.source = source
        self.is_file = is_file_source(source)
        self.loop_files = settings.LOOP_VIDEO_FILES if loop_files is None else loop_files
        self._cap: cv2.VideoCapture | None = None
        self._last_frame_at: float = 0.0
        self.reconnects = 0

    # -- lifecycle --------------------------------------------------------
    def open(self) -> bool:
        self.release()
        target: str | int = int(self.source) if self.source.isdigit() else self.source
        cap = cv2.VideoCapture(target)
        if not self.is_file:
            # Keep the internal buffer tiny so frames stay fresh.
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            cap.release()
            logger.warning("Could not open video source: %s", redact_url(self.source))
            return False
        self._cap = cap
        self._last_frame_at = time.monotonic()
        return True

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    @property
    def fps(self) -> float:
        if self._cap is None:
            return 0.0
        value = self._cap.get(cv2.CAP_PROP_FPS)
        return float(value) if value and value > 0 else 0.0

    # -- reading ----------------------------------------------------------
    def read(self) -> np.ndarray | None:
        """Return the newest frame, or None when the source needs reopening."""
        if self._cap is None:
            return None

        ok, frame = self._cap.read()
        if not ok or frame is None:
            if self.is_file and self.loop_files:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
                if ok and frame is not None:
                    self._last_frame_at = time.monotonic()
                    return frame
            return None

        self._last_frame_at = time.monotonic()
        return frame

    def drain(self, max_frames: int = 8) -> None:
        """Discard buffered frames on a live stream to catch up to real time."""
        if self._cap is None or self.is_file:
            return
        for _ in range(max_frames):
            if not self._cap.grab():
                break

    @property
    def seconds_since_frame(self) -> float:
        if self._last_frame_at == 0.0:
            return 0.0
        return time.monotonic() - self._last_frame_at

    def is_stalled(self) -> bool:
        return self.seconds_since_frame > settings.STREAM_READ_TIMEOUT_S

    def __enter__(self) -> VideoSource:
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


def grab_single_frame(source: str, *, retries: int = 3) -> np.ndarray | None:
    """Open a source, take one frame, close it. Used for calibration."""
    for attempt in range(retries):
        with VideoSource(source) as video:
            if not video.is_open:
                time.sleep(0.5 * (attempt + 1))
                continue
            if not video.is_file:
                video.drain(4)
            frame = video.read()
            if frame is not None:
                return frame
        time.sleep(0.5 * (attempt + 1))
    return None


def backoff_delay(attempt: int) -> float:
    """Exponential backoff between reconnect attempts, capped by settings."""
    delay = settings.STREAM_RECONNECT_BASE_S * (2 ** max(0, attempt - 1))
    return min(delay, settings.STREAM_RECONNECT_MAX_S)
