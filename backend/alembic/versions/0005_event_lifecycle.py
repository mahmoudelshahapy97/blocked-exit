"""Event lifecycle and detection confidence on blockage_event.

- status detected -> acknowledged -> resolved, with who and when for each
  step and an optional resolution note: the platform's event workflow, and
  what the response-time analytics measure.
- risk_level: the band of peak_risk_score (LOW..CRITICAL), stored so lists
  can filter and sort by it without re-deriving the bands in SQL.
- confidence / avg_confidence: peak and mean of the per-frame top detection
  confidence of the blocking objects, for the confidence-audit analytics.

Existing events are backfilled: risk_level from peak_risk_score with the
bands in app/services/risk.py, and every event that had already closed is
marked resolved at its end time with an explanatory note, so upgrading does
not flood the console with history nobody can acknowledge any more.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL_NOTE = "Closed before acknowledgement tracking existed"


def upgrade() -> None:
    op.add_column(
        "blockage_event",
        sa.Column(
            "status", sa.String(length=16), server_default="detected", nullable=False
        ),
    )
    op.add_column("blockage_event", sa.Column("risk_level", sa.String(length=16)))
    op.add_column(
        "blockage_event", sa.Column("acknowledged_at", sa.DateTime(timezone=True))
    )
    op.add_column("blockage_event", sa.Column("acknowledged_by_id", sa.Integer()))
    op.add_column("blockage_event", sa.Column("resolved_at", sa.DateTime(timezone=True)))
    op.add_column("blockage_event", sa.Column("resolved_by_id", sa.Integer()))
    op.add_column("blockage_event", sa.Column("resolution_note", sa.String(length=1000)))
    op.add_column("blockage_event", sa.Column("confidence", sa.Numeric(5, 4)))
    op.add_column("blockage_event", sa.Column("avg_confidence", sa.Numeric(5, 4)))

    op.create_foreign_key(
        "fk_blockage_event_acknowledged_by_id",
        "blockage_event",
        "app_user",
        ["acknowledged_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_blockage_event_resolved_by_id",
        "blockage_event",
        "app_user",
        ["resolved_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_blockage_event_status",
        "blockage_event",
        "status IN ('detected', 'acknowledged', 'resolved')",
    )
    op.create_index(
        "ix_blockage_event_workspace_status_started",
        "blockage_event",
        ["workspace_id", "status", "started_at"],
    )

    op.execute(
        """
        UPDATE blockage_event SET risk_level = CASE
            WHEN peak_state = 'FULL' AND peak_risk_score >= 60 THEN 'CRITICAL'
            WHEN peak_risk_score >= 80 THEN 'CRITICAL'
            WHEN peak_risk_score >= 55 THEN 'HIGH'
            ELSE 'MEDIUM'
        END
        """
    )
    op.execute(
        sa.text(
            "UPDATE blockage_event SET status = 'resolved', resolved_at = ended_at, "
            "resolution_note = :note WHERE ended_at IS NOT NULL"
        ).bindparams(note=BACKFILL_NOTE)
    )


def downgrade() -> None:
    op.drop_index("ix_blockage_event_workspace_status_started", table_name="blockage_event")
    op.drop_constraint("ck_blockage_event_status", "blockage_event", type_="check")
    op.drop_constraint(
        "fk_blockage_event_resolved_by_id", "blockage_event", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_blockage_event_acknowledged_by_id", "blockage_event", type_="foreignkey"
    )
    for column in (
        "avg_confidence",
        "confidence",
        "resolution_note",
        "resolved_by_id",
        "resolved_at",
        "acknowledged_by_id",
        "acknowledged_at",
        "risk_level",
        "status",
    ):
        op.drop_column("blockage_event", column)
