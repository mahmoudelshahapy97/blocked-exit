"""Image encoding helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

from app.core.config import settings


def encode_jpeg(frame: np.ndarray, quality: int | None = None) -> bytes:
    """Encode a BGR frame to JPEG bytes."""
    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality or settings.JPEG_QUALITY]
    ok, buffer = cv2.imencode(".jpg", frame, params)
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buffer.tobytes()


def decode_image(data: bytes) -> np.ndarray | None:
    array = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(array, cv2.IMREAD_COLOR)


def save_snapshot(frame: np.ndarray, camera_id: int, tag: str = "event") -> str:
    """Persist a frame under SNAPSHOT_DIR and return its path."""
    directory = Path(settings.SNAPSHOT_DIR) / f"camera_{camera_id}"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    path = directory / f"{tag}_{stamp}.jpg"
    path.write_bytes(encode_jpeg(frame))
    return str(path)


def mjpeg_part(jpeg: bytes) -> bytes:
    """Wrap JPEG bytes in a multipart/x-mixed-replace chunk."""
    return (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
    )
