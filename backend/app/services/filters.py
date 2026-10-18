"""The event filters shared by the event list, data delete and analytics.

The same query parameters as the platform's blocked-exit API -- date range,
time of day, camera, and the location > area > building > floor_level > zone
hierarchy -- so a filter built on one page means the same rows on every other.

Two deliberate differences from the platform's `_build_event_conditions`:
- `camera_id` takes a comma-separated list (its UI sends one, and the
  platform's endpoint rejects it with a 422);
- `end_time` is never silently dropped: a time with a date on the same side is
  an absolute bound, a time without one is a daily window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import Query
from sqlalchemy import ColumnElement, Time, and_, cast, func, or_, select

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.models.camera import Camera
from app.models.event import BlockageEvent

HIERARCHY = ("location", "area", "building", "floor_level", "zone")


def csv_values(value: str | None) -> list[str]:
    """`"a, b,,c"` -> `["a", "b", "c"]`."""
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _csv_ints(value: str | None, name: str) -> list[int]:
    try:
        return [int(part) for part in csv_values(value)]
    except ValueError as exc:
        raise ValidationError(f"{name} must be a comma-separated list of ids") from exc


def report_tz() -> ZoneInfo:
    return ZoneInfo(settings.REPORT_TIMEZONE)


def local_ts(column=None):
    """`column` (default: BlockageEvent.started_at) as wall-clock time in the
    report timezone -- a timestamp without zone, for date_trunc/extract."""
    column = BlockageEvent.started_at if column is None else column
    return func.timezone(settings.REPORT_TIMEZONE, column)


@dataclass
class EventFilters:
    camera_ids: list[int] = field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    location: list[str] = field(default_factory=list)
    area: list[str] = field(default_factory=list)
    building: list[str] = field(default_factory=list)
    floor_level: list[str] = field(default_factory=list)
    zone: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (
            self.camera_ids
            or self.start_date
            or self.end_date
            or self.start_time
            or self.end_time
            or any(getattr(self, level) for level in HIERARCHY)
        )

    @property
    def window(self) -> tuple[datetime | None, datetime | None]:
        """The absolute [start, end] the dates (and their times) describe."""
        tz = report_tz()
        start = (
            datetime.combine(self.start_date, self.start_time or time.min, tz)
            if self.start_date
            else None
        )
        end = (
            datetime.combine(self.end_date, self.end_time or time.max, tz)
            if self.end_date
            else None
        )
        return start, end

    def conditions(self, workspace_id: int) -> list[ColumnElement[bool]]:
        """WHERE clauses on BlockageEvent, tenant scoping included."""
        out: list[ColumnElement[bool]] = [BlockageEvent.workspace_id == workspace_id]
        if self.camera_ids:
            out.append(BlockageEvent.camera_id.in_(self.camera_ids))

        start, end = self.window
        if start is not None:
            out.append(BlockageEvent.started_at >= start)
        if end is not None:
            out.append(BlockageEvent.started_at <= end)

        # A time with no date on its side is a time-of-day window, applied to
        # every day in range. start > end means it wraps midnight (22:00-06:00).
        clock = cast(local_ts(), Time)
        daily_from = self.start_time if self.start_date is None else None
        daily_to = self.end_time if self.end_date is None else None
        if daily_from and daily_to and daily_from > daily_to:
            out.append(or_(clock >= daily_from, clock <= daily_to))
        else:
            if daily_from:
                out.append(clock >= daily_from)
            if daily_to:
                out.append(clock <= daily_to)

        levels = [
            getattr(Camera, level).in_(values)
            for level in HIERARCHY
            if (values := getattr(self, level))
        ]
        if levels:
            out.append(
                BlockageEvent.camera_id.in_(
                    select(Camera.id).where(Camera.workspace_id == workspace_id, *levels)
                )
            )
        return out

    def where(self, workspace_id: int) -> ColumnElement[bool]:
        return and_(*self.conditions(workspace_id))


def event_filters(
    camera_id: str | None = Query(
        None, description="Camera id, or several comma-separated"
    ),
    start_date: date | None = Query(None, description="YYYY-MM-DD, report timezone"),
    end_date: date | None = Query(None, description="YYYY-MM-DD, inclusive"),
    start_time: time | None = Query(
        None, description="HH:MM. With start_date: the exact start; alone: daily window"
    ),
    end_time: time | None = Query(
        None, description="HH:MM. With end_date: the exact end; alone: daily window"
    ),
    location: str | None = Query(None, description="Comma-separated"),
    area: str | None = Query(None, description="Comma-separated"),
    building: str | None = Query(None, description="Comma-separated"),
    floor_level: str | None = Query(None, description="Comma-separated"),
    zone: str | None = Query(None, description="Comma-separated"),
) -> EventFilters:
    filters = EventFilters(
        camera_ids=_csv_ints(camera_id, "camera_id"),
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        location=csv_values(location),
        area=csv_values(area),
        building=csv_values(building),
        floor_level=csv_values(floor_level),
        zone=csv_values(zone),
    )
    start, end = filters.window
    if start is not None and end is not None and start > end:
        raise ValidationError("The start of the range is after its end")
    return filters
