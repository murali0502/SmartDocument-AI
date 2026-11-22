"""Add content-addressed documents, processing jobs and extraction results."""

import sqlalchemy as sa
from alembic import op

revision = "0002_document_ingestion"
down_revision = "0001_workspace_foundation"
branch_labels = None
depends_on = None

LOCAL_WORKSPACE_ID = "00000000-0000-4000-8000-000000000001"


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "sha256", name="uq_document_workspace_hash"),
    )
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("error_code", sa.String(40)),
        sa.Column("error_message", sa.String(255)),
        sa.Column("pipeline_version", sa.String(40), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_job_status"
        ),
    )
    op.create_index("ix_ingestion_claim", "ingestion_jobs", ["status", "created_at"])
    op.create_table(
        "ingestion_results",
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("ingestion_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("extraction", sa.JSON(), nullable=False),
    )
    workspaces = sa.table("workspaces", sa.column("id", sa.String), sa.column("name", sa.String))
    op.bulk_insert(workspaces, [{"id": LOCAL_WORKSPACE_ID, "name": "Local workspace"}])


def downgrade() -> None:
    op.drop_table("ingestion_results")
    op.drop_table("ingestion_jobs")
    op.drop_table("documents")
    workspaces = sa.table("workspaces", sa.column("id", sa.String))
    op.execute(workspaces.delete().where(workspaces.c.id == LOCAL_WORKSPACE_ID))
