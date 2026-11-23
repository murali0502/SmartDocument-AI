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


class NcmSnapshot(Base):
    __tablename__ = "ncm_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "profile_key"],
            ["nlp_runs.job_id", "nlp_runs.profile_key"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "job_id", "profile_key", "configuration", "revision", name="uq_ncm_revision"
        ),
        CheckConstraint("status IN ('ready', 'failed')", name="ck_ncm_snapshot_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36))
    profile_key: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int]
    version: Mapped[str] = mapped_column(String(32))
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("ncm_snapshots.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(8))
    completed_at: Mapped[datetime]
    error: Mapped[str | None] = mapped_column(String(40))
    concept_count: Mapped[int]
    assertion_count: Mapped[int]
    audit: Mapped[dict] = mapped_column(JSON)
    payload: Mapped[dict | None] = mapped_column(JSON)
