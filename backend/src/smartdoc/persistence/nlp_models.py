from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from smartdoc.persistence.models import Base


class NlpRun(Base):
    __tablename__ = "nlp_runs"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'ready', 'failed')", name="ck_nlp_status"),
    )

    job_id: Mapped[str] = mapped_column(
        ForeignKey("structure_runs.job_id", ondelete="CASCADE"), primary_key=True
    )
    profile_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(40))
    method: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(8))
    processed: Mapped[int]
    completed_at: Mapped[datetime | None]
    error_code: Mapped[str | None] = mapped_column(String(40))


class ChunkAnnotation(Base):
    __tablename__ = "chunk_annotations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "profile_key"],
            ["nlp_runs.job_id", "nlp_runs.profile_key"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("job_id", "profile_key", "ordinal", name="uq_nlp_chunk_ordinal"),
    )

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), primary_key=True
    )
    profile_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36))
    ordinal: Mapped[int]
    payload: Mapped[dict] = mapped_column(JSON)
