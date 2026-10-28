"""What every InsightEye console now shares (migration 0007): the in-app
notification inbox and its socket, the audit log, CSV export, per-account
alert email, sign-in protection and camera health notifications."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.api.routes import auth as auth_routes
from app.core.config import settings
from app.core.ratelimit import SlidingWindow
from app.services import alerting, inbox
from app.services.camera_health import CameraHealthWatch
from tests.db.conftest import (
    PASSWORD,
    active_workspace_id,
    bearer,
    create_camera,
    insert_event,
    login,
)


async def test_a_workspace_notification_reaches_members_and_superadmins(
    client, superadmin, make_user
):
    ws = await active_workspace_id(client, superadmin)
    member = await make_user("ann", workspace_id=ws)
    stranger = await make_user("bob")  # no workspace
    sent = await inbox.notify_workspace(
        ws, kind="alert", title="Exit blocked", ref_id="event-1"
    )
    assert sent == 2
    for token, expected in ((member, 1), (superadmin, 1), (stranger, 0)):
        body = (
            await client.get(
                "/notifications", params={"kind": "alert"}, headers=bearer(token)
            )
        ).json()
        assert body["total"] == expected
    # The same thing never notifies an account twice.
    assert (
        await inbox.notify_workspace(
            ws, kind="alert", title="Exit blocked", ref_id="event-1"
        )
        == 0
    )


async def test_notification_routes_list_read_and_unread(client, superadmin):
    headers = bearer(superadmin)
    assert (await client.post("/notifications/test", headers=headers)).json() == {
        "sent": 1
    }
    body = (await client.get("/notifications", headers=headers)).json()
    assert body["unread"] == 1 and body["items"][0]["title"] == "Test notification"
    item = body["items"][0]
    read = (
        await client.post(
            "/notifications/read",
            json={"notification_ids": [item["notification_id"]]},
            headers=headers,
        )
    ).json()
    assert read == {"marked": 1, "unread": 0}
    assert (
        await client.delete(
            f"/notifications/{item['notification_id']}/read", headers=headers
        )
    ).json() == {"unread": 1}
    assert (await client.post("/notifications/read", json={}, headers=headers)).json()[
        "unread"
    ] == 0


async def test_leaving_a_workspace_takes_its_notifications_out_of_the_bell(
    client, superadmin, make_user, sql
):
    ws = await active_workspace_id(client, superadmin)
    member = await make_user("cid", workspace_id=ws)
    await inbox.notify_workspace(ws, kind="alert", title="t", ref_id="event-9")
    assert (
        await client.get("/notifications/unread-count", headers=bearer(member))
    ).json() == {"unread": 1}
    await sql.execute(
        "DELETE FROM workspace_member "
        "WHERE user_id = (SELECT id FROM app_user WHERE username = 'cid')"
    )
    assert (
        await client.get("/notifications/unread-count", headers=bearer(member))
    ).json() == {"unread": 0}


async def test_a_camera_going_offline_and_back_notifies_once_each(
    client, superadmin, monkeypatch
):
    from app.core.enums import WorkerState
    from app.schemas.detection import CameraStatus

    camera_id = await create_camera(client, superadmin, "door-a")
    monkeypatch.setattr(settings, "CAMERA_OFFLINE_AFTER_S", 30)
    watch = CameraHealthWatch()

    def status(state):
        return [
            CameraStatus(camera_id=camera_id, camera_name="door-a", worker_state=state)
        ]

    await watch.check(status(WorkerState.RUNNING), now=0)
    await watch.check(status(WorkerState.RECONNECTING), now=10)
    await watch.check(status(WorkerState.RECONNECTING), now=45)
    await watch.check(status(WorkerState.ERROR), now=60)
    await watch.check(status(WorkerState.RUNNING), now=70)
    kinds = [
        n["kind"]
        for n in (await client.get("/notifications", headers=bearer(superadmin))).json()[
            "items"
        ]
    ]
    assert kinds.count("camera_offline") == 1 and kinds.count("camera_online") == 1


async def test_sign_ins_and_changes_are_audited(client, superadmin):
    assert (
        await client.post(
            "/auth/login", json={"username": "root", "password": "wrong-Pass-1"}
        )
    ).status_code == 401
    token = await login(client, "root")
    headers = bearer(token)
    camera_id = await create_camera(client, token, "door-b")
    response = await client.patch(
        f"/cameras/{camera_id}", json={"location": "Gate 9"}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.headers["x-request-id"]

    page = (await client.get("/audit-logs", headers=headers)).json()
    actions = [row["action"] for row in page["items"]]
    assert (
        "auth.login_failed" in actions
        and "auth.login" in actions
        and "camera.updated" in actions
    )
    updated = next(r for r in page["items"] if r["action"] == "camera.updated")
    assert (
        updated["target_id"] == str(camera_id)
        and updated["request_id"] == response.headers["x-request-id"]
    )

    csv = await client.get("/audit-logs/export.csv", headers=headers)
    assert (
        csv.headers["content-type"].startswith("text/csv")
        and "camera.updated" in csv.text
    )


async def test_the_audit_log_is_for_superadmins(client, superadmin, make_user):
    ws = await active_workspace_id(client, superadmin)
    member = await make_user("dee", workspace_id=ws, workspace_role="admin")
    assert (await client.get("/audit-logs", headers=bearer(member))).status_code == 403


async def test_events_export_as_csv_with_the_list_filters(client, superadmin, sql):
    ws = await active_workspace_id(client, superadmin)
    camera_id = await create_camera(client, superadmin, "=door-c")
    now = datetime.now(UTC)
    await insert_event(
        sql, workspace_id=ws, camera_id=camera_id, started_at=now, risk_level="HIGH"
    )
    await insert_event(
        sql, workspace_id=ws, camera_id=camera_id, started_at=now, risk_level="LOW"
    )
    response = await client.get(
        "/events/export.csv", params={"risk_level": "HIGH"}, headers=bearer(superadmin)
    )
    assert response.status_code == 200, response.text
    lines = response.text.lstrip("﻿").strip().splitlines()
    assert lines[0].startswith("id,started_at,ended_at,camera_name")
    assert len(lines) == 2 and ",HIGH," in lines[1] and "'=door-c" in lines[1]


async def test_opted_in_accounts_get_alert_mail_one_message_each(
    client, superadmin, make_user, monkeypatch
):
    import aiosmtplib

    sent = []

    async def fake_send(message, **kwargs):
        sent.append(message)

    monkeypatch.setattr(aiosmtplib, "send", fake_send)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(settings, "ALERT_EMAIL_FROM", "alerts@example.com")
    monkeypatch.setattr(settings, "ALERT_EMAIL_TO", ["desk@example.com"])
    monkeypatch.setattr(settings, "WEBHOOK_URL", None)
    ws = await active_workspace_id(client, superadmin)
    member = await make_user("eve", workspace_id=ws)
    options = (await client.get("/auth/bootstrap")).json()
    assert options["notify_email"] is True
    me = (
        await client.patch(
            "/auth/me", json={"notify_email": True}, headers=bearer(member)
        )
    ).json()
    assert me["notify_email"] is True
    camera_id = await create_camera(client, superadmin, "door-d")
    payload = {
        "state": "FULL",
        "camera_name": "door-d",
        "location": None,
        "accessibility_pct": 0,
        "blocked_duration_s": 30,
        "risk_score": 90,
        "risk_level": "CRITICAL",
        "recommended_action": "Clear the exit",
        "strategy": "zone_based",
        "occurred_at": "2026-10-28T10:00:00Z",
        "blocking_objects": [],
    }
    await alerting.dispatch(payload, workspace_id=ws, camera_id=camera_id)
    assert sorted(m["To"] for m in sent) == ["desk@example.com", "eve@example.com"]


async def test_repeated_failed_sign_ins_are_locked_out(client, superadmin, monkeypatch):
    monkeypatch.setattr(auth_routes, "login_failures", SlidingWindow(3, 300))
    for _ in range(3):
        assert (
            await client.post(
                "/auth/login", json={"username": "root", "password": "nope-Nope-1"}
            )
        ).status_code == 401
    locked = await client.post(
        "/auth/login", json={"username": "root", "password": PASSWORD}
    )
    assert locked.status_code == 429 and int(locked.headers["retry-after"]) > 0


async def test_reset_mails_are_throttled_per_address(client, superadmin, monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(auth_routes, "reset_requests", SlidingWindow(2, 900))
    codes = [
        (
            await client.post(
                "/auth/forgot-password", json={"email": f"x{i}@example.com"}
            )
        ).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429]


@pytest.mark.parametrize("path", ["/health", "/health/ready"])
async def test_health_and_security_headers(client, path):
    response = await client.get(path)
    assert response.headers.get("x-content-type-options") == "nosniff"


async def test_a_bearer_token_opens_a_snapshot_like_a_ticket(client, superadmin):
    # The <img> routes take a stream ticket or a bearer token; the bearer path
    # goes through get_current_user and must reach the worker lookup.
    camera_id = await create_camera(client, superadmin, "Snap")
    response = await client.get(
        f"/monitoring/{camera_id}/snapshot", headers=bearer(superadmin)
    )
    assert response.status_code != 401, response.text
    assert (await client.get(f"/monitoring/{camera_id}/snapshot")).status_code == 401
