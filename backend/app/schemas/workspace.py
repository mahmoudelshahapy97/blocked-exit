"""Workspace and membership schemas."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.enums import WorkspaceRole

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slugify(value: str) -> str:
    """Best-effort slug. Uniqueness is the service's problem, not this one's."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:64] or "workspace"


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: str | None = None
    camera_quota: int
    is_active: bool
    created_at: datetime


class WorkspaceWithRole(WorkspaceRead):
    """A workspace as seen by one user — includes what they may do in it."""

    role: WorkspaceRole
    camera_count: int = 0


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(None, max_length=64)
    description: str | None = Field(None, max_length=500)
    camera_quota: int = Field(25, ge=1, le=10_000)

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not SLUG_RE.match(value):
            raise ValueError(
                "slug must be lowercase alphanumeric words separated by hyphens"
            )
        return value


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    # Quota and active flag are platform-admin only; the route enforces that,
    # because a workspace owner raising their own quota defeats the point.
    camera_quota: int | None = Field(None, ge=1, le=10_000)
    is_active: bool | None = None


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    username: str
    email: str
    full_name: str | None = None
    role: WorkspaceRole
    is_active: bool
    created_at: datetime


class MemberAdd(BaseModel):
    """Add an existing account to this workspace.

    By email or username — there is no invitation email in this service, so the
    person must already have signed up.
    """

    email: EmailStr | None = None
    username: str | None = None
    role: WorkspaceRole = WorkspaceRole.VIEWER


class MemberUpdate(BaseModel):
    role: WorkspaceRole
