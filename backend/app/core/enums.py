"""Enumerations shared by ORM models, schemas and services."""

from __future__ import annotations

from enum import StrEnum


class BlockageState(StrEnum):
    """How accessible the exit currently is."""

    CLEAR = "CLEAR"
    PARTIAL = "PARTIAL"
    FULL = "FULL"
    UNKNOWN = "UNKNOWN"

    @property
    def severity(self) -> int:
        return _SEVERITY[self]

    def is_blocked(self) -> bool:
        return self in (BlockageState.PARTIAL, BlockageState.FULL)


_SEVERITY = {
    BlockageState.UNKNOWN: 0,
    BlockageState.CLEAR: 1,
    BlockageState.PARTIAL: 2,
    BlockageState.FULL: 3,
}


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class StrategyName(StrEnum):
    ZONE_BASED = "zone_based"
    DOOR_CENTRIC = "door_centric"


class WorkerState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class AlertChannel(StrEnum):
    WEBHOOK = "webhook"
    EMAIL = "email"


class AlertStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class UserRole(StrEnum):
    """Platform-wide role, independent of any workspace membership.

    ADMIN is the only role that can reach across workspace boundaries — see
    `app.api.deps.resolve_workspace`. Everyone else is confined to the
    workspaces they are a member of, whatever this says.
    """

    ADMIN = "admin"
    USER = "user"


class WorkspaceRole(StrEnum):
    """What a member may do *inside* one workspace.

    Ordered: OWNER can do everything an ADMIN can, and so on down. Compare with
    `rank` rather than by name, so a new tier in the middle does not mean
    revisiting every guard.
    """

    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"

    @property
    def rank(self) -> int:
        return _WORKSPACE_ROLE_RANK[self]

    def can_act_as(self, required: WorkspaceRole) -> bool:
        return self.rank >= required.rank


_WORKSPACE_ROLE_RANK = {
    WorkspaceRole.VIEWER: 0,
    WorkspaceRole.OPERATOR: 1,
    WorkspaceRole.ADMIN: 2,
    WorkspaceRole.OWNER: 3,
}


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"
    # Single-camera, 60-second credential for <img src> MJPEG/snapshot URLs,
    # which cannot carry an Authorization header. See app.core.security and
    # POST /monitoring/{id}/stream-ticket.
    STREAM = "stream"
