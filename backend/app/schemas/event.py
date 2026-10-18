"""Blockage event and alert schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    AlertChannel,
    AlertStatus,
    BlockageState,
    EventStatus,
    RiskLevel,
)
from app.schemas.detection import BlockingObject


class BlockageEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    started_at: datetime
    ended_at: datetime | None = None
    duration_s: float | None = None
    state: BlockageState
    peak_state: BlockageState
    strategy: str
    min_accessibility_pct: float
    last_accessibility_pct: float
    peak_risk_score: float
    blocking_objects: list[BlockingObject] | None = None
    snapshot_path: str | None = None
    has_snapshot: bool = False
    camera_name: str | None = None

    risk_level: RiskLevel | None = None
    confidence: float | None = Field(
        None, description="Peak detection confidence of the blocking objects"
    )
    avg_confidence: float | None = Field(
        None, description="Mean of each frame's top blocking-object confidence"
    )

    status: EventStatus = EventStatus.DETECTED
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = Field(None, description="Username")
    resolved_at: datetime | None = None
    resolved_by: str | None = Field(None, description="Username")
    resolution_note: str | None = None

    @model_validator(mode="after")
    def _snapshot_flag(self) -> BlockageEventRead:
        self.has_snapshot = bool(self.snapshot_path)
        return self


class EventAcknowledge(BaseModel):
    note: str | None = Field(None, max_length=1000)


class EventResolve(BaseModel):
    """Move an event forward. `acknowledged` is the same as POST .../acknowledge."""

    status: Literal["acknowledged", "resolved"] = "resolved"
    note: str | None = Field(None, max_length=1000)


class EventOverview(BaseModel):
    """Landing-page counters (the platform's /blocked-exit/overview)."""

    events_24h: int
    open_events: int = Field(description="Not yet resolved")
    unacknowledged_events: int = Field(description="Still in 'detected'")
    ongoing_events: int = Field(description="Blockage still happening (no ended_at)")
    high_risk_open_events: int = Field(description="Unresolved, HIGH or CRITICAL")
    cameras_total: int
    cameras_monitored: int
    currently_blocked: int = Field(description="Exits with an ongoing blockage")
    latest_events: list[BlockageEventRead]


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    event_id: int | None = None
    channel: AlertChannel
    status: AlertStatus
    error: str | None = None
    payload: dict | None = None
    created_at: datetime
    sent_at: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None


class AlertAcknowledge(BaseModel):
    acknowledged_by: str = Field(min_length=1, max_length=120)


class AlertTestRequest(BaseModel):
    camera_id: int
    channels: list[AlertChannel] | None = None


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class DeleteResult(BaseModel):
    deleted: int = Field(description="Events removed, with their alerts and snapshots")
    skipped_open: int = Field(
        0, description="Matching events still ongoing, which are never deleted"
    )
