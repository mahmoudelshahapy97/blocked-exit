"""Camera location hierarchy: area, building, floor_level, zone.

The platform describes every camera as location > area > building >
floor_level > zone, and filters events and analytics by any of them. location
already exists; this adds the other four.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("camera", sa.Column("area", sa.String(length=100), nullable=True))
    op.add_column("camera", sa.Column("building", sa.String(length=100), nullable=True))
    op.add_column("camera", sa.Column("floor_level", sa.String(length=20), nullable=True))
    op.add_column("camera", sa.Column("zone", sa.String(length=100), nullable=True))
    op.create_index(
        "ix_camera_workspace_hierarchy",
        "camera",
        ["workspace_id", "location", "area", "building", "floor_level", "zone"],
    )


def downgrade() -> None:
    op.drop_index("ix_camera_workspace_hierarchy", table_name="camera")
    op.drop_column("camera", "zone")
    op.drop_column("camera", "floor_level")
    op.drop_column("camera", "building")
    op.drop_column("camera", "area")
