"""User accounts, workspace provisioning, and token lifecycle.

Splits the reference service's `user_service` + `session_service` in two halves
of one module, minus the PKCE surface this app has no use for. The emailed
password reset code lives in `app.services.otp`.

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
from app.services import otp
from app.utils.timing import utcnow

logger = get_logger(__name__)

DEFAULT_WORKSPACE_SLUG = "default"
DEFAULT_WORKSPACE_NAME = "Default Workspace"


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


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Email only, case-insensitively: what a person types at password reset."""
    return await session.scalar(
        select(User).where(func.lower(User.email) == email.strip().lower())
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


async def _check_identity_free(
    session: AsyncSession, *, username: str, email: str
) -> None:
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


async def _default_workspace(session: AsyncSession, name: str | None = None) -> Workspace:
    """The shared workspace self-registered accounts join, created on first use."""
    workspace = await session.scalar(
        select(Workspace).where(Workspace.slug == DEFAULT_WORKSPACE_SLUG)
    )
    if workspace is None:
        workspace = Workspace(
            name=(name or DEFAULT_WORKSPACE_NAME)[:120],
            slug=DEFAULT_WORKSPACE_SLUG,
        )
        session.add(workspace)
        await session.flush()
    return workspace


async def signup(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
    full_name: str | None = None,
    workspace_name: str | None = None,
) -> tuple[User, Workspace]:
    """Self-registration, which the platform allows in two cases only.

    The very first account bootstraps the deployment: it becomes SUPERADMIN
    and the admin of a fresh "Default Workspace" (named `workspace_name` when
    given). Later accounts arrive here only when ALLOW_OPEN_SIGNUP is on, and
    join that shared workspace as a MEMBER -- they never get a tenant of their
    own; creating tenants is the superadmin's job.
    """
    email = email.strip().lower()
    username = username.strip()
    await _check_identity_free(session, username=username, email=email)

    is_first_user = await user_count(session) == 0
    workspace = await _default_workspace(
        session, workspace_name if is_first_user else None
    )
    if is_first_user and workspace_name and workspace.name != workspace_name:
        # Migration 0002 seeds a "Default" workspace even on a fresh database;
        # the bootstrap account gets to name it.
        workspace.name = workspace_name[:120]

    user = User(
        username=username,
        email=email,
        full_name=full_name,
        password_hash=security.hash_password(password),
        role=UserRole.SUPERADMIN.value if is_first_user else UserRole.USER.value,
        default_workspace_id=workspace.id,
    )
    session.add(user)
    await session.flush()

    session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role=(WorkspaceRole.ADMIN if is_first_user else WorkspaceRole.MEMBER).value,
        )
    )
    await session.commit()
    await session.refresh(user)
    await session.refresh(workspace)

    logger.info(
        "Registered user %s (superadmin=%s) in workspace %s",
        user.username,
        is_first_user,
        workspace.slug,
    )
    return user, workspace


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
    full_name: str | None = None,
    role: UserRole = UserRole.USER,
    workspace_id: int | None = None,
    workspace_role: WorkspaceRole = WorkspaceRole.MEMBER,
) -> User:
    """A superadmin creating an account, optionally straight into a workspace,
    which then becomes the account's active workspace."""
    email = email.strip().lower()
    username = username.strip()
    await _check_identity_free(session, username=username, email=email)

    if workspace_id is not None:
        workspace = await session.get(Workspace, workspace_id)
        if workspace is None:
            raise NotFoundError(f"Workspace {workspace_id} not found")

    user = User(
        username=username,
        email=email,
        full_name=full_name,
        password_hash=security.hash_password(password),
        role=role.value,
        default_workspace_id=workspace_id,
    )
    session.add(user)
    await session.flush()
    if workspace_id is not None:
        session.add(
            WorkspaceMember(
                workspace_id=workspace_id, user_id=user.id, role=workspace_role.value
            )
        )
    await session.commit()
    await session.refresh(user)
    logger.info("Created user %s (role=%s)", user.username, user.role)
    return user


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


