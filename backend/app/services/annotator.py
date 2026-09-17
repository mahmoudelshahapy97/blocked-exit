"""Explainable overlays: show exactly why the exit is considered blocked."""

from __future__ import annotations

import cv2
import numpy as np

from app.core.enums import BlockageState, RiskLevel
from app.schemas.detection import DetectionResult
from app.utils.geometry import denormalize_polygon

# BGR
_STATE_COLORS = {
    BlockageState.CLEAR: (80, 200, 80),
    BlockageState.PARTIAL: (0, 190, 255),
    BlockageState.FULL: (60, 60, 235),
    BlockageState.UNKNOWN: (170, 170, 170),
}
_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)
_FONT = cv2.FONT_HERSHEY_SIMPLEX


def annotate(
    frame: np.ndarray,
    result: DetectionResult,
    *,
    state: BlockageState | None = None,
    camera_name: str | None = None,
    risk_score: float | None = None,
    risk_level: RiskLevel | None = None,
    blocked_duration_s: float | None = None,
) -> np.ndarray:
    """Return a copy of `frame` with the door region, obstacles and verdict drawn."""
    canvas = frame.copy()
    effective_state = state or result.raw_state
    color = _STATE_COLORS.get(effective_state, _STATE_COLORS[BlockageState.UNKNOWN])

    _draw_door(canvas, result, color)
    _draw_obstacles(canvas, result)
    _draw_banner(
        canvas,
        result,
        effective_state,
        color,
        camera_name=camera_name,
        risk_score=risk_score,
        risk_level=risk_level,
        blocked_duration_s=blocked_duration_s,
    )
    return canvas


def _draw_door(canvas: np.ndarray, result: DetectionResult, color: tuple) -> None:
    if result.door_region:
        points = np.asarray(result.door_region, dtype=np.int32).reshape(-1, 1, 2)
        overlay = canvas.copy()
        cv2.fillPoly(overlay, [points], color)
        cv2.addWeighted(overlay, 0.18, canvas, 0.82, 0, canvas)
        cv2.polylines(canvas, [points], True, color, 2, cv2.LINE_AA)

    # Door-centric: reference outline (dashed look) vs currently visible door.
    if result.reference_bbox:
        x1, y1, x2, y2 = (int(v) for v in result.reference_bbox)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (200, 200, 200), 1, cv2.LINE_AA)
        _label(canvas, "reference door", (x1, max(12, y1 - 6)), (200, 200, 200))
    if result.door_bbox:
        x1, y1, x2, y2 = (int(v) for v in result.door_bbox)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
        _label(canvas, "visible door", (x1, min(canvas.shape[0] - 4, y2 + 16)), color)


def _draw_obstacles(canvas: np.ndarray, result: DetectionResult) -> None:
    for obj in result.blocking_objects:
        if not obj.bbox or len(obj.bbox) != 4:
            continue
        x1, y1, x2, y2 = (int(v) for v in obj.bbox)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (235, 190, 60), 2, cv2.LINE_AA)
        tag = obj.label
        if obj.track_id is not None:
            tag += f" #{obj.track_id}"
        tag += f" {obj.area_pct:.0f}%"
        _label(canvas, tag, (x1, max(12, y1 - 6)), (235, 190, 60))


def _label(canvas: np.ndarray, text: str, origin: tuple[int, int], color: tuple) -> None:
    x, y = origin
    (width, height), _ = cv2.getTextSize(text, _FONT, 0.45, 1)
    cv2.rectangle(canvas, (x, y - height - 4), (x + width + 6, y + 3), color, -1)
    cv2.putText(canvas, text, (x + 3, y - 2), _FONT, 0.45, _BLACK, 1, cv2.LINE_AA)


def _draw_banner(
    canvas: np.ndarray,
    result: DetectionResult,
    state: BlockageState,
    color: tuple,
    *,
    camera_name: str | None,
    risk_score: float | None,
    risk_level: RiskLevel | None,
    blocked_duration_s: float | None,
) -> None:
    height, width = canvas.shape[:2]
    banner_h = 64
    overlay = canvas.copy()
    cv2.rectangle(overlay, (0, 0), (width, banner_h), _BLACK, -1)
    cv2.addWeighted(overlay, 0.55, canvas, 0.45, 0, canvas)
    cv2.rectangle(canvas, (0, 0), (10, banner_h), color, -1)

    headline = f"{state.value}  |  ACCESSIBLE {result.accessibility_pct:.1f}%"
    cv2.putText(canvas, headline, (22, 28), _FONT, 0.75, color, 2, cv2.LINE_AA)

    details: list[str] = []
    if camera_name:
        details.append(camera_name)
    if blocked_duration_s:
        details.append(f"blocked {blocked_duration_s:.0f}s")
    if risk_score is not None:
        level = f" ({risk_level.value})" if risk_level else ""
        details.append(f"risk {risk_score:.0f}/100{level}")
    if result.blocking_objects:
        labels = ", ".join(
            dict.fromkeys(obj.label for obj in result.blocking_objects[:4])
        )
        details.append(f"by {labels}")
    details.append(result.strategy)

    cv2.putText(
        canvas, "  |  ".join(details), (22, 52), _FONT, 0.48, _WHITE, 1, cv2.LINE_AA
    )


def draw_zone(
    frame: np.ndarray,
    polygon: list[list[float]] | None,
    *,
    caption: str | None = None,
) -> np.ndarray:
    """Draw a normalized [0,1] polygon over a frame — the calibration preview.

    Answers the only question that matters after drawing a region: *is this
    exactly the area the detector will measure?* Rendering it server-side from
    the stored coordinates proves the round trip, which a client-side canvas
    redraw of its own points cannot.
    """
    canvas = frame.copy()
    height, width = canvas.shape[:2]
    color = _STATE_COLORS[BlockageState.PARTIAL]

    if polygon:
        points = denormalize_polygon(polygon, width, height).reshape(-1, 1, 2)
        overlay = canvas.copy()
        cv2.fillPoly(overlay, [points], color)
        cv2.addWeighted(overlay, 0.25, canvas, 0.75, 0, canvas)
        cv2.polylines(canvas, [points], True, color, 2, cv2.LINE_AA)
        for index, point in enumerate(points.reshape(-1, 2)):
            centre = (int(point[0]), int(point[1]))
            cv2.circle(canvas, centre, 5, _WHITE, -1, cv2.LINE_AA)
            cv2.circle(canvas, centre, 5, color, 2, cv2.LINE_AA)
            _label(canvas, str(index + 1), (centre[0] + 8, centre[1] - 4), color)
    else:
        _label(
            canvas,
            "no door polygon set - the whole frame is treated as the exit",
            (12, 24),
            (170, 170, 170),
        )

    if caption:
        _label(canvas, caption, (12, height - 12), color)
    return canvas


def placeholder(text: str, width: int = 960, height: int = 540) -> np.ndarray:
    """Grey frame with a message, used when no frame is available yet."""
    canvas = np.full((height, width, 3), 40, dtype=np.uint8)
    (text_w, _), _ = cv2.getTextSize(text, _FONT, 0.7, 2)
    cv2.putText(
        canvas,
        text,
        ((width - text_w) // 2, height // 2),
        _FONT,
        0.7,
        (200, 200, 200),
        2,
        cv2.LINE_AA,
    )
    return canvas
