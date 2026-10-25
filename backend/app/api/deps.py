"""Shared FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.enums import TokenType, WorkspaceRole
from app.core.exceptions import AuthError, ForbiddenError, NotFoundError
from app.core.security import TokenError, decode_token
from app.models.camera import Camera
from app.models.user import User, Workspace
from app.services import auth as auth_service
from app.services.stream_manager import StreamManager, stream_manager

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_stream_manager() -> StreamManager:
    return stream_manager


ManagerDep = Annotated[StreamManager, Depends(get_stream_manager)]


# auto_error=False so a missing header raises our own AuthError -- keeping the
# {error, message, details} envelope every other failure in this API uses,
# instead of FastAPI's bare {"detail": "..."} for this one path.
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    """Decode the bearer token and load the user it names.

    Every rejection reason -- missing header, bad signature, expired, wrong
    token type, revoked, deactivated -- collapses to the same 401. A client
    that needs a specific reason has bugs an error code will not fix, and a
    would-be attacker only learns "not right now" either way.
    """
    if credentials is None:
        raise AuthError("Missing bearer token")

    try:
        claims = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
    except TokenError as exc:
        raise AuthError(str(exc)) from exc

    jti = claims.get("jti")
    if jti and await auth_service.is_revoked(session, jti):
        raise AuthError("Token has been revoked")

    user = await auth_service.get_user_by_id(session, int(claims["sub"]))
    if user is None or not user.is_active:
        raise AuthError("User not found or inactive")

    # A password change (or an admin-forced logout) stamps a cutoff row; any
    # access token minted before that moment must stop working immediately,
    # not linger until its own expiry.
    if await auth_service.issued_before_cutoff(session, user.id, claims.get("iat")):
        raise AuthError("Session has been invalidated, please log in again")

    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


@dataclass
class WorkspaceContext:
    user: User
    workspace: Workspace
    role: WorkspaceRole


async def resolve_workspace(
    session: SessionDep, user: CurrentUserDep
) -> WorkspaceContext:
    """Which workspace this request acts in, and what the caller may do there.

    The platform's model: the active workspace is stored server-side on the
    user (POST /workspaces/{id}/activate), not chosen per request, so every tab
    and every <img> fetch agrees on it. Membership is re-checked on each call,
    so a removed member loses access at once rather than when a token expires.
    """
    workspace = await auth_service.resolve_active_workspace(session, user)
    if workspace is None:
        raise NotFoundError(
            "No active workspace. Ask a superadmin to add you to a workspace."
        )
    role = await auth_service.workspace_role_for(session, user, workspace)
    if role is None:  # pragma: no cover - resolve_active_workspace checked it
        raise NotFoundError(f"Workspace {workspace.id} not found")
    return WorkspaceContext(user=user, workspace=workspace, role=role)


WorkspaceDep = Annotated[WorkspaceContext, Depends(resolve_workspace)]


def require_workspace_role(minimum: WorkspaceRole):
    """Dependency factory: 403 unless the caller's role in this workspace
    outranks `minimum`. Rank-based so inserting a role in the middle later
    does not mean revisiting every call site.

    Two ways to use the result:
      - `dependencies=[Depends(require_workspace_role(...))]` on the route,
        when the handler does not need the resolved context itself.
      - `ctx: Annotated[WorkspaceContext, Depends(require_workspace_role(...))]`
        as a parameter, when it does. (`ctx: WorkspaceDep = Depends(...)` looks
        equivalent but FastAPI rejects combining Annotated-with-Depends and a
        `= Depends(...)` default on the same parameter.)
    """

    async def _check(ctx: WorkspaceDep) -> WorkspaceContext:
        if not ctx.role.can_act_as(minimum):
            raise ForbiddenError(
                f"Requires {minimum.value} role or higher in this workspace "
                f"(you have {ctx.role.value})"
            )
        return ctx

    return _check


ViewerCtxDep = Annotated[
    WorkspaceContext, Depends(require_workspace_role(WorkspaceRole.VIEWER))
]
MemberCtxDep = Annotated[
    WorkspaceContext, Depends(require_workspace_role(WorkspaceRole.MEMBER))
]
AdminCtxDep = Annotated[
    WorkspaceContext, Depends(require_workspace_role(WorkspaceRole.ADMIN))
]


async def require_superadmin(user: CurrentUserDep) -> User:
    if not user.is_superadmin:
        raise ForbiddenError("Requires a superadmin")
    return user


SuperadminDep = Annotated[User, Depends(require_superadmin)]


async def get_camera_or_404(
    camera_id: int, ctx: WorkspaceDep, session: SessionDep
) -> Camera:
    """Tenant-scoped lookup: a camera in another workspace is a 404, exactly
    like one that does not exist. Anything else would confirm its existence to
    a caller who should not even know to ask."""
    camera = await session.scalar(
        select(Camera).where(
            Camera.id == camera_id, Camera.workspace_id == ctx.workspace.id
        )
    )
    if camera is None:
        raise NotFoundError(f"Camera {camera_id} not found")
    return camera


CameraDep = Annotated[Camera, Depends(get_camera_or_404)]


async def get_camera_via_ticket_or_bearer(
    camera_id: int,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    ticket: str | None = None,
) -> Camera:
    """Camera lookup for `<img src>` endpoints (stream, snapshot).

    An `<img>` tag cannot send an Authorization header, so these two routes
    additionally accept `?ticket=` -- a single-camera token minted by POST
    /monitoring/{id}/stream-ticket. A normal bearer token still works too, for
    a blob-fetched `<img>` or any other programmatic caller.
    """
    if ticket is not None:
        try:
            claims = decode_token(ticket, expected_type=TokenType.STREAM)
        except TokenError as exc:
            raise AuthError(str(exc)) from exc
        if claims.get("camera_id") != camera_id:
            raise AuthError("This ticket is not valid for this camera")
        camera = await session.scalar(
            select(Camera).where(
                Camera.id == camera_id, Camera.workspace_id == claims.get("workspace_id")
            )
        )
        if camera is None:
            raise NotFoundError(f"Camera {camera_id} not found")
        return camera

    user = await get_current_user(session, credentials)
    ctx = await resolve_workspace(session, user)
    return await get_camera_or_404(camera_id, ctx, session)


CameraViaTicketDep = Annotated[Camera, Depends(get_camera_via_ticket_or_bearer)]


class Pagination:
    def __init__(self, limit: int = 50, offset: int = 0) -> None:
        self.limit = max(1, min(limit, 500))
        self.offset = max(0, offset)


PaginationDep = Annotated[Pagination, Depends()]
