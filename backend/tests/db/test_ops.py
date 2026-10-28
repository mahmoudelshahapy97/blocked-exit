"""Ops extras: camera hierarchy, the shared event filters, connection probes,
and filtered/all data delete."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import cv2
import numpy as np
import pytest

from tests.db.conftest import (
    active_workspace_id,
    bearer,
    create_camera,
    insert_event,
)

# Africa/Cairo is UTC+3 in October 2026 (DST runs through to the end of October).
CAIRO = timedelta(hours=3)


@pytest.fixture(autouse=True)
def quick_probes(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PROBE_TIMEOUT_S", 3.0)


@pytest.fixture
async def site(client, superadmin, make_user):
    """A workspace with three exits across two buildings, and a token per role."""
    ws = (
        await client.post(
            "/workspaces", json={"name": "Mall"}, headers=bearer(superadmin)
        )
    ).json()["id"]
    tokens = {
        role: await make_user(f"{role}1", workspace_id=ws, workspace_role=role)
        for role in ("viewer", "member", "admin")
    }
    member = tokens["member"]
    cams = {
        "north": await create_camera(
            client,
            member,
            "North",
            location="Cairo",
            area="East",
            building="A",
            floor_level="1",
            zone="Gate",
        ),
        "south": await create_camera(
            client,
            member,
            "South",
            location="Cairo",
            area="East",
            building="B",
            floor_level="2",
            zone="Dock",
        ),
        "west": await create_camera(
            client,
            member,
            "West",
            location="Giza",
            area="West",
            building="C",
            rtsp_url="rtsp://user:s3cret@127.0.0.1:9/stream",
        ),
    }
    return {"ws": ws, "tokens": tokens, "cams": cams}


# -- hierarchy ----------------------------------------------------------------
async def test_hierarchy_cascades_from_the_levels_chosen_above(client, site):
    token = site["tokens"]["viewer"]
    everything = (await client.get("/cameras/hierarchy", headers=bearer(token))).json()
    assert everything == {
        "locations": ["Cairo", "Giza"],
        "areas": ["East", "West"],
        "buildings": ["A", "B", "C"],
        "floor_levels": ["1", "2"],
        "zones": ["Dock", "Gate"],
    }
    narrowed = (
        await client.get(
            "/cameras/hierarchy?location=Cairo&building=B", headers=bearer(token)
        )
    ).json()
    assert narrowed["buildings"] == ["A", "B"]  # a level is not narrowed by itself
    assert narrowed["floor_levels"] == ["2"]
    assert narrowed["zones"] == ["Dock"]


async def test_blank_hierarchy_values_are_stored_as_null(client, site):
    member = site["tokens"]["member"]
    response = await client.patch(
        f"/cameras/{site['cams']['west']}", json={"zone": "  "}, headers=bearer(member)
    )
    assert response.json()["zone"] is None


async def test_viewers_never_see_stream_credentials(client, site):
    viewer, member = site["tokens"]["viewer"], site["tokens"]["member"]
    west = site["cams"]["west"]
    as_viewer = (await client.get(f"/cameras/{west}", headers=bearer(viewer))).json()
    assert "s3cret" not in as_viewer["rtsp_url"]
    assert as_viewer["source_host"] == "rtsp://***:***@127.0.0.1:9/stream"
    as_member = (await client.get(f"/cameras/{west}", headers=bearer(member))).json()
    assert as_member["rtsp_url"] == "rtsp://user:s3cret@127.0.0.1:9/stream"
    assert as_member["source_host"] == "rtsp://***:***@127.0.0.1:9/stream"


# -- filters --------------------------------------------------------------------
@pytest.fixture
async def history(sql, site):
    """Events at known local (Cairo) times on 2026-10-10 and 2026-10-11."""

    def local(day: int, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 10, day, hour, minute, tzinfo=UTC) - CAIRO

    ws, cams = site["ws"], site["cams"]
    ids = {
        "north_morning": await insert_event(
            sql, workspace_id=ws, camera_id=cams["north"], started_at=local(10, 8)
        ),
        "south_night": await insert_event(
            sql, workspace_id=ws, camera_id=cams["south"], started_at=local(10, 23, 30)
        ),
        "west_after_midnight": await insert_event(
            sql, workspace_id=ws, camera_id=cams["west"], started_at=local(11, 0, 30)
        ),
        "north_noon": await insert_event(
            sql, workspace_id=ws, camera_id=cams["north"], started_at=local(11, 12)
        ),
    }
    return ids


async def _ids(client, token, query: str = "") -> set[int]:
    response = await client.get(f"/events?limit=500{query}", headers=bearer(token))
    assert response.status_code == 200, response.text
    return {e["id"] for e in response.json()["items"]}


async def test_dates_are_days_in_the_report_timezone(client, site, history):
    token = site["tokens"]["viewer"]
    # 23:30 Cairo on the 10th is 20:30 UTC: still the 10th locally.
    assert await _ids(client, token, "&start_date=2026-10-10&end_date=2026-10-10") == {
        history["north_morning"],
        history["south_night"],
    }
    # 00:30 Cairo on the 11th is 21:30 UTC on the 10th: the 11th locally.
    assert history["west_after_midnight"] in await _ids(
        client, token, "&start_date=2026-10-11"
    )


async def test_a_time_with_a_date_is_an_exact_bound(client, site, history):
    token = site["tokens"]["viewer"]
    found = await _ids(client, token, "&start_date=2026-10-10&start_time=23:00")
    assert found == {
        history["south_night"],
        history["west_after_midnight"],
        history["north_noon"],
    }


async def test_a_time_alone_is_a_daily_window_that_may_wrap_midnight(
    client, site, history
):
    token = site["tokens"]["viewer"]
    office = await _ids(client, token, "&start_time=07:00&end_time=13:00")
    assert office == {history["north_morning"], history["north_noon"]}
    night = await _ids(client, token, "&start_time=22:00&end_time=06:00")
    assert night == {history["south_night"], history["west_after_midnight"]}


async def test_camera_and_hierarchy_filters_take_comma_lists(client, site, history):
    token = site["tokens"]["viewer"]
    cams = site["cams"]
    both = await _ids(client, token, f"&camera_id={cams['south']},{cams['west']}")
    assert both == {history["south_night"], history["west_after_midnight"]}
    by_building = await _ids(client, token, "&building=A,C")
    assert by_building == {
        history["north_morning"],
        history["north_noon"],
        history["west_after_midnight"],
    }
    # Levels AND together.
    assert await _ids(client, token, "&location=Cairo&zone=Dock") == {
        history["south_night"]
    }


async def test_bad_filters_are_rejected(client, site):
    token = site["tokens"]["viewer"]
    assert (
        await client.get("/events?camera_id=1,x", headers=bearer(token))
    ).status_code == 422
    backwards = "/events?start_date=2026-10-11&end_date=2026-10-10"
    assert (await client.get(backwards, headers=bearer(token))).status_code == 422


# -- probes ---------------------------------------------------------------------
async def test_probe_reports_an_unreachable_source(client, site):
    member = site["tokens"]["member"]
    response = await client.post(
        f"/cameras/{site['cams']['west']}/probe", headers=bearer(member)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is False
    assert body["camera_name"] == "West"
    assert "s3cret" not in (body["error"] or "")


async def test_probe_reads_a_frame_from_a_working_source(client, site, tmp_path):
    clip = tmp_path / "exit.avi"
    writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
    for _ in range(5):
        writer.write(np.zeros((240, 320, 3), dtype=np.uint8))
    writer.release()

    member = site["tokens"]["member"]
    camera = await create_camera(client, member, "Clip", rtsp_url=str(clip))
    body = (await client.post(f"/cameras/{camera}/probe", headers=bearer(member))).json()
    assert body["reachable"] is True
    assert (body["width"], body["height"]) == (320, 240)

    results = (await client.post("/cameras/probe-all", headers=bearer(member))).json()
    assert {r["camera_name"]: r["reachable"] for r in results} == {
        "North": False,
        "South": False,
        "West": False,
        "Clip": True,
    }


async def test_viewers_cannot_probe(client, site):
    viewer = site["tokens"]["viewer"]
    response = await client.post("/cameras/probe-all", headers=bearer(viewer))
    assert response.status_code == 403


# -- data delete ------------------------------------------------------------------
async def test_delete_needs_admin_and_a_filter(client, site, history):
    member, admin = site["tokens"]["member"], site["tokens"]["admin"]
    north = site["cams"]["north"]
    assert (
        await client.delete(f"/events?camera_id={north}", headers=bearer(member))
    ).status_code == 403
    assert (await client.delete("/events", headers=bearer(admin))).status_code == 400

    response = await client.delete(f"/events?camera_id={north}", headers=bearer(admin))
    assert response.json() == {"deleted": 2, "skipped_open": 0}
    assert await _ids(client, admin) == {
        history["south_night"],
        history["west_after_midnight"],
    }


async def test_delete_all_needs_confirmation_and_keeps_ongoing_events(
    client, sql, site, history, tmp_path
):
    admin = site["tokens"]["admin"]
    snapshot = tmp_path / "open.jpg"
    snapshot.write_bytes(b"jpeg")
    closed_snapshot = tmp_path / "closed.jpg"
    closed_snapshot.write_bytes(b"jpeg")
    await sql.execute(
        "UPDATE blockage_event SET snapshot_path = $1 WHERE id = $2",
        str(closed_snapshot),
        history["north_noon"],
    )
    ongoing = await insert_event(
        sql,
        workspace_id=site["ws"],
        camera_id=site["cams"]["south"],
        started_at=datetime.now(UTC),
        ended_at=None,
        duration_s=None,
        snapshot_path=str(snapshot),
    )

    assert (await client.delete("/events/all", headers=bearer(admin))).status_code == 400
    response = await client.delete("/events/all?confirm=true", headers=bearer(admin))
    assert response.json() == {"deleted": 4, "skipped_open": 1}
    assert await _ids(client, admin) == {ongoing}
    assert not closed_snapshot.exists()
    assert snapshot.exists()


async def test_delete_is_scoped_to_the_active_workspace(client, sql, superadmin, site):
    other = (
        await client.post(
            "/workspaces", json={"name": "Other"}, headers=bearer(superadmin)
        )
    ).json()["id"]
    await client.post(f"/workspaces/{other}/activate", headers=bearer(superadmin))
    camera = await create_camera(client, superadmin, "Elsewhere")
    await insert_event(
        sql, workspace_id=other, camera_id=camera, started_at=datetime.now(UTC)
    )

    admin = site["tokens"]["admin"]
    assert await active_workspace_id(client, admin) == site["ws"]
    response = await client.delete("/events/all?confirm=true", headers=bearer(admin))
    assert response.json()["deleted"] == 0
    left = await sql.fetchval(
        "SELECT count(*) FROM blockage_event WHERE workspace_id=$1", other
    )
    assert left == 1
