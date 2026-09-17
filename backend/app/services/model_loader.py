"""YOLO model loading.

Two access patterns:

* :func:`get_shared_model` — one process-wide instance per weights file, used
  for stateless one-off inference (calibration, snapshots).
* :func:`load_model` — a *fresh* instance, used by stream workers. Ultralytics
  keeps ByteTrack state on the model object when ``track(persist=True)`` is
  used, so two cameras sharing one instance would corrupt each other's track
  ids. One instance per worker keeps tracking correct.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.exceptions import ModelNotAvailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

_shared: dict[str, Any] = {}
_lock = threading.Lock()
_names_cache: dict[str, dict[int, str]] = {}


def _import_yolo():
    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ModelNotAvailableError(
            "ultralytics is not installed. Run: pip install -r requirements.txt"
        ) from exc
    return YOLO


def load_model(weights: str) -> Any:
    """Load a fresh YOLO instance (own tracker state)."""
    YOLO = _import_yolo()
    resolved = settings.resolve_model(weights)
    if resolved is None:
        raise ModelNotAvailableError(f"No weights configured for {weights!r}")
    logger.info("Loading YOLO weights: %s (device=%s)", resolved, settings.DEVICE)
    try:
        model = YOLO(resolved)
    except Exception as exc:
        raise ModelNotAvailableError(
            f"Could not load weights {resolved!r}: {exc}"
        ) from exc
    _names_cache[resolved] = dict(getattr(model, "names", {}) or {})
    return model


def get_shared_model(weights: str) -> Any:
    """Return the process-wide instance for these weights, loading on first use."""
    resolved = settings.resolve_model(weights) or weights
    model = _shared.get(resolved)
    if model is not None:
        return model
    with _lock:
        model = _shared.get(resolved)
        if model is None:
            model = load_model(weights)
            _shared[resolved] = model
        return model


def detection_weights() -> str:
    """Weights used for obstacle detection (segmentation when enabled)."""
    if settings.USE_SEGMENTATION and settings.SEG_MODEL_PATH:
        return settings.SEG_MODEL_PATH
    return settings.MODEL_PATH


def door_weights() -> str | None:
    return settings.DOOR_MODEL_PATH


def class_names(model: Any) -> dict[int, str]:
    return dict(getattr(model, "names", {}) or {})


def warmup(model: Any) -> None:
    """Run one dummy inference so the first real frame is not slow."""
    try:
        blank = np.zeros((settings.IMG_SIZE, settings.IMG_SIZE, 3), dtype=np.uint8)
        model.predict(
            blank,
            imgsz=settings.IMG_SIZE,
            device=settings.DEVICE,
            verbose=False,
        )
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Model warmup failed: %s", exc)


def preload() -> dict[str, bool]:
    """Load configured models at startup. Never raises — reports per-model status."""
    status: dict[str, bool] = {}
    for label, weights in (
        ("detection", detection_weights()),
        ("door", door_weights()),
    ):
        if not weights:
            status[label] = False
            continue
        try:
            model = get_shared_model(weights)
            warmup(model)
            status[label] = True
        except Exception as exc:
            logger.warning("Could not preload %s model (%s): %s", label, weights, exc)
            status[label] = False
    return status


def loaded_models() -> list[str]:
    return sorted(_shared.keys())
