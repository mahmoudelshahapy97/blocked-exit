"""Authentication request/response schemas."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.enums import UserRole, WorkspaceRole

# Letters, digits, underscore, hyphen, dot. No spaces and no "@": a username
# that could be mistaken for an email would make the login lookup ambiguous.
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

PASSWORD_MIN_LENGTH = 10


def _validate_password(value: str) -> str:
    """Length plus variety, checked here so every entry point agrees.

    Deliberately not a dictionary or breach check — the reference service calls
    out to HaveIBeenPwned for that, which turns signup into a network round trip
    that fails closed when the site is down.
    """
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(value) > 128:
        # argon2 is happy with long input; this only stops someone posting a
        # megabyte and making us hash it.
        raise ValueError("password must be at most 128 characters")
    classes = sum(
        bool(pattern.search(value))
        for pattern in (
            re.compile(r"[a-z]"),
            re.compile(r"[A-Z]"),
            re.compile(r"[0-9]"),
            re.compile(r"[^A-Za-z0-9]"),
        )
    )
    if classes < 3:
        raise ValueError(
            "password must contain at least three of: lowercase, uppercase, digit, symbol"
        )
    return value


# --- tokens ----------------------------------------------------------------
class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime = Field(description="When the access token expires (UTC)")
    expires_in: int = Field(description="Access token lifetime in seconds")


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    # Optional: logging out without it revokes only the access token, leaving a
    # refresh token that could mint a new one. The client should always send it.
    refresh_token: str | None = None


class StreamTicket(BaseModel):
    """Short-lived, single-camera credential for `<img src>` live view."""

    ticket: str
    camera_id: int
    expires_at: datetime
    expires_in: int


# --- users -----------------------------------------------------------------
class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workspace_id: int
    workspace_name: str
    workspace_slug: str
    role: WorkspaceRole


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    full_name: str | None = None
    role: UserRole
    is_active: bool
    default_workspace_id: int | None = None
    last_login_at: datetime | None = None
    created_at: datetime


class UserProfile(UserRead):
    """`/auth/me` — the user plus everywhere they can go."""

    memberships: list[MembershipRead] = Field(default_factory=list)
    active_workspace_id: int | None = Field(
        None, description="The workspace every request currently acts in"
    )


class BootstrapStatus(BaseModel):
    """What the login page should offer before anyone is signed in."""

    signup_open: bool = Field(
        description="POST /auth/signup will accept a new account right now"
    )
    needs_bootstrap: bool = Field(
        description="No account exists yet; the first signup becomes superadmin"
    )


class _NewAccount(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str
    full_name: str | None = Field(None, max_length=160)

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        if not USERNAME_RE.match(value):
            raise ValueError(
                "username may contain only letters, digits, dot, underscore and hyphen"
            )
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password(value)


class SignupRequest(_NewAccount):
    workspace_name: str | None = Field(
        None,
        max_length=120,
        description="Bootstrap only: name for the first workspace. "
        'Defaults to "Default Workspace".',
    )


class UserCreate(_NewAccount):
    """A superadmin creating an account (the platform has no self-service
    signup past the first account)."""

    role: UserRole = UserRole.USER
    workspace_id: int | None = Field(
        None, description="Add the account to this workspace and make it active there"
    )
    workspace_role: WorkspaceRole = WorkspaceRole.MEMBER


class LoginRequest(BaseModel):
    # One field for both so an operator does not have to remember which they
    # signed up with; the service tries username first, then email.
    username: str = Field(min_length=1, max_length=255, description="Username or email")
    password: str = Field(min_length=1, max_length=128)
    workspace_id: int | None = Field(
        None, description="Workspace to open. Defaults to the user's default."
    )


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, max_length=160)
    email: EmailStr | None = None
    default_workspace_id: int | None = None


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password(value)


class UserAdminUpdate(BaseModel):
    """Superadmin edits to somebody else's account."""

    full_name: str | None = Field(None, max_length=160)
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(
        None, description="Set a new password; signs the user out everywhere"
    )

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str | None) -> str | None:
        return None if value is None else _validate_password(value)
