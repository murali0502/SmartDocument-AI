from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from smartdoc.persistence.models import Base


class StructureRun(Base):
    __tablename__ = "structure_runs"
    __table_args__ = (CheckConstraint("status IN ('ready', 'failed')", name="ck_structure_status"),)

    job_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_results.job_id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(8))
    completed_at: Mapped[datetime]
    element_count: Mapped[int]
    chunk_count: Mapped[int]
    error_code: Mapped[str | None] = mapped_column(String(40))


class StructureElement(Base):
    __tablename__ = "structure_elements"
    __table_args__ = (UniqueConstraint("job_id", "ordinal", name="uq_element_job_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("structure_runs.job_id", ondelete="CASCADE"))
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("structure_elements.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int]
    payload: Mapped[dict] = mapped_column(JSON)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("job_id", "ordinal", name="uq_chunk_job_ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("structure_runs.job_id", ondelete="CASCADE"))
    element_id: Mapped[str] = mapped_column(ForeignKey("structure_elements.id", ondelete="CASCADE"))
    ordinal: Mapped[int]
    payload: Mapped[dict] = mapped_column(JSON)
