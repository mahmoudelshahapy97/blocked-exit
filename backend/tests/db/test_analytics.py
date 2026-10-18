"""Extended analytics against hand-computed answers.

Four events at known Cairo times (UTC+3 in October 2026):

    id  exit  local start      length  conf  status (ack / resolve after)  worst  objects
    e1  A     Mon 12 Oct 09:00    20s  0.40  resolved (60s / 300s)                chair
    e2  A     Mon 12 Oct 09:30    45s  0.95  acknowledged (120s)          FULL   chair,
                                                                                 couch
    e3  B     Tue 13 Oct 22:00   400s  0.70  detected                             person
    e4  B     Tue 13 Oct 22:10  1000s  -     resolved (30s / 900s)        FULL   chair
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.db.conftest import bearer, create_camera, insert_event

CAIRO = timedelta(hours=3)


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC) - CAIRO


def _objs(*labels):
    return [{"label": label, "confidence": 0.9, "area_pct": 10.0} for label in labels]


@pytest.fixture
async def data(client, sql, superadmin):
    ws = (await client.get("/workspaces/active", headers=bearer(superadmin))).json()["id"]
    a = await create_camera(client, superadmin, "A", building="X")
    b = await create_camera(client, superadmin, "B", building="Y")

    async def event(camera, start, seconds, **fields):
        return await insert_event(
            sql,
            workspace_id=ws,
            camera_id=camera,
            started_at=start,
            ended_at=start + timedelta(seconds=seconds),
            duration_s=float(seconds),
            **fields,
        )

    e1_start, e4_start = local(12, 9), local(13, 22, 10)
    ids = SimpleNamespace(
        e1=await event(
            a,
            e1_start,
            20,
            confidence=0.40,
            status="resolved",
            acknowledged_at=e1_start + timedelta(seconds=60),
            resolved_at=e1_start + timedelta(seconds=300),
            blocking_objects=_objs("chair"),
        ),
        e2=await event(
            a,
            local(12, 9, 30),
            45,
            confidence=0.95,
            status="acknowledged",
            acknowledged_at=local(12, 9, 30) + timedelta(seconds=120),
            peak_state="FULL",
            min_accessibility_pct=10.0,
            blocking_objects=_objs("chair", "couch"),
        ),
        e3=await event(
            b, local(13, 22), 400, confidence=0.70, blocking_objects=_objs("person")
        ),
        e4=await event(
            b,
            e4_start,
            1000,
            status="resolved",
            acknowledged_at=e4_start + timedelta(seconds=30),
            resolved_at=e4_start + timedelta(seconds=900),
            peak_state="FULL",
            min_accessibility_pct=5.0,
            blocking_objects=_objs("chair"),
        ),
    )
    return SimpleNamespace(token=superadmin, a=a, b=b, ids=ids)


async def _get(client, data, path, **params):
    response = await client.get(
        f"/analytics/{path}", params=params, headers=bearer(data.token)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_incidents_per_camera(client, data):
    rows = await _get(client, data, "incidents-per-camera")
    assert [
        (r["camera_name"], r["events"], r["acknowledged"], r["resolved"]) for r in rows
    ] == [
        ("A", 2, 2, 1),
        ("B", 2, 1, 1),
    ]
    only_x = await _get(client, data, "incidents-per-camera", building="X")
    assert [r["camera_name"] for r in only_x] == ["A"]
    assert only_x[0]["building"] == "X"


async def test_confidence_audit(client, data):
    audit = await _get(client, data, "confidence-audit")
    summary = audit["summary"]
    assert summary["events"] == 4
    assert summary["scored_events"] == 3
    assert summary["avg_confidence"] == pytest.approx(0.6833, abs=1e-4)
    assert (summary["min_confidence"], summary["max_confidence"]) == (0.4, 0.95)
    assert summary["threshold"] == 0.35
    assert summary["low_confidence_cutoff"] == 0.45
    assert summary["low_confidence"] == 1
    assert summary["low_confidence_share"] == pytest.approx(0.3333, abs=1e-4)

    counts = {b["bucket"]: b["count"] for b in audit["histogram"]}
    assert len(counts) == 10
    assert (counts["0.4-0.5"], counts["0.7-0.8"], counts["0.9-1.0"]) == (1, 1, 1)
    assert sum(counts.values()) == 3

    assert [e["event_id"] for e in audit["per_event"]] == [
        data.ids.e3,
        data.ids.e2,
        data.ids.e1,
    ]
    per_camera = {c["camera_name"]: c for c in audit["per_camera"]}
    assert per_camera["A"]["low_confidence"] == 1
    assert per_camera["B"]["events"] == 1  # e4 has no confidence


async def test_trend_is_hourly_for_short_ranges_and_zero_fills(client, data):
    trend = await _get(
        client, data, "trend", start_date="2026-10-12", end_date="2026-10-13"
    )
    assert trend["bucket"] == "hour"
    assert trend["timezone"] == "Africa/Cairo"
    points = {p["bucket_start"]: (p["incidents"], p["resolved"]) for p in trend["points"]}
    assert len(points) == 48
    assert points["2026-10-12T09:00:00"] == (2, 1)
    assert points["2026-10-13T22:00:00"] == (2, 1)
    assert points["2026-10-12T10:00:00"] == (0, 0)

    daily = await _get(
        client,
        data,
        "trend",
        start_date="2026-10-12",
        end_date="2026-10-13",
        bucket="day",
    )
    assert [
        (p["bucket_start"], p["incidents"], p["resolved"]) for p in daily["points"]
    ] == [
        ("2026-10-12T00:00:00", 2, 1),
        ("2026-10-13T00:00:00", 2, 1),
    ]


async def test_trend_without_a_range_spans_the_data(client, data):
    trend = await _get(client, data, "trend", bucket="day")
    assert [p["bucket_start"][:10] for p in trend["points"]] == [
        "2026-10-12",
        "2026-10-13",
    ]


async def test_heatmap_uses_local_weekday_and_hour(client, data):
    cells = await _get(client, data, "heatmap")
    assert [(c["weekday"], c["hour"], c["incidents"]) for c in cells] == [
        (1, 9, 2),  # Monday 09:xx
        (2, 22, 2),  # Tuesday 22:xx
    ]


async def test_response_times_use_interpolated_percentiles(client, data):
    times = await _get(client, data, "response-times")
    assert times["summary"] == {
        "incidents": 4,
        "acknowledged": 3,
        "resolved": 2,
        "open": 2,
        "ack_median_s": 60.0,
        "ack_p90_s": 108.0,  # 30, 60, 120 -> 60 + 0.8 * 60
        "resolve_median_s": 600.0,
        "resolve_p90_s": 840.0,  # 300, 900 -> 300 + 0.9 * 600
    }
    per_camera = {c["camera_name"]: c for c in times["per_camera"]}
    assert per_camera["B"]["resolve_median_s"] == 900.0
    assert per_camera["A"]["ack_median_s"] == 90.0


async def test_breakdown(client, data):
    result = await _get(client, data, "breakdown")
    per_camera = result["per_camera"]
    assert [c["camera_name"] for c in per_camera] == ["B", "A"]
    b, a = per_camera
    assert (b["episodes"], b["total_blocked_s"], b["max_duration_s"]) == (
        2,
        1400.0,
        1000.0,
    )
    assert (b["worst_accessibility_pct"], b["fully_blocked"]) == (5.0, 1)
    assert (a["total_blocked_s"], a["avg_duration_s"]) == (65.0, 32.5)

    assert [(h["min"], h["max"], h["count"]) for h in result["duration_histogram"]] == [
        (0.0, 30.0, 1),
        (30.0, 60.0, 1),
        (60.0, 300.0, 0),
        (300.0, 900.0, 1),
        (900.0, None, 1),
    ]
    assert result["top_objects"] == [
        {"object": "chair", "episodes": 3},
        {"object": "couch", "episodes": 1},
        {"object": "person", "episodes": 1},
    ]


async def test_existing_reports_take_the_filters_too(client, data):
    summary = await _get(
        client, data, "summary", start_date="2026-10-12", end_date="2026-10-12"
    )
    assert summary["events_total"] == 2
    most = await _get(client, data, "most-blocked", start_date="2026-10-01", building="Y")
    assert [m["camera_name"] for m in most] == ["B"]
    report = await _get(client, data, "daily-report", report_date="2026-10-13")
    rows = {r["camera_name"]: r["event_count"] for r in report["rows"]}
    assert rows == {"A": 0, "B": 2}


async def test_empty_results_are_well_formed(client, data):
    params = {"start_date": "2020-01-01", "end_date": "2020-01-02"}
    assert await _get(client, data, "incidents-per-camera", **params) == []
    assert await _get(client, data, "heatmap", **params) == []
    audit = await _get(client, data, "confidence-audit", **params)
    assert audit["summary"]["scored_events"] == 0
    assert audit["summary"]["low_confidence_share"] is None
    times = await _get(client, data, "response-times", **params)
    assert times["summary"]["ack_median_s"] is None
    trend = await _get(client, data, "trend", **params)
    assert trend["bucket"] == "hour"
    assert all(p["incidents"] == 0 for p in trend["points"])
