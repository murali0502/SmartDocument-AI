"""Store versioned, source-anchored NLP annotations."""

import sqlalchemy as sa
from alembic import op

revision = "0004_linguistic_annotations"
down_revision = "0003_document_structure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nlp_runs",
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("structure_runs.job_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("profile_key", sa.String(64), primary_key=True),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("error_code", sa.String(40)),
        sa.CheckConstraint("status IN ('pending', 'ready', 'failed')", name="ck_nlp_status"),
    )
    op.create_table(
        "chunk_annotations",
        sa.Column(
            "chunk_id",
            sa.String(36),
            sa.ForeignKey("document_chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("profile_key", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id", "profile_key"],
            ["nlp_runs.job_id", "nlp_runs.profile_key"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("job_id", "profile_key", "ordinal", name="uq_nlp_chunk_ordinal"),
    )


def downgrade() -> None:
    op.drop_table("chunk_annotations")
    op.drop_table("nlp_runs")
