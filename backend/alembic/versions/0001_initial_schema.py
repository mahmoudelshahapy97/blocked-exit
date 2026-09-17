"""Initial schema: camera, blockage_event, alert

Revision ID: 0001
Revises:
Create Date: 2026-08-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "camera",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("rtsp_url", sa.String(length=512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("door_polygon", postgresql.JSONB(), nullable=True),
        sa.Column("reference_bbox", postgresql.JSONB(), nullable=True),
        sa.Column("reference_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clear_min_pct", sa.Float(), nullable=True),
        sa.Column("full_max_pct", sa.Float(), nullable=True),
        sa.Column("confirm_seconds", sa.Float(), nullable=True),
        sa.Column("clear_seconds", sa.Float(), nullable=True),
        sa.Column("process_fps", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_camera_name", "camera", ["name"], unique=True)
    op.create_index("ix_camera_enabled", "camera", ["enabled"])

    op.create_table(
        "blockage_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("peak_state", sa.String(length=16), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("min_accessibility_pct", sa.Float(), nullable=False),
        sa.Column("last_accessibility_pct", sa.Float(), nullable=False),
        sa.Column("peak_risk_score", sa.Float(), nullable=False),
        sa.Column("blocking_objects", postgresql.JSONB(), nullable=True),
        sa.Column("snapshot_path", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(["camera_id"], ["camera.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_blockage_event_camera_id", "blockage_event", ["camera_id"])
    op.create_index("ix_blockage_event_started_at", "blockage_event", ["started_at"])
    op.create_index(
        "ix_blockage_event_camera_started",
        "blockage_event",
        ["camera_id", "started_at"],
    )

    op.create_table(
        "alert",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["camera_id"], ["camera.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["event_id"], ["blockage_event.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_camera_id", "alert", ["camera_id"])
    op.create_index("ix_alert_event_id", "alert", ["event_id"])
    op.create_index("ix_alert_status", "alert", ["status"])
    op.create_index("ix_alert_created_at", "alert", ["created_at"])
    op.create_index("ix_alert_camera_created", "alert", ["camera_id", "created_at"])


def downgrade() -> None:
    op.drop_table("alert")
    op.drop_table("blockage_event")
    op.drop_table("camera")
