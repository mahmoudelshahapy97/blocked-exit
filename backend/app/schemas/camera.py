"""Camera request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import StrategyName
from app.core.redaction import redact_url
from app.utils.geometry import normalize_polygon

Polygon = list[list[float]]

HIERARCHY_FIELDS = ("location", "area", "building", "floor_level", "zone")


def _blank_to_none(value: str | None) -> str | None:
    """"  " and "" mean "not set": an empty level would otherwise show up in the
    hierarchy filters as a blank option nobody can tell apart."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _looks_like_pixels(value: Polygon) -> bool:
    """Coordinates above 1.0 can only be pixels — [0,1] is the stored form."""
    return any(coord > 1.0 for point in value for coord in point)


def _check_shape(value: Polygon) -> None:
    """Structural check, run before any coordinate maths can trip over it."""
    if len(value) < 3:
        raise ValueError("door_polygon needs at least 3 points")
    for point in value:
        if len(point) != 2:
            raise ValueError("each polygon point must be [x, y]")


def _validate_polygon(value: Polygon | None) -> Polygon | None:
    if value is None:
        return None
    _check_shape(value)
    if _looks_like_pixels(value):
        raise ValueError(
            "polygon coordinates look like pixels — send frame_width and "
            "frame_height alongside them (PUT /cameras/{id}/door-polygon), or "
            "divide each point by the frame size yourself to normalize to [0, 1]"
        )
    for point in value:
        if not all(0.0 <= coord <= 1.0 for coord in point):
            raise ValueError("polygon coordinates must be normalized to [0, 1]")
    return value


class _HierarchyFields(BaseModel):
    @field_validator(*HIERARCHY_FIELDS, check_fields=False)
    @classmethod
    def _blank_hierarchy(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class CameraBase(_HierarchyFields):
    name: str = Field(min_length=1, max_length=120)
    location: str | None = Field(None, max_length=255)
    area: str | None = Field(None, max_length=100)
    building: str | None = Field(None, max_length=100)
    floor_level: str | None = Field(None, max_length=20)
    zone: str | None = Field(None, max_length=100)
    rtsp_url: str = Field(
        min_length=1,
        max_length=512,
        description="rtsp:// URL, or a local video file path for testing",
    )
    enabled: bool = True
    strategy: StrategyName = StrategyName.ZONE_BASED
    door_polygon: Polygon | None = None
    clear_min_pct: float | None = Field(None, ge=0, le=100)
    full_max_pct: float | None = Field(None, ge=0, le=100)
    confirm_seconds: float | None = Field(None, ge=0)
    clear_seconds: float | None = Field(None, ge=0)
    process_fps: float | None = Field(None, gt=0, le=60)

    @field_validator("door_polygon")
    @classmethod
    def _check_polygon(cls, value: Polygon | None) -> Polygon | None:
        return _validate_polygon(value)


class CameraCreate(CameraBase):
    pass


class CameraUpdate(_HierarchyFields):
    name: str | None = Field(None, min_length=1, max_length=120)
    location: str | None = Field(None, max_length=255)
    area: str | None = Field(None, max_length=100)
    building: str | None = Field(None, max_length=100)
    floor_level: str | None = Field(None, max_length=20)
    zone: str | None = Field(None, max_length=100)
    rtsp_url: str | None = Field(None, min_length=1, max_length=512)
    enabled: bool | None = None
    strategy: StrategyName | None = None
    door_polygon: Polygon | None = None
    clear_min_pct: float | None = Field(None, ge=0, le=100)
    full_max_pct: float | None = Field(None, ge=0, le=100)
    confirm_seconds: float | None = Field(None, ge=0)
    clear_seconds: float | None = Field(None, ge=0)
    process_fps: float | None = Field(None, gt=0, le=60)

    @field_validator("door_polygon")
    @classmethod
    def _check_polygon(cls, value: Polygon | None) -> Polygon | None:
        return _validate_polygon(value)


class DoorPolygonUpdate(BaseModel):
    """The exit region, in normalized [0,1] *or* pixel coordinates.

    A drawing UI works in the pixels of the frame it displayed. Sending those
    together with the frame size it measured them against keeps the client free
    of conversion maths — and keeps the stored polygon resolution-independent,
    so it survives a camera being swapped for one with a different sensor.
    """

    door_polygon: Polygon
    frame_width: int | None = Field(
        None, gt=0, description="Width of the frame the points were drawn on"
    )
    frame_height: int | None = Field(
        None, gt=0, description="Height of the frame the points were drawn on"
    )

    @model_validator(mode="after")
    def _normalize(self) -> DoorPolygonUpdate:
        if (self.frame_width is None) != (self.frame_height is None):
            raise ValueError("frame_width and frame_height must be given together")
        _check_shape(self.door_polygon)
        if self.frame_width is not None and self.frame_height is not None:
            self.door_polygon = normalize_polygon(
                self.door_polygon, self.frame_width, self.frame_height
            )
        _validate_polygon(self.door_polygon)
        return self


class CameraRead(CameraBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_host: str = Field(
        "", description="rtsp_url with any credentials masked, safe to display"
    )

    @model_validator(mode="after")
    def _mask_source(self) -> CameraRead:
        self.source_host = redact_url(self.rtsp_url)
        return self
    reference_bbox: list[float] | None = None
    reference_captured_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ReferenceCaptureResponse(BaseModel):
    camera_id: int
    reference_bbox: list[float]
    confidence: float
    captured_at: datetime
    message: str


class CameraHierarchy(BaseModel):
    """Distinct values for each level, narrowed by the levels above it."""

    locations: list[str]
    areas: list[str]
    buildings: list[str]
    floor_levels: list[str]
    zones: list[str]


class ProbeResult(BaseModel):
    """One "Test connection" result (the platform's rtsp_probe output)."""

    camera_id: int
    camera_name: str
    reachable: bool
    latency_ms: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    error: str | None = None
