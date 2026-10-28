"""Platform roles: superadmin, and admin/member/viewer workspace roles.

Brings tenancy in line with the InsightEye platform:

- app_user.role gains 'superadmin'. Before this migration 'admin' was the
  only role that could manage the deployment (the bootstrap account), so every
  existing admin becomes a superadmin -- nobody loses access.
- workspace_member.role collapses from owner/admin/operator/viewer to the
  platform's admin/member/viewer: owner and admin both become admin, operator
  becomes member.
- app_user.default_workspace_id is now the user's *active* workspace, switched
  server-side; no column change is needed for that.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE app_user SET role = 'superadmin' WHERE role = 'admin'")
    op.execute("UPDATE workspace_member SET role = 'admin' WHERE role = 'owner'")
    op.execute("UPDATE workspace_member SET role = 'member' WHERE role = 'operator'")

    op.create_check_constraint(
        "ck_app_user_role", "app_user", "role IN ('superadmin', 'admin', 'user')"
    )
    op.create_check_constraint(
        "ck_workspace_member_role",
        "workspace_member",
        "role IN ('admin', 'member', 'viewer')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_workspace_member_role", "workspace_member", type_="check")
    op.drop_constraint("ck_app_user_role", "app_user", type_="check")
    # Lossy: admins and owners cannot be told apart again, so every workspace
    # admin comes back as an owner.
    op.execute("UPDATE workspace_member SET role = 'operator' WHERE role = 'member'")
    op.execute("UPDATE workspace_member SET role = 'owner' WHERE role = 'admin'")
    op.execute("UPDATE app_user SET role = 'admin' WHERE role = 'superadmin'")
