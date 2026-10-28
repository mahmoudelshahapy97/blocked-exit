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


class EventStatus(StrEnum):
    """Where an operator has got to with a blockage event (the platform's
    detected -> acknowledged -> resolved). Independent of whether the blockage
    itself is still ongoing: that is `ended_at`."""

    DETECTED = "detected"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


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

    Mirrors the platform's users.role: SUPERADMIN runs the deployment (creates
    users and workspaces, manages every roster) and may open any workspace.
    ADMIN acts as a workspace admin inside the workspaces it belongs to, but
    cannot manage tenancy. USER gets whatever its membership role says.
    """

    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    USER = "user"


class WorkspaceRole(StrEnum):
    """What a member may do *inside* one workspace.

    Same three roles as the platform's workspace_members.role. Ordered: ADMIN
    can do everything a MEMBER can, and so on down. Compare with `rank` rather
    than by name, so a new tier in the middle does not mean revisiting every
    guard.
    """

    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"

    @property
    def rank(self) -> int:
        return _WORKSPACE_ROLE_RANK[self]

    def can_act_as(self, required: WorkspaceRole) -> bool:
        return self.rank >= required.rank


_WORKSPACE_ROLE_RANK = {
    WorkspaceRole.VIEWER: 0,
    WorkspaceRole.MEMBER: 1,
    WorkspaceRole.ADMIN: 2,
}


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"
    # Single-camera, 60-second credential for <img src> MJPEG/snapshot URLs,
    # which cannot carry an Authorization header. See app.core.security and
    # POST /monitoring/{id}/stream-ticket.
    STREAM = "stream"