async def resolve_active_workspace(
    session: AsyncSession, user: User
) -> Workspace | None:
    """The workspace this user is working in, stored server-side per user.

    Like the platform's active workspace: their stored choice while it is
    still valid (active, and they still belong to it -- a superadmin belongs
    everywhere), otherwise the first workspace they belong to. A superadmin
    with no membership at all lands in the first active workspace.
    """
    if user.default_workspace_id is not None:
        workspace = await session.get(Workspace, user.default_workspace_id)
        if workspace is not None and workspace.is_active:
            if user.is_superadmin or await get_membership(
                session, user_id=user.id, workspace_id=workspace.id
            ):
                return workspace

    memberships = await list_memberships(session, user.id)
    if memberships:
        return memberships[0][1]
    if user.is_superadmin:
        return await session.scalar(
            select(Workspace).where(Workspace.is_active.is_(True)).order_by(Workspace.name)
        )
    return None


async def workspace_role_for(
    session: AsyncSession, user: User, workspace: Workspace
) -> WorkspaceRole | None:
    """The user's effective role in one workspace, or None when they have no
    business there. System admins are raised to ADMIN where they belong; a
    superadmin is ADMIN everywhere."""
    if user.is_superadmin:
        return WorkspaceRole.ADMIN
    membership = await get_membership(session, user_id=user.id, workspace_id=workspace.id)
    if membership is None:
        return None
    if user.is_system_admin:
        return WorkspaceRole.ADMIN
    return WorkspaceRole(membership.role)


async def activate_workspace(
    session: AsyncSession, user: User, workspace_id: int
) -> tuple[Workspace, WorkspaceRole]:
    """Make `workspace_id` the user's active workspace (platform's
    POST /workspaces/{id}/activate)."""
    workspace = await session.get(Workspace, workspace_id)
    role = (
        await workspace_role_for(session, user, workspace)
        if workspace is not None and workspace.is_active
        else None
    )
    if role is None:
        # 404, not 403: confirming the workspace exists to an outsider leaks it.
        raise NotFoundError(f"Workspace {workspace_id} not found")
    user.default_workspace_id = workspace.id
    await session.commit()
    return workspace, role


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
    # Without this a password change or reset would sign out every access
    # token while the refresh token beside it quietly minted new ones.
    if await issued_before_cutoff(session, user.id, claims.get("iat")):
        raise AuthError("Session has been invalidated, please log in again")

    await revoke(
        session,
        jti=claims["jti"],
        user_id=user.id,
        expires_at=datetime.fromtimestamp(claims["exp"], tz=utcnow().tzinfo),
        token_type=TokenType.REFRESH.value,
        reason="rotated",
        commit=False,
    )

    # The claim is informational; the active workspace lives on the user row
    # and may have changed (or been revoked) since this token was minted.
    workspace = await resolve_active_workspace(session, user)
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
            # The API's clock, like every token's iat -- not the database's
            # now(), which is also the start of the transaction, not this line.
            revoked_at=utcnow(),
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


async def issued_before_cutoff(
    session: AsyncSession, user_id: int, issued_at: int | float | None
) -> bool:
    """True when a token with this `iat` predates the user's latest cutoff.

    Both sides come from the API's clock with sub-second precision (see
    `security.create_token` and `revoke_all_for_user`), so a login made right
    after a password reset is not mistaken for one made before it.
    """
    cutoff = await latest_cutoff(session, user_id)
    if cutoff is None or issued_at is None:
        return False
    return float(issued_at) < cutoff.timestamp()


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


async def reset_password_with_code(
    session: AsyncSession, *, email: str, code: str, new_password: str
) -> bool:
    """Set a new password with an emailed code, then sign out everywhere.

    False for an unknown or deactivated account and for a wrong, expired or
    burnt code alike: the caller answers all of them the same way.
    """
    user = await get_user_by_email(session, email)
    if user is None or not user.is_active:
        return False
    if not await otp.consume(session, user.id, code):
        return False
    user.password_hash = security.hash_password(new_password)
    await session.commit()  # the new password and the spent code, together
    await revoke_all_for_user(session, user.id, reason="password_reset")
    logger.info("Password reset by emailed code for user %s", user.id)
    return True


async def require_user(session: AsyncSession, user_id: int) -> User:
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    return user
