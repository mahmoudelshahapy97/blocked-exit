"""Event lifecycle: detected -> acknowledged -> resolved, the overview counters,
and the pipeline writing risk level and detection confidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.db.conftest import bearer, create_camera, insert_event


@pytest.fixture
async def setup(client, sql, superadmin, make_user):
    ws = (
        await client.post(
            "/workspaces", json={"name": "Plant"}, headers=bearer(superadmin)
        )
    ).json()["id"]
    viewer = await make_user("vera", workspace_id=ws, workspace_role="viewer")
    member = await make_user("max", workspace_id=ws, workspace_role="member")
    camera = await create_camera(client, member, "Dock")
    now = datetime.now(UTC)
    events = {
        "closed": await insert_event(
            sql,
            workspace_id=ws,
            camera_id=camera,
            started_at=now - timedelta(hours=2),
            risk_level="MEDIUM",
            peak_risk_score=40.0,
        ),
        "critical": await insert_event(
            sql,
            workspace_id=ws,
            camera_id=camera,
            started_at=now - timedelta(minutes=5),
            ended_at=None,
            duration_s=None,
            peak_state="FULL",
            risk_level="CRITICAL",
            peak_risk_score=90.0,
        ),
        "old": await insert_event(
            sql,
            workspace_id=ws,
            camera_id=camera,
            started_at=now - timedelta(days=3),
            risk_level="HIGH",
            peak_risk_score=60.0,
        ),
    }
    return SimpleNamespace(
        ws=ws, viewer=viewer, member=member, camera=camera, events=events
    )


async def test_new_events_start_detected(client, setup):
    event = (
        await client.get(
            f"/events/{setup.events['closed']}", headers=bearer(setup.viewer)
        )
    ).json()
    assert event["status"] == "detected"
    assert event["camera_name"] == "Dock"
    assert event["acknowledged_at"] is None


async def test_acknowledge_then_resolve_records_who_and_when(client, setup):
    event_id = setup.events["closed"]
    ack = await client.post(
        f"/events/{event_id}/acknowledge", json={}, headers=bearer(setup.member)
    )
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"
    assert ack.json()["acknowledged_by"] == "max"
    acknowledged_at = ack.json()["acknowledged_at"]

    # Acknowledging again changes nothing.
    again = await client.post(
        f"/events/{event_id}/acknowledge", headers=bearer(setup.member)
    )
    assert again.json()["acknowledged_at"] == acknowledged_at

    resolved = await client.post(
        f"/events/{event_id}/resolve",
        json={"note": "Pallet moved to bay 4"},
        headers=bearer(setup.member),
    )
    body = resolved.json()
    assert body["status"] == "resolved"
    assert body["resolved_by"] == "max"
    assert body["resolution_note"] == "Pallet moved to bay 4"
    assert body["acknowledged_at"] == acknowledged_at

    late = await client.post(
        f"/events/{event_id}/acknowledge", headers=bearer(setup.member)
    )
    assert late.status_code == 409


async def test_resolving_from_detected_also_acknowledges(client, setup):
    body = (
        await client.post(
            f"/events/{setup.events['critical']}/resolve",
            json={},
            headers=bearer(setup.member),
        )
    ).json()
    assert body["status"] == "resolved"
    assert body["acknowledged_at"] == body["resolved_at"]


async def test_viewers_cannot_acknowledge(client, setup):
    response = await client.post(
        f"/events/{setup.events['closed']}/acknowledge", headers=bearer(setup.viewer)
    )
    assert response.status_code == 403


async def test_list_filters_by_status_and_risk_and_sorts_by_risk(client, setup):
    await client.post(
        f"/events/{setup.events['old']}/resolve", json={}, headers=bearer(setup.member)
    )

    async def ids(query):
        response = await client.get(f"/events?{query}", headers=bearer(setup.viewer))
        assert response.status_code == 200, response.text
        return [e["id"] for e in response.json()["items"]]

    assert set(await ids("status=detected")) == {
        setup.events["closed"],
        setup.events["critical"],
    }
    assert await ids("risk_level=HIGH,CRITICAL&sort=risk") == [
        setup.events["critical"],
        setup.events["old"],
    ]
    assert await ids("sort=risk") == [
        setup.events["critical"],
        setup.events["old"],
        setup.events["closed"],
    ]
    assert await ids("state=FULL") == [setup.events["critical"]]
    bad = await client.get("/events?status=done", headers=bearer(setup.viewer))
    assert bad.status_code == 400


async def test_overview_counts(client, setup):
    overview = (await client.get("/events/overview", headers=bearer(setup.viewer))).json()
    assert overview["events_24h"] == 2
    assert overview["open_events"] == 3
    assert overview["unacknowledged_events"] == 3
    assert overview["ongoing_events"] == 1
    assert overview["high_risk_open_events"] == 2
    assert overview["currently_blocked"] == 1
    assert overview["cameras_total"] == 1
    assert [e["id"] for e in overview["latest_events"]][0] == setup.events["critical"]


async def test_snapshot_is_served_from_disk(client, sql, setup, tmp_path):
    jpeg = tmp_path / "frame.jpg"
    jpeg.write_bytes(b"\xff\xd8fake")
    await sql.execute(
        "UPDATE blockage_event SET snapshot_path = $1 WHERE id = $2",
        str(jpeg),
        setup.events["closed"],
    )
    response = await client.get(
        f"/events/{setup.events['closed']}/snapshot", headers=bearer(setup.viewer)
    )
    assert response.status_code == 200
    assert response.content == b"\xff\xd8fake"
    missing = await client.get(
        f"/events/{setup.events['old']}/snapshot", headers=bearer(setup.viewer)
    )
    assert missing.status_code == 404


async def test_pipeline_records_risk_level_and_confidence(db, sql, setup):
    from app.services.stream_manager import StreamManager
    from app.services.stream_worker import PipelineMessage

    manager = StreamManager()
    worker = SimpleNamespace(
        camera=SimpleNamespace(workspace_id=setup.ws), current_event_id=None
    )
    manager._workers[setup.camera] = worker
    base = {
        "state": "PARTIAL",
        "strategy": "zone_based",
        "accessibility_pct": 60.0,
        "risk_score": 35.0,
        "risk_level": "MEDIUM",
        "duration_s": 6.0,
        "blocking_objects": [],
        "confidence": 0.81,
        "avg_confidence": 0.81,
    }
    await manager._on_open(
        PipelineMessage(kind="open", camera_id=setup.camera, payload=base)
    )
    event_id = worker.current_event_id
    await manager._on_update(
        PipelineMessage(
            kind="update",
            camera_id=setup.camera,
            payload={
                **base,
                "state": "FULL",
                "risk_level": "CRITICAL",
                "confidence": 0.93,
                "avg_confidence": 0.87,
            },
        )
    )
    # A later, calmer reading does not lower the worst band reached.
    await manager._on_update(
        PipelineMessage(
            kind="update",
            camera_id=setup.camera,
            payload={
                **base,
                "risk_level": "MEDIUM",
                "confidence": 0.93,
                "avg_confidence": 0.85,
            },
        )
    )
    await manager._on_close(
        PipelineMessage(
            kind="close",
            camera_id=setup.camera,
            payload={
                "event_id": event_id,
                "duration_s": 30.0,
                "accessibility_pct": 100.0,
                "confidence": 0.93,
                "avg_confidence": 0.84,
            },
        )
    )
    row = await sql.fetchrow(
        "SELECT status, risk_level, confidence, avg_confidence, ended_at "
        "FROM blockage_event WHERE id = $1",
        event_id,
    )
    assert row["status"] == "detected"  # closing a blockage is not resolving it
    assert row["risk_level"] == "CRITICAL"
    assert float(row["confidence"]) == pytest.approx(0.93)
    assert float(row["avg_confidence"]) == pytest.approx(0.84)
    assert row["ended_at"] is not None
