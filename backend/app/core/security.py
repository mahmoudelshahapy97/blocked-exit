"""Password hashing and JWT encode/decode.

Deliberately free of database and FastAPI imports: everything here is pure
computation over strings, so it is testable without a session, a request or a
running event loop. Anything that needs to *look something up* (is this token
revoked? is this user still active?) lives in `app.services.auth`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings
from app.core.enums import TokenType
from app.utils.timing import utcnow

# argon2-cffi directly rather than through passlib: passlib 1.7.x reaches for
# the stdlib `crypt` module, which is deprecated on 3.12 and *removed* in 3.13.
# This is the same primitive passlib would have delegated to anyway.
_hasher = PasswordHasher()


class TokenError(Exception):
    """A token could not be decoded, or decoded into something unusable."""


# --- passwords -------------------------------------------------------------
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-ish verify that never raises on a bad hash.

    A malformed or empty stored hash means the account cannot be logged into,
    not that the request 500s — an attacker should not be able to tell a
    corrupt row from a wrong password.
    """
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash predates the current argon2 cost parameters.

    Callers re-hash on the next successful login, so tightening the parameters
    migrates the user base without a password reset.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# --- tokens ----------------------------------------------------------------
STREAM_TICKET_LIFETIME_S = 60


def _lifetime(token_type: TokenType) -> timedelta:
    if token_type is TokenType.ACCESS:
        return timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    if token_type is TokenType.STREAM:
        return timedelta(seconds=STREAM_TICKET_LIFETIME_S)
    return timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


def create_token(
    *,
    user_id: int,
    workspace_id: int | None,
    token_type: TokenType,
    role: str | None = None,
) -> tuple[str, str, datetime]:
    """Return `(encoded_jwt, jti, expires_at)`.

    The `jti` comes back to the caller because revocation is keyed on it: the
    raw token is long, unbounded and awkward to index, while a jti is a fixed
    36 characters. `role` is carried for display and cheap client-side gating
    only — every guard re-reads the role from the database, because a token
    minted before a demotion would otherwise outlive it.
    """
    issued_at = utcnow()
    expires_at = issued_at + _lifetime(token_type)
    jti = str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "workspace_id": workspace_id,
        "token_type": token_type.value,
        "role": role,
        "jti": jti,
        # Fractional seconds (a NumericDate may be non-integer): the cutoff a
        # password change writes is compared against this, and whole seconds
        # cannot order a reset and a login made within the same second.
        "iat": issued_at.timestamp(),
        "exp": expires_at,
    }
    encoded = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    # PyJWT < 2 returned bytes; the pin returns str. Normalise so callers never
    # have to care which is installed.
    if isinstance(encoded, bytes):
        encoded = encoded.decode("utf-8")
    return encoded, jti, expires_at


def create_stream_ticket(
    *, user_id: int, workspace_id: int, camera_id: int
) -> tuple[str, datetime]:
    """A 60-second, single-camera credential for `<img src>` MJPEG/snapshot URLs.

    `<img>` cannot send an Authorization header, and a full-lifetime access
    token in a query string would sit in nginx access logs, browser history and
    any `Referer` header sent onward. Scoping the ticket to one camera and one
    minute means a leaked one costs that much, not the account.
    """
    issued_at = utcnow()
    expires_at = issued_at + timedelta(seconds=STREAM_TICKET_LIFETIME_S)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "workspace_id": workspace_id,
        "camera_id": camera_id,
        "token_type": TokenType.STREAM.value,
        "jti": str(uuid.uuid4()),
        "iat": issued_at,
        "exp": expires_at,
    }
    encoded = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    if isinstance(encoded, bytes):
        encoded = encoded.decode("utf-8")
    return encoded, expires_at


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict:
    """Verify signature and expiry, and return the claims.

    Raises `TokenError` for every failure mode, so callers map one exception to
    one 401 instead of enumerating PyJWT's hierarchy at each call site.
    """
    if not token or token.count(".") != 2:
        raise TokenError("Malformed token")

    try:
        claims = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid token") from exc

    actual_type = claims.get("token_type")
    if expected_type is not None and actual_type != expected_type.value:
        raise TokenError(
            f"Expected a {expected_type.value} token, got {actual_type or 'none'}"
        )
    return claims
