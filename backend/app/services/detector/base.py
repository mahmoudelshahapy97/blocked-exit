"""The contract every blockage-detection strategy implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np

from app.core.config import settings
from app.core.enums import BlockageState
from app.schemas.detection import DetectionResult


@dataclass
class CameraContext:
    """Everything a strategy needs to know about the camera it is analysing.

    Detached from the ORM on purpose: strategies run on worker threads, where
    touching a lazily-loaded SQLAlchemy object would be unsafe.
    """

    id: int
    name: str
    location: str | None = None
    strategy: str = "zone_based"
    door_polygon: list[list[float]] | None = None
    reference_bbox: list[float] | None = None
    clear_min_pct: float | None = None
    full_max_pct: float | None = None
    confirm_seconds: float | None = None
    clear_seconds: float | None = None
    process_fps: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_orm(cls, camera: Any) -> CameraContext:
        return cls(
            id=camera.id,
            name=camera.name,
            location=camera.location,
            strategy=camera.strategy,
            door_polygon=camera.door_polygon,
            reference_bbox=camera.reference_bbox,
            clear_min_pct=camera.clear_min_pct,
            full_max_pct=camera.full_max_pct,
            confirm_seconds=camera.confirm_seconds,
            clear_seconds=camera.clear_seconds,
            process_fps=camera.process_fps,
        )

    # -- effective thresholds (camera override -> global default) ---------
    @property
    def effective_clear_min_pct(self) -> float:
        return (
            self.clear_min_pct
            if self.clear_min_pct is not None
            else settings.CLEAR_MIN_PCT
        )

    @property
    def effective_full_max_pct(self) -> float:
        return (
            self.full_max_pct if self.full_max_pct is not None else settings.FULL_MAX_PCT
        )

    @property
    def effective_confirm_seconds(self) -> float:
        return (
            self.confirm_seconds
            if self.confirm_seconds is not None
            else settings.CONFIRM_SECONDS
        )

    @property
    def effective_clear_seconds(self) -> float:
        return (
            self.clear_seconds
            if self.clear_seconds is not None
            else settings.CLEAR_SECONDS
        )

    @property
    def effective_process_fps(self) -> float:
        return self.process_fps if self.process_fps is not None else settings.PROCESS_FPS


def classify(accessibility_pct: float, camera: CameraContext) -> BlockageState:
    """Map an accessibility percentage onto CLEAR / PARTIAL / FULL."""
    if accessibility_pct >= camera.effective_clear_min_pct:
        return BlockageState.CLEAR
    if accessibility_pct < camera.effective_full_max_pct:
        return BlockageState.FULL
    return BlockageState.PARTIAL


@runtime_checkable
class BlockageStrategy(Protocol):
    """Analyse one frame and report how accessible the exit is."""

    name: str

    def analyze(
        self, frame: np.ndarray, camera: CameraContext, *, track: bool = True
    ) -> DetectionResult: ...

    def is_available(self) -> bool: ...

    def reset(self, camera_id: int) -> None: ...


class BaseStrategy:
    """Shared plumbing for strategies (per-camera state, availability)."""

    name = "base"

    def is_available(self) -> bool:
        return True

    def reset(self, camera_id: int) -> None:  # pragma: no cover - default no-op
        return None
