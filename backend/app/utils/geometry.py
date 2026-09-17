"""Geometry helpers for exit-region occupancy math.

Occupancy is computed on rasterized masks rather than bounding-box IoU so that
a partially obstructing object contributes only the area it actually covers —
this is what makes the accessibility percentage meaningful.
"""

from __future__ import annotations

import cv2
import numpy as np

Polygon = list[list[float]]
BBox = list[float] | tuple[float, float, float, float]


def denormalize_polygon(polygon: Polygon, width: int, height: int) -> np.ndarray:
    """Convert a normalized [0,1] polygon to integer pixel coordinates."""
    points = np.asarray(polygon, dtype=np.float32)
    points[:, 0] *= width
    points[:, 1] *= height
    return np.round(points).astype(np.int32)


def normalize_polygon(polygon: Polygon, width: int, height: int) -> Polygon:
    """Convert a pixel-space polygon to normalized [0,1] coordinates.

    The inverse of :func:`denormalize_polygon`. Points are clamped rather than
    rejected: a click one pixel outside the frame is an operator's aim, not an
    error worth failing a calibration on.
    """
    if width <= 0 or height <= 0:
        raise ValueError("frame_width and frame_height must be positive")
    return [
        [
            clamp(float(x) / width, 0.0, 1.0),
            clamp(float(y) / height, 0.0, 1.0),
        ]
        for x, y in polygon
    ]


def normalize_bbox(bbox: BBox, width: int, height: int) -> list[float]:
    x1, y1, x2, y2 = bbox
    return [x1 / width, y1 / height, x2 / width, y2 / height]


def denormalize_bbox(bbox: BBox, width: int, height: int) -> list[float]:
    x1, y1, x2, y2 = bbox
    return [x1 * width, y1 * height, x2 * width, y2 * height]


def polygon_to_mask(polygon: Polygon, width: int, height: int) -> np.ndarray:
    """Rasterize a normalized polygon into a uint8 {0,1} mask."""
    mask = np.zeros((height, width), dtype=np.uint8)
    points = denormalize_polygon(polygon, width, height)
    cv2.fillPoly(mask, [points], 1)
    return mask


def full_frame_polygon() -> Polygon:
    """Fallback exit region when no polygon has been configured."""
    return [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def bbox_to_mask(bbox: BBox, width: int, height: int) -> np.ndarray:
    """Rasterize a pixel-space bbox into a uint8 {0,1} mask."""
    mask = np.zeros((height, width), dtype=np.uint8)
    x1, y1, x2, y2 = (int(round(v)) for v in bbox)
    x1 = max(0, min(x1, width))
    x2 = max(0, min(x2, width))
    y1 = max(0, min(y1, height))
    y2 = max(0, min(y2, height))
    if x2 > x1 and y2 > y1:
        mask[y1:y2, x1:x2] = 1
    return mask


def resize_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize a binary mask to the target frame size (nearest neighbour)."""
    if mask.shape[:2] == (height, width):
        return mask.astype(np.uint8)
    resized = cv2.resize(
        mask.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST
    )
    return (resized > 0).astype(np.uint8)


def mask_area(mask: np.ndarray) -> int:
    return int(np.count_nonzero(mask))


def intersection_ratio(region: np.ndarray, obstacle: np.ndarray) -> float:
    """Fraction of `region` covered by `obstacle`, in [0, 1]."""
    region_area = mask_area(region)
    if region_area == 0:
        return 0.0
    overlap = mask_area(cv2.bitwise_and(region, obstacle))
    return overlap / region_area


def occupancy(region: np.ndarray, obstacles: list[np.ndarray]) -> float:
    """Fraction of `region` covered by the union of `obstacles`, in [0, 1].

    Uses the union so two overlapping obstacles are never double counted.
    """
    if not obstacles:
        return 0.0
    union = obstacles[0].copy()
    for mask in obstacles[1:]:
        union = cv2.bitwise_or(union, mask)
    return intersection_ratio(region, union)


def bbox_area(bbox: BBox) -> float:
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def bbox_iou(a: BBox, b: BBox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = bbox_area(a) + bbox_area(b) - inter
    return inter / union if union > 0 else 0.0


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))
