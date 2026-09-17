"""User accounts, workspace provisioning, and token lifecycle.

Splits the reference service's `user_service` + `session_service` in two halves
of one module, minus the OTP / email / PKCE surface this app has no use for.

Everything that needs a database lives here; the pure crypto lives in
`app.core.security`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.enums import TokenType, UserRole, WorkspaceRole
from app.core.exceptions import AuthError, ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.core.security import TokenError
from app.models.user import RevokedToken, User, Workspace, WorkspaceMember
from app.schemas.auth import TokenPair
from app.schemas.workspace import slugify
from app.utils.timing import utcnow

logger = get_logger(__name__)


# --- lookups ---------------------------------------------------------------
async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_login(session: AsyncSession, identifier: str) -> User | None:
    """Look a user up by username or email, case-insensitively."""
    needle = identifier.strip().lower()
    return await session.scalar(
        select(User).where(
            or_(
                func.lower(User.username) == needle,
                func.lower(User.email) == needle,
            )
        )
    )


async def user_count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count(User.id))) or 0)


# --- registration ------------------------------------------------------------
async def _unique_slug(session: AsyncSession, base: str) -> str:
    """acme, then acme-2, acme-3... until one is free."""
    slug = slugify(base)
    candidate, suffix = slug, 1
    while await session.scalar(select(Workspace.id).where(Workspace.slug == candidate)):
        suffix += 1
        candidate = f"{slug}-{suffix}"
    return candidate


async def create_user_with_workspace(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
    full_name: str | None = None,
    workspace_name: str | None = None,
) -> tuple[User, Workspace]:
    """Register an account and the workspace it owns, in one transaction.

    The first account ever created becomes a platform admin -- the same
    bootstrap rule as the reference service. Without it a fresh deployment has
    no way to reach the admin-only routes, since there is nobody to grant them.
    """
    email = email.strip().lower()
    username = username.strip()

    clash = await session.scalar(
        select(User).where(
            or_(
                func.lower(User.username) == username.lower(),
                func.lower(User.email) == email,
            )
        )
    )
    if clash is not None:
        # Which one clashed is not disclosed: that would turn signup into an
        # oracle for "does this person have an account here".
        raise ConflictError("That username or email is already registered")

    is_first_user = await user_count(session) == 0

    default_workspace_name = workspace_name or f"{username} workspace"
    workspace = Workspace(
        name=default_workspace_name[:120],
        slug=await _unique_slug(session, workspace_name or username),
    )
    session.add(workspace)
    # Flush, not commit: the workspace id is needed for the rows below, but the
    # whole registration must still roll back as one unit if anything fails.
    await session.flush()

    user = User(
        username=username,
        email=email,
        full_name=full_name,
        password_hash=security.hash_password(password),
        role=UserRole.ADMIN.value if is_first_user else UserRole.USER.value,
        default_workspace_id=workspace.id,
    )
    session.add(user)
    await session.flush()

    session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.OWNER.value,
        )
    )
    await session.commit()
    await session.refresh(user)
    await session.refresh(workspace)

    logger.info(
        "Registered user %s (platform_admin=%s) with workspace %s",
        user.username,
        is_first_user,
        workspace.slug,
    )
    return user, workspace


# --- authentication ----------------------------------------------------------
async def authenticate(session: AsyncSession, *, identifier: str, password: str) -> User:
    """Verify credentials, or raise AuthError.

    Every failure returns the same message. Distinguishing "no such user" from
    "wrong password" tells an attacker which half to keep working on.
    """
    generic = AuthError("Incorrect username or password")

    user = await get_user_by_login(session, identifier)
    if user is None:
        # Hash anyway so a missing user does not answer measurably faster than
        # a wrong password -- that timing difference enumerates accounts.
        security.hash_password(password)
        raise generic

    if not security.verify_password(password, user.password_hash):
        raise generic

    if not user.is_active:
        # Safe to be specific: they proved they own the account.
        raise ForbiddenError("This account has been deactivated")

    # Cost parameters may have been raised since this hash was written; the one
    # moment we hold the plaintext is the only chance to upgrade it.
    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)

    user.last_login_at = utcnow()
    await session.commit()
    return user


# --- workspace membership -----------------------------------------------------
async def get_membership(
    session: AsyncSession, *, user_id: int, workspace_id: int
) -> WorkspaceMember | None:
    return await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
    )


async def list_memberships(
    session: AsyncSession, user_id: int
) -> list[tuple[WorkspaceMember, Workspace]]:
    rows = await session.execute(
        select(WorkspaceMember, Workspace)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == user_id, Workspace.is_active.is_(True))
        .order_by(Workspace.name)
    )
    return [(m, w) for m, w in rows.all()]


async def resolve_default_workspace(
    session: AsyncSession, user: User
) -> Workspace | None:
    """The workspace this user lands in when they do not name one.

    Their stored default if it is still valid, otherwise any workspace they
    belong to -- a user whose default workspace was deleted should still be
    able to log in and see the rest.
    """
    if user.default_workspace_id is not None:
        membership = await get_membership(
            session, user_id=user.id, workspace_id=user.default_workspace_id
        )
        if membership is not None:
            workspace = await session.get(Workspace, user.default_workspace_id)
            if workspace is not None and workspace.is_active:
                return workspace

    memberships = await list_memberships(session, user.id)
    return memberships[0][1] if memberships else None


# --- tokens --------------------------------------------------------------------
async def issue_token_pair(
    session: AsyncSession, *, user: User, workspace_id: int | None
) -> TokenPair:
    access, _, access_exp = security.create_token(
        user_id=user.id,
        workspace_id=workspace_id,
        token_type=TokenType.ACCESS,
        role=user.role,
    )
    refresh, _, _ = security.create_token(
        user_id=user.id,
        workspace_id=workspace_id,
        token_type=TokenType.REFRESH,
        role=user.role,
    )
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_at=access_exp,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


async def is_revoked(session: AsyncSession, jti: str) -> bool:
    return (
        await session.scalar(select(RevokedToken.id).where(RevokedToken.jti == jti))
    ) is not None


async def revoke(
    session: AsyncSession,
    *,
    jti: str,
    user_id: int | None,
    expires_at: datetime,
    token_type: str = TokenType.ACCESS.value,
    reason: str | None = None,
    commit: bool = True,
) -> None:
    """Record a jti as dead. Idempotent -- revoking twice is not an error."""
    if await is_revoked(session, jti):
        return
    session.add(
        RevokedToken(
            jti=jti,
            user_id=user_id,
            token_type=token_type,
            expires_at=expires_at,
            reason=reason,
        )
    )
    if commit:
        await session.commit()


async def revoke_token_string(
    session: AsyncSession, token: str, *, reason: str | None = None
) -> bool:
    """Revoke a token given the encoded string. False when it was unusable.

    An expired or malformed token is not an error here: logging out with one is
    exactly as effective as logging out with a valid one, so callers should not
    have to care.
    """
    try:
        claims = security.decode_token(token)
    except TokenError:
        return False

    await revoke(
        session,
        jti=claims["jti"],
        user_id=int(claims["sub"]) if claims.get("sub") else None,
        expires_at=datetime.fromtimestamp(claims["exp"], tz=utcnow().tzinfo),
        token_type=claims.get("token_type", TokenType.ACCESS.value),
        reason=reason,
        commit=False,
    )
    return True


async def rotate_refresh_token(session: AsyncSession, refresh_token: str) -> TokenPair:
    """Exchange a refresh token for a new pair, burning the one presented.

    Rotation is the point: a stolen refresh token works once, and the moment
    the legitimate client tries to use it again the revocation check rejects
    it, so the theft surfaces instead of granting indefinite quiet access.
    """
    try:
        claims = security.decode_token(refresh_token, expected_type=TokenType.REFRESH)
    except TokenError as exc:
        raise AuthError(str(exc)) from exc

    if await is_revoked(session, claims["jti"]):
        raise AuthError("This refresh token has already been used or revoked")

    user = await get_user_by_id(session, int(claims["sub"]))
    if user is None or not user.is_active:
        raise AuthError("User no longer exists or is inactive")

    await revoke(
        session,
        jti=claims["jti"],
        user_id=user.id,
        expires_at=datetime.fromtimestamp(claims["exp"], tz=utcnow().tzinfo),
        token_type=TokenType.REFRESH.value,
        reason="rotated",
        commit=False,
    )

    workspace_id = claims.get("workspace_id")
    # The workspace may have been revoked from this user since the token was
    # minted, so re-check rather than carrying the claim forward blindly.
    if workspace_id is not None:
        membership = await get_membership(
            session, user_id=user.id, workspace_id=workspace_id
        )
        if membership is None and not user.is_platform_admin:
            workspace = await resolve_default_workspace(session, user)
            workspace_id = workspace.id if workspace else None

    pair = await issue_token_pair(session, user=user, workspace_id=workspace_id)
    await session.commit()
    return pair


async def revoke_all_for_user(
    session: AsyncSession, user_id: int, *, reason: str = "password_change"
) -> None:
    """Invalidate every outstanding token for one user.

    There is no list of issued tokens to walk, so this works by a sentinel
    cutoff row instead: `deps.get_current_user` rejects any access token whose
    `iat` predates the newest cutoff row for that user.
    """
    session.add(
        RevokedToken(
            jti=f"user-cutoff:{user_id}:{utcnow().timestamp()}",
            user_id=user_id,
            token_type="cutoff",
            # Outlives any token that could still be valid.
            expires_at=utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS + 1),
            reason=reason,
        )
    )
    await session.commit()


async def latest_cutoff(session: AsyncSession, user_id: int) -> datetime | None:
    """Most recent revoke_all_for_user() timestamp for this user, if any."""
    row = await session.scalar(
        select(RevokedToken.revoked_at)
        .where(RevokedToken.user_id == user_id, RevokedToken.token_type == "cutoff")
        .order_by(RevokedToken.revoked_at.desc())
        .limit(1)
    )
    return row


async def purge_expired_revocations(session: AsyncSession) -> int:
    """Drop revocation rows whose tokens have expired anyway.

    Past expires_at the signature check rejects the token on its own, so the
    row stops carrying information and becomes pure table growth. Cutoff rows
    are exempt: they are compared by revoked_at, not expires_at, against every
    access token's iat, for as long as a token of that lifetime could exist.
    """
    result = await session.execute(
        delete(RevokedToken).where(
            RevokedToken.token_type != "cutoff",
            RevokedToken.expires_at < utcnow(),
        )
    )
    return int(result.rowcount or 0)


# --- password management -------------------------------------------------------
async def change_password(
    session: AsyncSession, *, user: User, current_password: str, new_password: str
) -> None:
    if not security.verify_password(current_password, user.password_hash):
        raise AuthError("Current password is incorrect")
    user.password_hash = security.hash_password(new_password)
    await session.commit()
    await revoke_all_for_user(session, user.id, reason="password_change")


async def require_user(session: AsyncSession, user_id: int) -> User:
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    return user
