"""alert: one delivery attempt, on one channel, for one event (or a test)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Alert(Base):
    __tablename__ = "alert"
    __table_args__ = (
        Index("ix_alert_camera_created", "camera_id", "created_at"),
        Index("ix_alert_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspace.id", name="fk_alert_workspace_id", ondelete="CASCADE"),
        index=True,
    )
    camera_id: Mapped[int] = mapped_column(
        ForeignKey("camera.id", ondelete="CASCADE"), index=True
    )
    # NULL for a test alert, which has no event behind it.
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("blockage_event.id", ondelete="CASCADE"), index=True
    )

    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(120))
