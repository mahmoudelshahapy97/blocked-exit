"""Workspaces, the active workspace, and membership management.

The platform's rules: every user works in one *active* workspace, stored
server-side and switched with POST /workspaces/{id}/activate. Creating,
editing, deactivating and deleting workspaces, and managing who belongs to
them, is the superadmin's job -- workspace admins run the cameras and data
inside a workspace, not its roster.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import func, or_, select

from app.api.deps import (
    CurrentUserDep,
    ManagerDep,
    SessionDep,
    SuperadminDep,
    WorkspaceDep,
)
from app.core.enums import WorkspaceRole
from app.core.exceptions import ConflictError, NotFoundError
from app.core.redaction import redact_url
from app.models.camera import Camera
from app.models.user import User, Workspace, WorkspaceMember
from app.schemas.workspace import (
    MemberAdd,
    MemberRead,
    MemberUpdate,
    WorkspaceCamera,
    WorkspaceCreate,
    WorkspacePermissions,
    WorkspaceRead,
    WorkspaceUpdate,
    WorkspaceWithRole,
    slugify,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


async def _with_role(
    session: SessionDep, workspace: Workspace, role: WorkspaceRole
) -> WorkspaceWithRole:
    count = await session.scalar(
        select(func.count(Camera.id)).where(Camera.workspace_id == workspace.id)
    )
    return WorkspaceWithRole(
        **WorkspaceRead.model_validate(workspace, from_attributes=True).model_dump(),
        role=role,
        camera_count=int(count or 0),
    )


async def _visible_workspace(
    session: SessionDep, user: User, workspace_id: int
) -> tuple[Workspace, WorkspaceRole]:
    """A workspace by id, if this user may see it. Inactive ones are visible to
    the superadmin only, who has to be able to reactivate or delete them."""
    workspace = await session.get(Workspace, workspace_id)
    if workspace is not None and (workspace.is_active or user.is_superadmin):
        role = await auth_service.workspace_role_for(session, user, workspace)
        if role is not None:
            return workspace, role
    raise NotFoundError(f"Workspace {workspace_id} not found")


async def _require_workspace(session: SessionDep, workspace_id: int) -> Workspace:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFoundError(f"Workspace {workspace_id} not found")
    return workspace


# --- the caller's workspaces --------------------------------------------------
@router.get("", response_model=list[WorkspaceWithRole])
async def list_my_workspaces(
    session: SessionDep, user: CurrentUserDep, include_inactive: bool = False
) -> list[WorkspaceWithRole]:
    """Every workspace this user can switch to. A superadmin sees them all,
    and with ?include_inactive=true the deactivated ones too."""
    if user.is_superadmin:
        query = select(Workspace).order_by(Workspace.name)
        if not include_inactive:
            query = query.where(Workspace.is_active.is_(True))
        workspaces = (await session.execute(query)).scalars().all()
        pairs = [(WorkspaceRole.ADMIN, w) for w in workspaces]
    else:
        pairs = [
            (WorkspaceRole.ADMIN if user.is_system_admin else WorkspaceRole(m.role), w)
            for m, w in await auth_service.list_memberships(session, user.id)
        ]
    return [await _with_role(session, w, role) for role, w in pairs]


@router.get("/active", response_model=WorkspaceWithRole)
async def get_active_workspace(
    ctx: WorkspaceDep, session: SessionDep
) -> WorkspaceWithRole:
    return await _with_role(session, ctx.workspace, ctx.role)


@router.get("/active/permissions", response_model=WorkspacePermissions)
async def get_permissions(ctx: WorkspaceDep) -> WorkspacePermissions:
    """What the caller may do in the active workspace, so the UI can hide
    actions that would 403 (the platform's /blocked-exit/permissions)."""
    return WorkspacePermissions(
        workspace_id=ctx.workspace.id,
        role=ctx.role,
        can_resolve=ctx.role.can_act_as(WorkspaceRole.MEMBER),
        can_manage=ctx.role.can_act_as(WorkspaceRole.ADMIN),
        is_superadmin=ctx.user.is_superadmin,
    )


@router.post("/{workspace_id}/activate", response_model=WorkspaceWithRole)
async def activate_workspace(
    workspace_id: int, session: SessionDep, user: CurrentUserDep
) -> WorkspaceWithRole:
    """Switch the caller's active workspace. Applies to every session at once,
    like the platform's, because it is stored on the user."""
    workspace, role = await auth_service.activate_workspace(session, user, workspace_id)
    return await _with_role(session, workspace, role)


@router.get("/{workspace_id}", response_model=WorkspaceWithRole)
async def get_workspace(
    workspace_id: int, session: SessionDep, user: CurrentUserDep
) -> WorkspaceWithRole:
    workspace, role = await _visible_workspace(session, user, workspace_id)
    return await _with_role(session, workspace, role)


@router.get("/{workspace_id}/cameras", response_model=list[WorkspaceCamera])
async def list_workspace_cameras(
    workspace_id: int, session: SessionDep, user: CurrentUserDep
) -> list[WorkspaceCamera]:
    """Cameras of any workspace the caller can see -- for a superadmin, any
    workspace at all, without switching into it first."""
    workspace, _ = await _visible_workspace(session, user, workspace_id)
    cameras = (
        await session.execute(
            select(Camera)
            .where(Camera.workspace_id == workspace.id)
            .order_by(Camera.name)
        )
    ).scalars()
    return [
        WorkspaceCamera(
            id=c.id,
            name=c.name,
            location=c.location,
            enabled=c.enabled,
            strategy=c.strategy,
            source=redact_url(c.rtsp_url),
            created_at=c.created_at,
        )
        for c in cameras
    ]


# --- superadmin: workspace lifecycle ------------------------------------------
@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate, session: SessionDep, user: SuperadminDep
) -> Workspace:
    if await session.scalar(select(Workspace.id).where(Workspace.name == payload.name)):
        raise ConflictError(f"A workspace named {payload.name!r} already exists")
    slug = payload.slug or slugify(payload.name)
    if await session.scalar(select(Workspace.id).where(Workspace.slug == slug)):
        raise ConflictError(f"Workspace slug {slug!r} is already taken")

    workspace = Workspace(
        name=payload.name,
        slug=slug,
        description=payload.description,
        camera_quota=payload.camera_quota,
    )
    session.add(workspace)
    await session.flush()
    # The creator joins as its admin, as on the platform, so the workspace
    # shows up in their own list even if their superadmin role is removed.
    session.add(
        WorkspaceMember(
            workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.ADMIN.value
        )
    )
    await session.commit()
    await session.refresh(workspace)
    return workspace


