"""Signup, login, token refresh, and the current-user profile."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import CurrentUserDep, PlatformAdminDep, SessionDep
from app.core.config import settings
from app.core.exceptions import ForbiddenError
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    MembershipRead,
    PasswordChange,
    RefreshRequest,
    SignupRequest,
    TokenPair,
    UserAdminUpdate,
    UserProfile,
    UserRead,
    UserUpdate,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/signup", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, session: SessionDep) -> TokenPair:
    # The very first account bootstraps the platform regardless of this flag --
    # otherwise a deployment with ALLOW_OPEN_SIGNUP=false could never be used.
    if not settings.ALLOW_OPEN_SIGNUP and await auth_service.user_count(session) > 0:
        raise ForbiddenError(
            "Open signup is disabled. Ask a workspace admin to add your account."
        )

    user, workspace = await auth_service.create_user_with_workspace(
        session,
        username=payload.username,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        workspace_name=payload.workspace_name,
    )
    return await auth_service.issue_token_pair(
        session, user=user, workspace_id=workspace.id
    )


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, session: SessionDep) -> TokenPair:
    user = await auth_service.authenticate(
        session, identifier=payload.username, password=payload.password
    )

    workspace_id = payload.workspace_id
    if workspace_id is not None:
        membership = await auth_service.get_membership(
            session, user_id=user.id, workspace_id=workspace_id
        )
        if membership is None and not user.is_platform_admin:
            # Do not confirm the workspace exists -- same reasoning as
            # resolve_workspace: fall back rather than leak.
            workspace_id = None

    if workspace_id is None:
        workspace = await auth_service.resolve_default_workspace(session, user)
        workspace_id = workspace.id if workspace else None

    return await auth_service.issue_token_pair(
        session, user=user, workspace_id=workspace_id
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, session: SessionDep) -> TokenPair:
    return await auth_service.rotate_refresh_token(session, payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: LogoutRequest, session: SessionDep, user: CurrentUserDep
) -> None:
    """Revoke the tokens presented. Best-effort: an already-expired or
    malformed token is not an error -- the point is the session ending, and it
    ends either way."""
    if payload.refresh_token:
        await auth_service.revoke_token_string(
            session, payload.refresh_token, reason="logout"
        )
    await session.commit()


@router.get("/me", response_model=UserProfile)
async def me(session: SessionDep, user: CurrentUserDep) -> UserProfile:
    memberships = await auth_service.list_memberships(session, user.id)
    return UserProfile(
        **UserRead.model_validate(user, from_attributes=True).model_dump(),
        memberships=[
            MembershipRead(
                workspace_id=w.id,
                workspace_name=w.name,
                workspace_slug=w.slug,
                role=m.role,
            )
            for m, w in memberships
        ],
    )


@router.patch("/me", response_model=UserProfile)
async def update_me(
    payload: UserUpdate, session: SessionDep, user: CurrentUserDep
) -> UserProfile:
    changes = payload.model_dump(exclude_unset=True)
    if "default_workspace_id" in changes and changes["default_workspace_id"] is not None:
        membership = await auth_service.get_membership(
            session, user_id=user.id, workspace_id=changes["default_workspace_id"]
        )
        if membership is None and not user.is_platform_admin:
            raise ForbiddenError("You are not a member of that workspace")
    for field, value in changes.items():
        setattr(user, field, value)
    await session.commit()
    return await me(session, user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChange, session: SessionDep, user: CurrentUserDep
) -> None:
    await auth_service.change_password(
        session,
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )


# --- platform-admin user management ------------------------------------------
# Every account on the deployment, not scoped to any one workspace -- distinct
# from GET /workspaces/{id}/members, which lists one workspace's roster.
@router.get("/users", response_model=list[UserRead])
async def list_all_users(session: SessionDep, _admin: PlatformAdminDep) -> list[User]:
    rows = await session.execute(select(User).order_by(User.username))
    return list(rows.scalars().all())


@router.patch("/users/{user_id}", response_model=UserRead)
async def admin_update_user(
    user_id: int, payload: UserAdminUpdate, session: SessionDep, admin: PlatformAdminDep
) -> User:
    target = await auth_service.require_user(session, user_id)
    changes = payload.model_dump(exclude_unset=True)

    if "is_active" in changes and changes["is_active"] is False and target.id == admin.id:
        raise ForbiddenError("You cannot deactivate your own account")
    if "role" in changes and changes["role"] != target.role and target.id == admin.id:
        raise ForbiddenError("You cannot change your own platform role")

    for field, value in changes.items():
        setattr(target, field, value.value if hasattr(value, "value") else value)
    await session.commit()
    await session.refresh(target)

    if changes.get("is_active") is False:
        await auth_service.revoke_all_for_user(session, target.id, reason="deactivated")
    return target
