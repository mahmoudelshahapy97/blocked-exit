"""ORM models. Importing this package registers every table on Base.metadata,
which Alembic's env.py and init_models() rely on."""

from app.models.alert import Alert
from app.models.camera import Camera
from app.models.event import BlockageEvent
from app.models.user import RevokedToken, User, Workspace, WorkspaceMember

__all__ = [
    "Alert",
    "BlockageEvent",
    "Camera",
    "RevokedToken",
    "User",
    "Workspace",
    "WorkspaceMember",
]
