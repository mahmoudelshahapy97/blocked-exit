"""camera: one monitored emergency exit, fed by one stream."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Camera(Base):
    __tablename__ = "camera"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_camera_workspace_name"),
        Index("ix_camera_workspace_enabled", "workspace_id", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspace.id", name="fk_camera_workspace_id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    location: Mapped[str | None] = mapped_column(String(255))
    rtsp_url: Mapped[str] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    strategy: Mapped[str] = mapped_column(String(32), default="zone_based")

    # Normalized to [0, 1] so the region survives a change of resolution.
    door_polygon: Mapped[list | None] = mapped_column(JSONB)
    reference_bbox: Mapped[list | None] = mapped_column(JSONB)
    reference_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # Per-camera overrides; NULL inherits the global setting.
    clear_min_pct: Mapped[float | None] = mapped_column(Float)
    full_max_pct: Mapped[float | None] = mapped_column(Float)
    confirm_seconds: Mapped[float | None] = mapped_column(Float)
    clear_seconds: Mapped[float | None] = mapped_column(Float)
    process_fps: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