@router.patch("/{workspace_id}", response_model=WorkspaceRead)
async def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    session: SessionDep,
    _admin: SuperadminDep,
    manager: ManagerDep,
) -> Workspace:
    workspace = await _require_workspace(session, workspace_id)
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] != workspace.name:
        if await session.scalar(
            select(Workspace.id).where(Workspace.name == changes["name"])
        ):
            raise ConflictError(f"A workspace named {changes['name']!r} already exists")
    for field, value in changes.items():
        setattr(workspace, field, value)
    await session.commit()
    await session.refresh(workspace)
    if changes.get("is_active") is False:
        await _stop_workspace_cameras(session, manager, workspace.id)
    return workspace


async def _stop_workspace_cameras(
    session: SessionDep, manager: ManagerDep, workspace_id: int
) -> None:
    camera_ids = (
        (
            await session.execute(
                select(Camera.id).where(Camera.workspace_id == workspace_id)
            )
        )
        .scalars()
        .all()
    )
    for camera_id in camera_ids:
        await manager.stop(camera_id)


@router.post("/{workspace_id}/deactivate", response_model=WorkspaceRead)
async def deactivate_workspace(
    workspace_id: int, session: SessionDep, _admin: SuperadminDep, manager: ManagerDep
) -> Workspace:
    """Stop every camera in the workspace and lock it. Members are moved to
    another workspace on their next request; nobody can switch back into it
    until it is reactivated (PATCH is_active=true)."""
    workspace = await _require_workspace(session, workspace_id)
    workspace.is_active = False
    await session.commit()
    await session.refresh(workspace)
    await _stop_workspace_cameras(session, manager, workspace.id)
    return workspace


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: int, session: SessionDep, _admin: SuperadminDep, manager: ManagerDep
) -> None:
    """Delete a workspace and, by cascade, its cameras, events and alerts.

    It must be deactivated first: a two-step delete means a single mis-click
    can never wipe a tenant that is live.
    """
    workspace = await _require_workspace(session, workspace_id)
    if workspace.is_active:
        raise ConflictError("Deactivate the workspace before deleting it")
    await _stop_workspace_cameras(session, manager, workspace.id)
    await session.delete(workspace)
    await session.commit()


