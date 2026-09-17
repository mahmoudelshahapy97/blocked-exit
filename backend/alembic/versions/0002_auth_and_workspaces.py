"""Auth and workspace multi-tenancy: workspace, app_user, workspace_member,
revoked_token; workspace_id added to camera, blockage_event, alert.

Every row that predates this migration is adopted into one "Default"
workspace -- there is no way to know which tenant a pre-tenancy camera
"belongs" to, so this is the only sane backfill. A fresh deployment (no
existing rows) never sees that workspace; it only appears when upgrading a
database that already had cameras in it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-27

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_WORKSPACE_SLUG = "default"
DEFAULT_WORKSPACE_NAME = "Default"


def upgrade() -> None:
    # --- 1. new tables -----------------------------------------------------
    op.create_table(
        "workspace",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("camera_quota", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_name", "workspace", ["name"], unique=True)
    op.create_index("ix_workspace_slug", "workspace", ["slug"], unique=True)

    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("default_workspace_id", sa.Integer(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["default_workspace_id"], ["workspace.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_user_username", "app_user", ["username"], unique=True)
    op.create_index("ix_app_user_email", "app_user", ["email"], unique=True)
    op.create_index("ix_app_user_role", "app_user", ["role"])
    op.create_index("ix_app_user_is_active", "app_user", ["is_active"])
    op.create_index("ix_app_user_default_workspace_id", "app_user", ["default_workspace_id"])

    op.create_table(
        "workspace_member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )
    op.create_index("ix_workspace_member_workspace_id", "workspace_member", ["workspace_id"])
    op.create_index("ix_workspace_member_user_id", "workspace_member", ["user_id"])
    op.create_index(
        "ix_workspace_member_user_workspace", "workspace_member", ["user_id", "workspace_id"]
    )

    op.create_table(
        "revoked_token",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("token_type", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=120), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_revoked_token_jti", "revoked_token", ["jti"], unique=True)
    op.create_index("ix_revoked_token_user_id", "revoked_token", ["user_id"])
    op.create_index("ix_revoked_token_expires_at", "revoked_token", ["expires_at"])

    # --- 2. default workspace, for rows that predate tenancy ----------------
    workspace_table = sa.table(
        "workspace",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("camera_quota", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    conn = op.get_bind()
    conn.execute(
        workspace_table.insert().values(
            name=DEFAULT_WORKSPACE_NAME,
            slug=DEFAULT_WORKSPACE_SLUG,
            camera_quota=1000,
            is_active=True,
        )
    )
    default_workspace_id = conn.execute(
        sa.select(workspace_table.c.id).where(workspace_table.c.slug == DEFAULT_WORKSPACE_SLUG)
    ).scalar_one()

    # --- 3. workspace_id on domain tables, nullable first --------------------
    op.add_column("camera", sa.Column("workspace_id", sa.Integer(), nullable=True))
    op.add_column("blockage_event", sa.Column("workspace_id", sa.Integer(), nullable=True))
    op.add_column("alert", sa.Column("workspace_id", sa.Integer(), nullable=True))

    # --- 4. backfill ----------------------------------------------------------
    camera_table = sa.table("camera", sa.column("workspace_id", sa.Integer))
    event_table = sa.table("blockage_event", sa.column("workspace_id", sa.Integer))
    alert_table = sa.table("alert", sa.column("workspace_id", sa.Integer))
    conn.execute(camera_table.update().values(workspace_id=default_workspace_id))
    conn.execute(event_table.update().values(workspace_id=default_workspace_id))
    conn.execute(alert_table.update().values(workspace_id=default_workspace_id))

    # --- 5. NOT NULL, FKs, indexes ---------------------------------------------
    op.alter_column("camera", "workspace_id", nullable=False)
    op.alter_column("blockage_event", "workspace_id", nullable=False)
    op.alter_column("alert", "workspace_id", nullable=False)

    op.create_foreign_key(
        "fk_camera_workspace_id", "camera", "workspace", ["workspace_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_blockage_event_workspace_id",
        "blockage_event",
        "workspace",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_alert_workspace_id", "alert", "workspace", ["workspace_id"], ["id"], ondelete="CASCADE"
    )

    op.create_index("ix_camera_workspace_id", "camera", ["workspace_id"])
    op.create_index("ix_camera_workspace_enabled", "camera", ["workspace_id", "enabled"])
    op.create_index("ix_blockage_event_workspace_id", "blockage_event", ["workspace_id"])
    op.create_index(
        "ix_blockage_event_workspace_started", "blockage_event", ["workspace_id", "started_at"]
    )
    op.create_index("ix_alert_workspace_id", "alert", ["workspace_id"])
    op.create_index("ix_alert_workspace_created", "alert", ["workspace_id", "created_at"])

    # --- 6. camera.name: global unique -> (workspace_id, name) unique ----------
    op.drop_index("ix_camera_name", table_name="camera")
    op.create_index("ix_camera_name", "camera", ["name"])
    op.create_unique_constraint(
        "uq_camera_workspace_name", "camera", ["workspace_id", "name"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_camera_workspace_name", "camera", type_="unique")
    op.drop_index("ix_camera_name", table_name="camera")
    op.create_index("ix_camera_name", "camera", ["name"], unique=True)

    op.drop_index("ix_alert_workspace_created", table_name="alert")
    op.drop_index("ix_alert_workspace_id", table_name="alert")
    op.drop_index("ix_blockage_event_workspace_started", table_name="blockage_event")
    op.drop_index("ix_blockage_event_workspace_id", table_name="blockage_event")
    op.drop_index("ix_camera_workspace_enabled", table_name="camera")
    op.drop_index("ix_camera_workspace_id", table_name="camera")

    op.drop_constraint("fk_alert_workspace_id", "alert", type_="foreignkey")
    op.drop_constraint(
        "fk_blockage_event_workspace_id", "blockage_event", type_="foreignkey"
    )
    op.drop_constraint("fk_camera_workspace_id", "camera", type_="foreignkey")

    op.drop_column("alert", "workspace_id")
    op.drop_column("blockage_event", "workspace_id")
    op.drop_column("camera", "workspace_id")

    op.drop_table("revoked_token")
    op.drop_table("workspace_member")
    op.drop_table("app_user")
    op.drop_table("workspace")
