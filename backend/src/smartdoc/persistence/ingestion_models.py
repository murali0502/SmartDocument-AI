from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from smartdoc.persistence.models import Base

LOCAL_WORKSPACE_ID = "00000000-0000-4000-8000-000000000001"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sha256", name="uq_document_workspace_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(8))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]
    created_at: Mapped[datetime]


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_job_status"
        ),
        Index("ix_ingestion_claim", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(String(12))
    attempts: Mapped[int]
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(255))
    pipeline_version: Mapped[str] = mapped_column(String(40))


class IngestionResult(Base):
    __tablename__ = "ingestion_results"

    job_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    extraction: Mapped[dict] = mapped_column(JSON)