# --- membership -----------------------------------------------------------------
async def _member_read(member: WorkspaceMember, user: User) -> MemberRead:
    return MemberRead(
        id=member.id,
        user_id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=WorkspaceRole(member.role),
        is_active=user.is_active,
        created_at=member.created_at,
    )


@router.get("/{workspace_id}/members", response_model=list[MemberRead])
async def list_members(
    workspace_id: int, session: SessionDep, user: CurrentUserDep
) -> list[MemberRead]:
    workspace, _ = await _visible_workspace(session, user, workspace_id)
    rows = (
        await session.execute(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == workspace.id)
            .order_by(User.username)
        )
    ).all()
    return [await _member_read(member, u) for member, u in rows]


async def _admin_count(session: SessionDep, workspace_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(WorkspaceMember.id)).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == WorkspaceRole.ADMIN.value,
            )
        )
        or 0
    )


async def _require_member(
    session: SessionDep, workspace_id: int, member_id: int
) -> WorkspaceMember:
    member = await session.get(WorkspaceMember, member_id)
    if member is None or member.workspace_id != workspace_id:
        raise NotFoundError(f"Member {member_id} not found")
    return member


@router.post(
    "/{workspace_id}/members",
    response_model=MemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    workspace_id: int, payload: MemberAdd, session: SessionDep, _admin: SuperadminDep
) -> MemberRead:
    workspace = await _require_workspace(session, workspace_id)
    if payload.user_id is None and not payload.email and not payload.username:
        raise ConflictError("Provide a user_id, email or username to add")

    if payload.user_id is not None:
        target = await session.get(User, payload.user_id)
    else:
        target = await session.scalar(
            select(User).where(
                or_(
                    User.email == (payload.email.lower() if payload.email else None),
                    User.username == payload.username,
                )
            )
        )
    if target is None:
        raise NotFoundError(
            "No account matches -- create it first under Users, then add it here"
        )

    if await auth_service.get_membership(
        session, user_id=target.id, workspace_id=workspace.id
    ):
        raise ConflictError(f"{target.username} is already a member of this workspace")

    member = WorkspaceMember(
        workspace_id=workspace.id, user_id=target.id, role=payload.role.value
    )
    session.add(member)
    # Someone with nowhere else to go lands here at their next request anyway;
    # recording it keeps /auth/me honest.
    if target.default_workspace_id is None:
        target.default_workspace_id = workspace.id
    await session.commit()
    await session.refresh(member)
    return await _member_read(member, target)


@router.patch("/{workspace_id}/members/{member_id}", response_model=MemberRead)
async def update_member(
    workspace_id: int,
    member_id: int,
    payload: MemberUpdate,
    session: SessionDep,
    _admin: SuperadminDep,
) -> MemberRead:
    member = await _require_member(session, workspace_id, member_id)
    if (
        member.role == WorkspaceRole.ADMIN.value
        and payload.role is not WorkspaceRole.ADMIN
        and await _admin_count(session, workspace_id) <= 1
    ):
        raise ConflictError("A workspace must keep at least one admin")
    member.role = payload.role.value
    await session.commit()
    return await _member_read(member, await session.get(User, member.user_id))


@router.delete(
    "/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    workspace_id: int, member_id: int, session: SessionDep, _admin: SuperadminDep
) -> None:
    member = await _require_member(session, workspace_id, member_id)
    if (
        member.role == WorkspaceRole.ADMIN.value
        and await _admin_count(session, workspace_id) <= 1
    ):
        raise ConflictError("A workspace must keep at least one admin")
    await session.delete(member)
    await session.commit()
