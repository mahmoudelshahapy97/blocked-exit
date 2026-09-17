"""Detection / verdict schemas — the core output of the pipeline."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import BlockageState, RiskLevel, WorkerState


class BlockingObject(BaseModel):
    """One obstacle overlapping the exit region."""

    label: str
    class_id: int | None = None
    confidence: float
    track_id: int | None = None
    bbox: list[float] = Field(default_factory=list, description="[x1, y1, x2, y2] px")
    area_pct: float = Field(
        0.0, description="Percent of the exit region this object covers"
    )


class DetectionResult(BaseModel):
    """Raw per-frame analysis produced by a BlockageStrategy."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    accessibility_pct: float = Field(100.0, ge=0.0, le=100.0)
    occupied_pct: float = Field(0.0, ge=0.0, le=100.0)
    raw_state: BlockageState = BlockageState.CLEAR
    blocking_objects: list[BlockingObject] = Field(default_factory=list)
    people_count: int = 0
    door_region: list[list[float]] | None = Field(
        None, description="Exit polygon in pixel coordinates"
    )
    door_bbox: list[float] | None = None
    reference_bbox: list[float] | None = None
    door_visible: bool = True
    strategy: str = "zone_based"
    inference_ms: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class CameraStatus(BaseModel):
    """Live verdict for one camera, as served by /monitoring/{id}/status."""

    camera_id: int
    camera_name: str
    location: str | None = None
    worker_state: WorkerState = WorkerState.STOPPED

    state: BlockageState = BlockageState.UNKNOWN
    accessibility_pct: float = 100.0
    occupied_pct: float = 0.0
    blocked: bool = False
    blocked_since: datetime | None = None
    blocked_duration_s: float = 0.0

    blocking_objects: list[BlockingObject] = Field(default_factory=list)
    people_count: int = 0

    risk_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW
    recommended_action: str = "No action required"

    strategy: str = "zone_based"
    door_visible: bool = True
    event_id: int | None = None

    fps: float = 0.0
    inference_ms: float = 0.0
    last_frame_at: datetime | None = None
    frames_processed: int = 0
    reconnects: int = 0
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class MonitoringActionResponse(BaseModel):
    camera_id: int
    worker_state: WorkerState
    message: str
