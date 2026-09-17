"""Analytics response schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

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
