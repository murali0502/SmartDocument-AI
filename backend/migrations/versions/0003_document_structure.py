"""Persist stable structural elements and exact-span chunks."""

import sqlalchemy as sa
from alembic import op

revision = "0003_document_structure"
down_revision = "0002_document_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "structure_runs",
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("ingestion_results.job_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("element_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.CheckConstraint("status IN ('ready', 'failed')", name="ck_structure_status"),
    )
    op.create_table(
        "structure_elements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("structure_runs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id", sa.String(36), sa.ForeignKey("structure_elements.id", ondelete="CASCADE")
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("job_id", "ordinal", name="uq_element_job_ordinal"),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("structure_runs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "element_id",
            sa.String(36),
            sa.ForeignKey("structure_elements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("job_id", "ordinal", name="uq_chunk_job_ordinal"),
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("structure_elements")
    op.drop_table("structure_runs")
