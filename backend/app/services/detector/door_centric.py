"""Door-centric change monitoring.

Implements the ICAART 2026 method (Talebi et al., *Real Time Exit Blockage
Detection via Door-Centric Change Monitoring for Emergency Evacuation*, §3 and
§4.3.2): rather than cataloguing every possible obstacle, a door-only detector
reports the *visible* door region, and

    accessible % = area(current door bbox) / area(reference unobstructed bbox)

Because nothing about the obstacle is modelled, the method generalises to
obstruction types never seen in training.

Requires door weights (``DOOR_MODEL_PATH``) and a per-camera reference bbox
captured from an unobstructed frame via ``POST /cameras/{id}/reference``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.core.config import settings
from app.core.enums import BlockageState
from app.core.logging import get_logger
from app.schemas.detection import DetectionResult
from app.services import model_loader
from app.services.detector.base import BaseStrategy, CameraContext, classify
from app.services.detector.zone_based import ZoneBasedStrategy
from app.utils.geometry import bbox_area, clamp, denormalize_bbox, normalize_bbox
from app.utils.timing import Stopwatch

logger = get_logger(__name__)


class DoorCentricStrategy(BaseStrategy):
    name = "door_centric"

    def __init__(self, *, dedicated: bool = False, weights: str | None = None) -> None:
        self._dedicated = dedicated
        self._weights = weights or model_loader.door_weights()
        self._model: Any | None = None
        self._names: dict[int, str] = {}
        self._explainer: ZoneBasedStrategy | None = None

    # -- model ------------------------------------------------------------
    @property
    def model(self) -> Any:
        if self._model is None:
            if not self._weights:
                raise RuntimeError(
                    "DOOR_MODEL_PATH is not configured — door-centric detection "
                    "needs door weights."
                )
            self._model = (
                model_loader.load_model(self._weights)
                if self._dedicated
                else model_loader.get_shared_model(self._weights)
            )
            self._names = model_loader.class_names(self._model)
        return self._model

    def is_available(self) -> bool:
        if not self._weights:
            return False
        try:
            _ = self.model
            return True
        except Exception as exc:
            logger.warning("Door model unavailable: %s", exc)
            return False

    def reset(self, camera_id: int) -> None:
        if self._explainer is not None:
            self._explainer.reset(camera_id)

    # -- inference --------------------------------------------------------
    def analyze(
        self, frame: np.ndarray, camera: CameraContext, *, track: bool = True
    ) -> DetectionResult:
        height, width = frame.shape[:2]
        warnings: list[str] = []

        if not camera.reference_bbox:
            warnings.append(
                "No reference door captured — POST /cameras/"
                f"{camera.id}/reference on an unobstructed view first."
            )
            return DetectionResult(
                accessibility_pct=100.0,
                raw_state=BlockageState.UNKNOWN,
                strategy=self.name,
                door_visible=False,
                warnings=warnings,
            )

        with Stopwatch() as watch:
            detection = self.detect_door(frame)

        reference_px = denormalize_bbox(camera.reference_bbox, width, height)

        if detection is None:
            # The door is not detectable at all: either fully obscured or the
            # camera moved. Treated as fully blocked, flagged for review.
            warnings.append("Door not detected in the current frame.")
            return DetectionResult(
                accessibility_pct=0.0,
                occupied_pct=100.0,
                raw_state=BlockageState.FULL,
                strategy=self.name,
                door_visible=False,
                reference_bbox=[round(v, 1) for v in reference_px],
                inference_ms=round(watch.elapsed_ms, 2),
                warnings=warnings,
            )

        bbox_px, confidence = detection
        reference_area = bbox_area(reference_px)
        if reference_area <= 0:
            warnings.append("Reference bbox has zero area — recapture it.")
            return DetectionResult(
                accessibility_pct=100.0,
                raw_state=BlockageState.UNKNOWN,
                strategy=self.name,
                warnings=warnings,
            )

        del confidence  # localisation quality, not part of the verdict
        ratio = bbox_area(bbox_px) / reference_area
        accessibility = clamp(ratio * 100.0)

        result = DetectionResult(
            accessibility_pct=round(accessibility, 2),
            occupied_pct=round(clamp(100.0 - accessibility), 2),
            raw_state=classify(accessibility, camera),
            door_bbox=[round(v, 1) for v in bbox_px],
            reference_bbox=[round(v, 1) for v in reference_px],
            door_visible=True,
            strategy=self.name,
            inference_ms=round(watch.elapsed_ms, 2),
            warnings=warnings,
        )

        if settings.DOOR_CENTRIC_EXPLAIN and result.raw_state.is_blocked():
            self._explain(frame, camera, result, track=track)
        return result

    def detect_door(self, frame: np.ndarray) -> tuple[list[float], float] | None:
        """Highest-confidence door box in pixel coordinates."""
        try:
            results = self.model.predict(
                frame,
                imgsz=settings.IMG_SIZE,
                conf=settings.CONF_THRESHOLD,
                iou=settings.IOU_THRESHOLD,
                device=settings.DEVICE,
                verbose=False,
            )
        except Exception as exc:
            logger.warning("Door inference failed: %s", exc)
            return None

        if not results:
            return None
        boxes = getattr(results[0], "boxes", None)
        if boxes is None or len(boxes) == 0:
            return None

        confs = boxes.conf.cpu().numpy()
        best = int(confs.argmax())
        xyxy = boxes.xyxy.cpu().numpy()[best]
        return [float(v) for v in xyxy], float(confs[best])

    def _explain(
        self,
        frame: np.ndarray,
        camera: CameraContext,
        result: DetectionResult,
        *,
        track: bool,
    ) -> None:
        """Attach a human-readable obstacle list without changing the verdict."""
        if self._explainer is None:
            self._explainer = ZoneBasedStrategy(dedicated=self._dedicated)
            if not self._explainer.is_available():
                self._explainer = None
                return
        try:
            # Restrict the explainer to the reference door area so it reports
            # what is actually in front of this door.
            context = CameraContext(
                id=camera.id,
                name=camera.name,
                door_polygon=_bbox_to_polygon(camera.reference_bbox),
            )
            explanation = self._explainer.analyze(frame, context, track=track)
            result.blocking_objects = explanation.blocking_objects
            result.people_count = explanation.people_count
        except Exception as exc:  # pragma: no cover - explanation is optional
            logger.debug("Explainer failed: %s", exc)


def _bbox_to_polygon(bbox: list[float] | None) -> list[list[float]] | None:
    if not bbox:
        return None
    x1, y1, x2, y2 = bbox
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def capture_reference(frame: np.ndarray) -> tuple[list[float], float] | None:
    """Detect the unobstructed door and return its normalized bbox.

    Used by the calibration endpoint; deliberately module level so the route
    does not need a worker.
    """
    strategy = DoorCentricStrategy()
    if not strategy.is_available():
        return None
    detection = strategy.detect_door(frame)
    if detection is None:
        return None

    bbox_px, confidence = detection
    height, width = frame.shape[:2]
    return normalize_bbox(bbox_px, width, height), confidence
