"""Zone-based blockage detection.

A pretrained YOLO11 model detects obstacles; whatever overlaps the operator's
door polygon reduces the accessible area. Works from day one with COCO weights
and no training, and names the objects responsible for the blockage.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.detection import BlockingObject, DetectionResult
from app.services import model_loader
from app.services.detector.base import BaseStrategy, CameraContext, classify
from app.utils.geometry import (
    bbox_to_mask,
    clamp,
    denormalize_polygon,
    full_frame_polygon,
    intersection_ratio,
    mask_area,
    occupancy,
    polygon_to_mask,
    resize_mask,
)
from app.utils.timing import Stopwatch

logger = get_logger(__name__)

PERSON_CLASS_ID = 0


class ZoneBasedStrategy(BaseStrategy):
    name = "zone_based"

    def __init__(self, *, dedicated: bool = False, weights: str | None = None) -> None:
        self._dedicated = dedicated
        self._weights = weights or model_loader.detection_weights()
        self._model: Any | None = None
        self._names: dict[int, str] = {}
        self._load_error: str | None = None

    # -- model ------------------------------------------------------------
    @property
    def model(self) -> Any:
        if self._model is None:
            self._model = (
                model_loader.load_model(self._weights)
                if self._dedicated
                else model_loader.get_shared_model(self._weights)
            )
            self._names = model_loader.class_names(self._model)
        return self._model

    def is_available(self) -> bool:
        try:
            _ = self.model
            return True
        except Exception as exc:
            self._load_error = str(exc)
            return False

    def reset(self, camera_id: int) -> None:
        """Drop tracker state (used when a stream reconnects)."""
        if self._model is not None:
            try:
                self._model.predictor = None  # ultralytics rebuilds it on next call
            except Exception:  # pragma: no cover - defensive
                pass

    # -- inference --------------------------------------------------------
    def analyze(
        self, frame: np.ndarray, camera: CameraContext, *, track: bool = True
    ) -> DetectionResult:
        height, width = frame.shape[:2]
        warnings: list[str] = []

        polygon = camera.door_polygon
        if not polygon:
            polygon = full_frame_polygon()
            warnings.append(
                "No door polygon configured — analysing the whole frame. "
                "Set one via PUT /cameras/{id}/door-polygon."
            )

        door_mask = polygon_to_mask(polygon, width, height)
        door_area = mask_area(door_mask)
        if door_area == 0:
            warnings.append("Door polygon has zero area in pixel space.")
            return DetectionResult(
                accessibility_pct=100.0,
                occupied_pct=0.0,
                raw_state=classify(100.0, camera),
                strategy=self.name,
                door_region=denormalize_polygon(polygon, width, height).tolist(),
                warnings=warnings,
            )

        with Stopwatch() as watch:
            result = self._infer(frame, track=track)

        obstacles: list[BlockingObject] = []
        masks: list[np.ndarray] = []
        people_count = 0

        if result is not None:
            masks, obstacles, people_count = self._extract(
                result, frame_shape=(height, width), door_mask=door_mask
            )

        occupied = occupancy(door_mask, masks) * 100.0
        accessibility = clamp(100.0 - occupied)

        return DetectionResult(
            accessibility_pct=round(accessibility, 2),
            occupied_pct=round(clamp(occupied), 2),
            raw_state=classify(accessibility, camera),
            blocking_objects=obstacles,
            people_count=people_count,
            door_region=denormalize_polygon(polygon, width, height).tolist(),
            strategy=self.name,
            inference_ms=round(watch.elapsed_ms, 2),
            warnings=warnings,
        )

    def _infer(self, frame: np.ndarray, *, track: bool) -> Any | None:
        classes = settings.OBSTACLE_CLASSES or None
        kwargs = {
            "imgsz": settings.IMG_SIZE,
            "conf": settings.CONF_THRESHOLD,
            "iou": settings.IOU_THRESHOLD,
            "device": settings.DEVICE,
            "classes": classes,
            "verbose": False,
        }
        try:
            if track and settings.ENABLE_TRACKING:
                results = self.model.track(
                    frame, persist=True, tracker=settings.TRACKER, **kwargs
                )
            else:
                results = self.model.predict(frame, **kwargs)
        except Exception as exc:
            logger.warning("Inference failed: %s", exc)
            return None
        return results[0] if results else None

    def _extract(
        self,
        result: Any,
        *,
        frame_shape: tuple[int, int],
        door_mask: np.ndarray,
    ) -> tuple[list[np.ndarray], list[BlockingObject], int]:
        height, width = frame_shape
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return [], [], 0

        names = self._names or model_loader.class_names(self.model)
        seg_masks = self._segmentation_masks(result, width, height)

        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        class_ids = boxes.cls.cpu().numpy().astype(int)
        track_ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else None

        masks: list[np.ndarray] = []
        obstacles: list[BlockingObject] = []
        people_count = 0

        for index in range(len(xyxy)):
            mask = (
                seg_masks[index]
                if seg_masks is not None and index < len(seg_masks)
                else bbox_to_mask(xyxy[index], width, height)
            )
            coverage = intersection_ratio(door_mask, mask)
            if coverage <= 0:
                continue  # object is nowhere near the exit

            class_id = int(class_ids[index])
            if class_id == PERSON_CLASS_ID:
                people_count += 1

            masks.append(mask)
            obstacles.append(
                BlockingObject(
                    label=names.get(class_id, str(class_id)),
                    class_id=class_id,
                    confidence=round(float(confs[index]), 3),
                    track_id=int(track_ids[index]) if track_ids is not None else None,
                    bbox=[round(float(v), 1) for v in xyxy[index]],
                    area_pct=round(coverage * 100.0, 2),
                )
            )

        obstacles.sort(key=lambda item: item.area_pct, reverse=True)
        return masks, obstacles, people_count

    @staticmethod
    def _segmentation_masks(
        result: Any, width: int, height: int
    ) -> list[np.ndarray] | None:
        """Per-object binary masks at frame resolution, when the model is a
        segmentation model. Falls back to None so boxes are used instead."""
        masks = getattr(result, "masks", None)
        if masks is None or masks.data is None:
            return None
        try:
            data = masks.data.cpu().numpy()
        except Exception:  # pragma: no cover - defensive
            return None
        return [resize_mask(item > 0.5, width, height) for item in data]
