"""Login and workspaces, platform model: bootstrap superadmin, closed signup,
superadmin-run tenancy, a server-side active workspace, and the
admin/member/viewer role matrix."""

from __future__ import annotations

from tests.db.conftest import PASSWORD, bearer, login


async def _workspace(client, token, name="Site B") -> int:
    response = await client.post(
        "/workspaces", json={"name": name}, headers=bearer(token)
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# -- signup ---------------------------------------------------------------------
async def test_first_signup_bootstraps_a_superadmin_then_signup_closes(client):
    status = (await client.get("/auth/bootstrap")).json()
    assert status == {
        "signup_open": True,
        "needs_bootstrap": True,
        "password_reset": False,
        "notify_email": False,
    }

    response = await client.post(
        "/auth/signup",
        json={
            "username": "root",
            "email": "root@example.com",
            "password": PASSWORD,
            "workspace_name": "Head Office",
        },
    )
    assert response.status_code == 201
    me = (
        await client.get("/auth/me", headers=bearer(response.json()["access_token"]))
    ).json()
    assert me["role"] == "superadmin"
    assert [(m["workspace_name"], m["role"]) for m in me["memberships"]] == [
        ("Head Office", "admin")
    ]
    assert me["active_workspace_id"] == me["memberships"][0]["workspace_id"]

    assert (await client.get("/auth/bootstrap")).json() == {
        "signup_open": False,
        "needs_bootstrap": False,
        "password_reset": False,
        "notify_email": False,
    }
    second = await client.post(
        "/auth/signup",
        json={"username": "eve", "email": "eve@example.com", "password": PASSWORD},
    )
    assert second.status_code == 403


async def test_open_signup_joins_the_default_workspace_as_member(
    client, superadmin, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ALLOW_OPEN_SIGNUP", True)
    response = await client.post(
        "/auth/signup",
        json={"username": "dana", "email": "dana@example.com", "password": PASSWORD},
    )
    assert response.status_code == 201
    me = (
        await client.get("/auth/me", headers=bearer(response.json()["access_token"]))
    ).json()
    assert me["role"] == "user"
    assert [m["role"] for m in me["memberships"]] == ["member"]


async def test_login_accepts_username_or_email(client, superadmin):
    assert await login(client, "root")
    assert await login(client, "ROOT@example.com")


# -- superadmin user management ---------------------------------------------------
async def test_only_a_superadmin_creates_users(client, superadmin, make_user):
    ws = await _workspace(client, superadmin)
    token = await make_user("alice", workspace_id=ws, workspace_role="admin")

    me = (await client.get("/auth/me", headers=bearer(token))).json()
    assert me["active_workspace_id"] == ws
    assert me["memberships"][0]["role"] == "admin"

    # A workspace admin is not a superadmin.
    response = await client.post(
        "/auth/users",
        json={"username": "mallory", "email": "m@example.com", "password": PASSWORD},
        headers=bearer(token),
    )
    assert response.status_code == 403
    assert (await client.get("/auth/users", headers=bearer(token))).status_code == 403


async def test_superadmin_password_reset_signs_the_user_out(
    client, superadmin, make_user
):
    token = await make_user("bob")
    users = (await client.get("/auth/users", headers=bearer(superadmin))).json()
    bob = next(u for u in users if u["username"] == "bob")

    response = await client.patch(
        f"/auth/users/{bob['id']}",
        json={"password": "Brand-New-Pass-1"},
        headers=bearer(superadmin),
    )
    assert response.status_code == 200
    assert (await client.get("/auth/me", headers=bearer(token))).status_code == 401
    assert await login(client, "bob", "Brand-New-Pass-1")


# -- workspaces ------------------------------------------------------------------
async def test_only_a_superadmin_creates_workspaces_and_manages_members(
    client, superadmin, make_user
):
    ws = await _workspace(client, superadmin)
    admin = await make_user("alice", workspace_id=ws, workspace_role="admin")

    assert (
        await client.post("/workspaces", json={"name": "Rogue"}, headers=bearer(admin))
    ).status_code == 403
    assert (
        await client.post(
            f"/workspaces/{ws}/members", json={"username": "root"}, headers=bearer(admin)
        )
    ).status_code == 403
    # ...but they can read their own roster.
    roster = (await client.get(f"/workspaces/{ws}/members", headers=bearer(admin))).json()
    assert {m["username"] for m in roster} == {"root", "alice"}


async def test_activate_switches_the_workspace_every_request_uses(
    client, superadmin, make_user
):
    ws_a = await _workspace(client, superadmin, "Site A")
    ws_b = await _workspace(client, superadmin, "Site B")
    token = await make_user("carol", workspace_id=ws_a, workspace_role="viewer")
    members = (
        await client.get(f"/workspaces/{ws_b}/members", headers=bearer(superadmin))
    ).json()
    assert members  # the creator joined as admin
    carol = next(
        u["id"]
        for u in (await client.get("/auth/users", headers=bearer(superadmin))).json()
        if u["username"] == "carol"
    )
    added = await client.post(
        f"/workspaces/{ws_b}/members",
        json={"user_id": carol, "role": "member"},
        headers=bearer(superadmin),
    )
    assert added.status_code == 201

    active = (await client.get("/workspaces/active", headers=bearer(token))).json()
    assert (active["id"], active["role"]) == (ws_a, "viewer")

    switched = await client.post(f"/workspaces/{ws_b}/activate", headers=bearer(token))
    assert switched.status_code == 200
    perms = (
        await client.get("/workspaces/active/permissions", headers=bearer(token))
    ).json()
    assert perms == {
        "workspace_id": ws_b,
        "role": "member",
        "can_resolve": True,
        "can_manage": False,
        "is_superadmin": False,
    }
    # Stored server-side: a fresh login lands in the same workspace.
    fresh = await login(client, "carol")
    assert (await client.get("/workspaces/active", headers=bearer(fresh))).json()[
        "id"
    ] == ws_b


async def test_cannot_activate_a_workspace_you_do_not_belong_to(
    client, superadmin, make_user
):
    ws_a = await _workspace(client, superadmin, "Site A")
    ws_b = await _workspace(client, superadmin, "Site B")
    token = await make_user("dave", workspace_id=ws_a)

    response = await client.post(f"/workspaces/{ws_b}/activate", headers=bearer(token))
    assert response.status_code == 404
    assert (
        await client.get(f"/workspaces/{ws_b}", headers=bearer(token))
    ).status_code == 404
    listed = (await client.get("/workspaces", headers=bearer(token))).json()
    assert [w["id"] for w in listed] == [ws_a]


async def test_a_superadmin_may_open_any_workspace(client, superadmin, make_user):
    ws = await _workspace(client, superadmin)
    await make_user("erin", workspace_id=ws, workspace_role="admin")
    # Remove root from the roster entirely: superadmin still gets in, as admin.
    roster = (
        await client.get(f"/workspaces/{ws}/members", headers=bearer(superadmin))
    ).json()
    root = next(m for m in roster if m["username"] == "root")
    await client.delete(
        f"/workspaces/{ws}/members/{root['id']}", headers=bearer(superadmin)
    )

    response = await client.post(f"/workspaces/{ws}/activate", headers=bearer(superadmin))
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


async def test_a_system_admin_acts_as_workspace_admin_where_it_belongs(
    client, superadmin, make_user
):
    ws = await _workspace(client, superadmin)
    token = await make_user(
        "frank", role="admin", workspace_id=ws, workspace_role="viewer"
    )
    perms = (
        await client.get("/workspaces/active/permissions", headers=bearer(token))
    ).json()
    assert perms["role"] == "admin"
    assert perms["is_superadmin"] is False


async def test_the_last_admin_cannot_be_removed_or_demoted(client, superadmin):
    ws = await _workspace(client, superadmin)
    roster = (
        await client.get(f"/workspaces/{ws}/members", headers=bearer(superadmin))
    ).json()
    (only_admin,) = roster

    demote = await client.patch(
        f"/workspaces/{ws}/members/{only_admin['id']}",
        json={"role": "member"},
        headers=bearer(superadmin),
    )
    assert demote.status_code == 409
    remove = await client.delete(
        f"/workspaces/{ws}/members/{only_admin['id']}", headers=bearer(superadmin)
    )
    assert remove.status_code == 409


async def test_deactivate_then_delete(client, superadmin, make_user):
    ws = await _workspace(client, superadmin)
    token = await make_user("gina", workspace_id=ws)

    assert (
        await client.delete(f"/workspaces/{ws}", headers=bearer(superadmin))
    ).status_code == 409
    response = await client.post(
        f"/workspaces/{ws}/deactivate", headers=bearer(superadmin)
    )
    assert response.json()["is_active"] is False

    # Gina's only workspace is gone; she has nowhere to act.
    assert (
        await client.get("/workspaces/active", headers=bearer(token))
    ).status_code == 404

    assert (
        await client.delete(f"/workspaces/{ws}", headers=bearer(superadmin))
    ).status_code == 204
    all_ws = (
        await client.get("/workspaces?include_inactive=true", headers=bearer(superadmin))
    ).json()
    assert ws not in [w["id"] for w in all_ws]


# -- role matrix inside a workspace ------------------------------------------------
async def test_role_matrix_for_cameras_and_exit_setup(client, superadmin, make_user):
    ws = await _workspace(client, superadmin)
    viewer = await make_user("vic", workspace_id=ws, workspace_role="viewer")
    member = await make_user("mia", workspace_id=ws, workspace_role="member")
    admin = await make_user("ada", workspace_id=ws, workspace_role="admin")

    camera = {"name": "Exit 1", "rtsp_url": "rtsp://example.invalid/1", "enabled": False}
    assert (
        await client.post("/cameras", json=camera, headers=bearer(viewer))
    ).status_code == 403
    created = await client.post("/cameras", json=camera, headers=bearer(member))
    assert created.status_code == 201, created.text
    camera_id = created.json()["id"]
    assert (await client.get("/cameras", headers=bearer(viewer))).status_code == 200

    polygon = {"door_polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]}
    assert (
        await client.put(
            f"/cameras/{camera_id}/door-polygon", json=polygon, headers=bearer(member)
        )
    ).status_code == 403
    assert (
        await client.put(
            f"/cameras/{camera_id}/door-polygon", json=polygon, headers=bearer(admin)
        )
    ).status_code == 200
