"""ORM models. Importing this package registers every table on Base.metadata,
which Alembic's env.py and init_models() rely on."""

from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.camera import Camera
from app.models.event import BlockageEvent
from app.models.notification import Notification
from app.models.user import (
    PasswordOtp,
    RevokedToken,
    User,
    Workspace,
    WorkspaceMember,
)

__all__ = [
    "Alert",
    "AuditLog",
    "BlockageEvent",
    "Camera",
    "Notification",
    "PasswordOtp",
    "RevokedToken",
    "User",
    "Workspace",
    "WorkspaceMember",
]
