"""notification: the in-app inbox (bell, Notifications page, live socket).

One row per account per notification, so read marks are per person. A
workspace's notification goes to its members and every superadmin.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Notification(Base):
    __tablename__ = "notification"
    __table_args__ = (
        Index("ix_notification_user_created", "user_id", "created_at"),
        Index(
            "ix_notification_unread", "user_id", postgresql_where=text("read_at IS NULL")
        ),
        # One thing (an event, a test) never notifies the same account twice.
        Index(
            "uq_notification_ref",
            "user_id",
            "kind",
            "ref_id",
            unique=True,
            postgresql_where=text("ref_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", name="fk_notification_user_id", ondelete="CASCADE")
    )
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "workspace.id", name="fk_notification_workspace_id", ondelete="CASCADE"
        )
    )
    kind: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16), default="info")
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(200))
    camera_id: Mapped[int | None] = mapped_column(
        ForeignKey("camera.id", name="fk_notification_camera_id", ondelete="SET NULL")
    )
    camera_name: Mapped[str | None] = mapped_column(String(120))
    ref_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
