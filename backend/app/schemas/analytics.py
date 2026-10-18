"""Analytics response schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.enums import BlockageState


class AnalyticsSummary(BaseModel):
    window_start: datetime
    window_end: datetime
    cameras_total: int
    cameras_monitored: int
    currently_blocked: int
    events_total: int
    events_open: int
    avg_duration_s: float
    max_duration_s: float
    avg_min_accessibility_pct: float
    alerts_sent: int


class ExitBlockageStat(BaseModel):
    camera_id: int
    camera_name: str
    location: str | None = None
    event_count: int
    total_blocked_s: float
    avg_duration_s: float
    max_duration_s: float
    min_accessibility_pct: float
    peak_risk_score: float


class TimelineEntry(BaseModel):
    event_id: int
    started_at: datetime
    ended_at: datetime | None
    duration_s: float | None
    state: BlockageState
    peak_state: BlockageState
    min_accessibility_pct: float
    peak_risk_score: float
    blocking_labels: list[str]


class CameraTimeline(BaseModel):
    camera_id: int
    camera_name: str
    window_start: datetime
    window_end: datetime
    entries: list[TimelineEntry]


class DailyReportRow(BaseModel):
    camera_id: int
    camera_name: str
    location: str | None = None
    event_count: int
    total_blocked_s: float
    avg_duration_s: float
    longest_blockage_s: float
    worst_accessibility_pct: float
    alerts_sent: int


class DailyReport(BaseModel):
    report_date: date
    generated_at: datetime
    rows: list[DailyReportRow]
    totals: DailyReportRow | None = None


# --- extended analytics (the platform's blocked-exit charts) ----------------
# Every one of these honours the shared event filters (services/filters.py).


class CameraIncidentCount(BaseModel):
    """Incidents per camera, with how far operators have got with them."""

    camera_id: int
    camera_name: str
    location: str | None = None
    area: str | None = None
    building: str | None = None
    floor_level: str | None = None
    zone: str | None = None
    events: int = Field(description="Blockage episodes (incidents)")
    acknowledged: int = Field(
        description="Acknowledged at some point (resolved included)"
    )
    resolved: int


class ConfidenceSummary(BaseModel):
    events: int
    scored_events: int = Field(description="Events with a recorded confidence")
    avg_confidence: float | None = None
    min_confidence: float | None = None
    max_confidence: float | None = None
    low_confidence: int = Field(description="Scored events below low_confidence_cutoff")
    low_confidence_share: float | None = Field(None, description="low / scored, 0..1")
    acknowledged: int
    resolved: int
    threshold: float = Field(description="The detector's confidence threshold")
    low_confidence_cutoff: float = Field(description="threshold + 0.1")


class CameraConfidence(BaseModel):
    camera_id: int
    camera_name: str
    events: int
    avg_confidence: float | None = None
    min_confidence: float | None = None
    max_confidence: float | None = None
    low_confidence: int


class HistogramBin(BaseModel):
    min: float
    max: float | None = Field(None, description="None for the open-ended last bin")
    count: int


class ConfidenceBin(HistogramBin):
    bucket: str = Field(description='Label, e.g. "0.8-0.9"')


class EventConfidence(BaseModel):
    event_id: int
    started_at: datetime
    camera_id: int
    camera_name: str
    confidence: float
    avg_confidence: float | None = None
    status: str
    risk_level: str | None = None


class ConfidenceAudit(BaseModel):
    """Model accuracy and confidence audit of the blocking detections."""

    summary: ConfidenceSummary
    per_camera: list[CameraConfidence]
    histogram: list[ConfidenceBin]
    per_event: list[EventConfidence] = Field(description="Latest 200 scored events")


class TrendPoint(BaseModel):
    bucket_start: datetime = Field(description="Wall-clock time in REPORT_TIMEZONE")
    incidents: int
    resolved: int


class Trend(BaseModel):
    bucket: Literal["hour", "day"]
    timezone: str
    points: list[TrendPoint]


class HeatmapCell(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0 = Sunday")
    hour: int = Field(ge=0, le=23)
    incidents: int


class ResponseTimeStats(BaseModel):
    incidents: int = 0
    acknowledged: int = 0
    resolved: int = 0
    open: int = Field(0, description="Not resolved yet")
    ack_median_s: float | None = None
    ack_p90_s: float | None = None
    resolve_median_s: float | None = None
    resolve_p90_s: float | None = None


class CameraResponseTimes(ResponseTimeStats):
    camera_id: int
    camera_name: str


class ResponseTimes(BaseModel):
    """Time from an incident to its acknowledgement and resolution."""

    summary: ResponseTimeStats
    per_camera: list[CameraResponseTimes]


class CameraBlockage(BaseModel):
    camera_id: int
    camera_name: str
    episodes: int
    total_blocked_s: float
    avg_duration_s: float
    max_duration_s: float
    worst_accessibility_pct: float
    fully_blocked: int = Field(description="Episodes that reached FULL")


class ObjectCount(BaseModel):
    object: str
    episodes: int


class Breakdown(BaseModel):
    """Blocked time per camera, how long episodes last, and what blocks exits."""

    per_camera: list[CameraBlockage]
    duration_histogram: list[HistogramBin]
    top_objects: list[ObjectCount]
