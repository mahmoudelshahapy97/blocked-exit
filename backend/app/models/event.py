"""blockage_event: one confirmed obstruction episode. ended_at IS NULL means
the blockage is still happening."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BlockageEvent(Base):
    __tablename__ = "blockage_event"
    __table_args__ = (
        Index("ix_blockage_event_camera_started", "camera_id", "started_at"),
        Index("ix_blockage_event_workspace_started", "workspace_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey(
            "workspace.id", name="fk_blockage_event_workspace_id", ondelete="CASCADE"
        ),
        index=True,
    )
    camera_id: Mapped[int] = mapped_column(
        ForeignKey("camera.id", ondelete="CASCADE"), index=True
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[float | None] = mapped_column(Float)

    state: Mapped[str] = mapped_column(String(16))
    peak_state: Mapped[str] = mapped_column(String(16))
    strategy: Mapped[str] = mapped_column(String(32))

    min_accessibility_pct: Mapped[float] = mapped_column(Float)
    last_accessibility_pct: Mapped[float] = mapped_column(Float)
    peak_risk_score: Mapped[float] = mapped_column(Float)

    blocking_objects: Mapped[list | None] = mapped_column(JSONB)
    snapshot_path: Mapped[str | None] = mapped_column(String(512))
