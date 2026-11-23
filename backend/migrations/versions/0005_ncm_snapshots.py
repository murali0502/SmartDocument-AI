"""Persist versioned NCM concepts, assertions, and local review history."""

import sqlalchemy as sa
from alembic import op

revision = "0005_ncm_snapshots"
down_revision = "0004_linguistic_annotations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ncm_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("profile_key", sa.String(64), nullable=False),
        sa.Column("configuration", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column(
            "parent_id", sa.String(36), sa.ForeignKey("ncm_snapshots.id", ondelete="SET NULL")
        ),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("error", sa.String(40)),
        sa.Column("concept_count", sa.Integer(), nullable=False),
        sa.Column("assertion_count", sa.Integer(), nullable=False),
        sa.Column("audit", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id", "profile_key"],
            ["nlp_runs.job_id", "nlp_runs.profile_key"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "job_id", "profile_key", "configuration", "revision", name="uq_ncm_revision"
        ),
        sa.CheckConstraint("status IN ('ready', 'failed')", name="ck_ncm_snapshot_status"),
    )


def downgrade() -> None:
    op.drop_table("ncm_snapshots")
