"""Workspace CRUD and membership management."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import func, or_, select

from app.api.deps import (
    AdminCtxDep,
    CurrentUserDep,
    SessionDep,
    ViewerCtxDep,
    WorkspaceDep,
)
from app.core.enums import WorkspaceRole
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.camera import Camera
from app.models.user import User, Workspace, WorkspaceMember
from app.schemas.workspace import (
    MemberAdd,
    MemberRead,
    MemberUpdate,
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceUpdate,
    WorkspaceWithRole,
    slugify,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceWithRole])
async def list_my_workspaces(
    session: SessionDep, user: CurrentUserDep
) -> list[WorkspaceWithRole]:
    """Every workspace this user belongs to, admin bypass included."""
    if user.is_platform_admin:
        rows = (
            (await session.execute(select(Workspace).order_by(Workspace.name)))
            .scalars()
            .all()
        )
        pairs = [(WorkspaceRole.OWNER, w) for w in rows]
    else:
        pairs = [
            (WorkspaceRole(m.role), w)
            for m, w in await auth_service.list_memberships(session, user.id)
        ]

    out = []
    for role, workspace in pairs:
        count = await session.scalar(
            select(func.count(Camera.id)).where(Camera.workspace_id == workspace.id)
        )
        out.append(
            WorkspaceWithRole(
                **WorkspaceRead.model_validate(
                    workspace, from_attributes=True
                ).model_dump(),
                role=role,
                camera_count=int(count or 0),
            )
        )
    return out


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate, session: SessionDep, user: CurrentUserDep
) -> Workspace:
    """Any authenticated user may create a workspace and becomes its owner --
    this is not platform-admin gated, unlike managing *someone else's*."""
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
    session.add(
        WorkspaceMember(
            workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER.value
        )
    )
    if user.default_workspace_id is None:
        user.default_workspace_id = workspace.id
    await session.commit()
    await session.refresh(workspace)
    return workspace


@router.get("/{workspace_id}", response_model=WorkspaceWithRole)
async def get_workspace(ctx: WorkspaceDep, session: SessionDep) -> WorkspaceWithRole:
    count = await session.scalar(
        select(func.count(Camera.id)).where(Camera.workspace_id == ctx.workspace.id)
    )
    return WorkspaceWithRole(
        **WorkspaceRead.model_validate(ctx.workspace, from_attributes=True).model_dump(),
        role=ctx.role,
        camera_count=int(count or 0),
    )


@router.patch("/{workspace_id}", response_model=WorkspaceRead)
async def update_workspace(
    payload: WorkspaceUpdate,
    session: SessionDep,
    ctx: AdminCtxDep,
) -> Workspace:
    changes = payload.model_dump(exclude_unset=True)
    # Quota and activation bypass workspace-role checks entirely, because an
    # admin *of the workspace* raising their own resource ceiling defeats the
    # point of having one.
    if (
        "camera_quota" in changes or "is_active" in changes
    ) and not ctx.user.is_platform_admin:
        raise ForbiddenError(
            "Only a platform administrator can change quota or activation"
        )
    for field, value in changes.items():
        setattr(ctx.workspace, field, value)
    await session.commit()
    await session.refresh(ctx.workspace)
    return ctx.workspace


@router.get("/{workspace_id}/members", response_model=list[MemberRead])
async def list_members(
    session: SessionDep,
    ctx: ViewerCtxDep,
) -> list[MemberRead]:
    rows = (
        await session.execute(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == ctx.workspace.id)
            .order_by(User.username)
        )
    ).all()
    return [
        MemberRead(
            id=member.id,
            user_id=u.id,
            username=u.username,
            email=u.email,
            full_name=u.full_name,
            role=WorkspaceRole(member.role),
            is_active=u.is_active,
            created_at=member.created_at,
        )
        for member, u in rows
    ]


@router.post(
    "/{workspace_id}/members",
    response_model=MemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    payload: MemberAdd,
    session: SessionDep,
    ctx: AdminCtxDep,
) -> MemberRead:
    if not payload.email and not payload.username:
        raise ConflictError("Provide an email or a username to add")

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
            "No account with that email/username exists yet -- they must sign "
            "up before they can be added to a workspace"
        )

    existing = await auth_service.get_membership(
        session, user_id=target.id, workspace_id=ctx.workspace.id
    )
    if existing is not None:
        raise ConflictError(f"{target.username} is already a member of this workspace")

    # An ADMIN cannot hand out OWNER -- only an existing OWNER (or a platform
    # admin) can create a peer.
    if payload.role is WorkspaceRole.OWNER and not (
        ctx.role is WorkspaceRole.OWNER or ctx.user.is_platform_admin
    ):
        raise ForbiddenError("Only an owner can grant the owner role")

    member = WorkspaceMember(
        workspace_id=ctx.workspace.id, user_id=target.id, role=payload.role.value
    )
    session.add(member)
    await session.commit()
    await session.refresh(member)

    return MemberRead(
        id=member.id,
        user_id=target.id,
        username=target.username,
        email=target.email,
        full_name=target.full_name,
        role=payload.role,
        is_active=target.is_active,
        created_at=member.created_at,
    )


@router.patch("/{workspace_id}/members/{member_id}", response_model=MemberRead)
async def update_member(
    member_id: int,
    payload: MemberUpdate,
    session: SessionDep,
    ctx: AdminCtxDep,
) -> MemberRead:
    member = await session.get(WorkspaceMember, member_id)
    if member is None or member.workspace_id != ctx.workspace.id:
        raise NotFoundError(f"Member {member_id} not found")

    if payload.role is WorkspaceRole.OWNER and not (
        ctx.role is WorkspaceRole.OWNER or ctx.user.is_platform_admin
    ):
        raise ForbiddenError("Only an owner can grant the owner role")
    if (
        member.role == WorkspaceRole.OWNER.value
        and ctx.role is not WorkspaceRole.OWNER
        and not ctx.user.is_platform_admin
    ):
        raise ForbiddenError("Only an owner can change another owner's role")

    member.role = payload.role.value
    await session.commit()

    target = await session.get(User, member.user_id)
    return MemberRead(
        id=member.id,
        user_id=target.id,
        username=target.username,
        email=target.email,
        full_name=target.full_name,
        role=payload.role,
        is_active=target.is_active,
        created_at=member.created_at,
    )


@router.delete(
    "/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    member_id: int,
    session: SessionDep,
    ctx: AdminCtxDep,
) -> None:
    member = await session.get(WorkspaceMember, member_id)
    if member is None or member.workspace_id != ctx.workspace.id:
        raise NotFoundError(f"Member {member_id} not found")
    if member.role == WorkspaceRole.OWNER.value:
        owner_count = await session.scalar(
            select(func.count(WorkspaceMember.id)).where(
                WorkspaceMember.workspace_id == ctx.workspace.id,
                WorkspaceMember.role == WorkspaceRole.OWNER.value,
            )
        )
        if int(owner_count or 0) <= 1:
            raise ConflictError("A workspace must keep at least one owner")
    await session.delete(member)
    await session.commit()
