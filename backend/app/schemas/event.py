"""Blockage event and alert schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AlertChannel, AlertStatus, BlockageState
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
