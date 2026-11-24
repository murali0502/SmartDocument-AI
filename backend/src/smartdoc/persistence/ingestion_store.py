from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from smartdoc.ingestion.contracts import Extraction, ExtractionError
from smartdoc.persistence.ingestion_models import (
    LOCAL_WORKSPACE_ID,
    Document,
    IngestionJob,
    IngestionResult,
)

MAX_ATTEMPTS = 3
PIPELINE_VERSION = "ingestion-v1"


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class Upload:
    path: Path
    filename: str
    format: str
    digest: str
    size_bytes: int


@dataclass(frozen=True)
class Claim:
    job_id: str
    token: str
    path: Path
    format: str


class IngestionStore:
    def __init__(self, engine: Engine, storage: Path) -> None:
        self.engine = engine
        self.storage = storage

    def original_path(self, digest: str) -> Path:
        return self.storage / "originals" / LOCAL_WORKSPACE_ID / digest[:2] / digest

    def accept(self, upload: Upload) -> tuple[Document, IngestionJob, bool]:
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            # Serialize deduplication and installation of the content-addressed blob.
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            previous = session.execute(
                select(Document, IngestionJob)
                .join(IngestionJob)
                .where(
                    Document.workspace_id == LOCAL_WORKSPACE_ID, Document.sha256 == upload.digest
                )
            ).first()
            original = self.original_path(upload.digest)
            if previous and original.is_file():
                return previous[0], previous[1], True

            original.parent.mkdir(parents=True, exist_ok=True)
            # A failed commit can leave an unreferenced blob. A retry replaces it.
            upload.path.replace(original)
            if previous:
                return previous[0], previous[1], True

            created_at = now()
            document = Document(
                id=str(uuid4()),
                workspace_id=LOCAL_WORKSPACE_ID,
                filename=upload.filename,
                format=upload.format,
                sha256=upload.digest,
                size_bytes=upload.size_bytes,
                created_at=created_at,
            )
            job = IngestionJob(
                id=str(uuid4()),
                document_id=document.id,
                status="queued",
                attempts=0,
                created_at=created_at,
                pipeline_version=PIPELINE_VERSION,
            )
            session.add(document)
            session.flush()
            session.add(job)
            return document, job, False

    def documents(self, after: str, limit: int) -> list[tuple[Document, IngestionJob]]:
        with Session(self.engine) as session:
            rows = session.execute(
                select(Document, IngestionJob)
                .join(IngestionJob)
                .where(Document.workspace_id == LOCAL_WORKSPACE_ID, Document.id > after)
                .order_by(Document.id)
                .limit(limit)
            )
            return [(document, job) for document, job in rows]

    def original(self, document_id: str) -> tuple[Path, str] | None:
        with Session(self.engine) as session:
            document = session.scalar(
                select(Document).where(
                    Document.id == document_id, Document.workspace_id == LOCAL_WORKSPACE_ID
                )
            )
            if document is None:
                return None
            return self.original_path(document.sha256), document.filename

    def job(self, job_id: str) -> IngestionJob | None:
        with Session(self.engine) as session:
            return session.scalar(
                select(IngestionJob)
                .join(Document)
                .where(IngestionJob.id == job_id, Document.workspace_id == LOCAL_WORKSPACE_ID)
            )

    def extraction(self, document_id: str) -> tuple[str, dict | None] | None:
        with Session(self.engine) as session:
            row = session.execute(
                select(IngestionJob.status, IngestionResult.extraction)
                .join(Document)
                .outerjoin(IngestionResult, IngestionResult.job_id == IngestionJob.id)
                .where(Document.id == document_id, Document.workspace_id == LOCAL_WORKSPACE_ID)
            ).first()
            return (row[0], row[1]) if row else None

    def claim(self, lease_seconds: int) -> Claim | None:
        with Session(self.engine) as session, session.begin():
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            current = now()
            expired = and_(
                IngestionJob.status == "running", IngestionJob.lease_expires_at <= current
            )
            session.execute(
                update(IngestionJob)
                .where(expired, IngestionJob.attempts >= MAX_ATTEMPTS)
                .values(
                    status="failed",
                    error_code="attempts_exhausted",
                    error_message="Processing attempts expired.",
                    finished_at=current,
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
            row = session.execute(
                select(IngestionJob, Document)
                .join(Document)
                .where(
                    Document.workspace_id == LOCAL_WORKSPACE_ID,
                    or_(IngestionJob.status == "queued", expired),
                )
                .order_by(IngestionJob.created_at, IngestionJob.id)
                .limit(1)
            ).first()
            if not row:
                return None
            job, document = row
            job.status = "running"
            job.lease_token = str(uuid4())
            job.attempts += 1
            job.started_at = current
            job.lease_expires_at = current + timedelta(seconds=lease_seconds)
            return Claim(
                job.id, job.lease_token, self.original_path(document.sha256), document.format
            )

    def finish(self, claim: Claim, outcome: Extraction | ExtractionError) -> bool:
        success = isinstance(outcome, Extraction)
        with Session(self.engine) as session, session.begin():
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            current = now()
            result = session.execute(
                update(IngestionJob)
                .where(
                    IngestionJob.id == claim.job_id,
                    IngestionJob.status == "running",
                    IngestionJob.lease_token == claim.token,
                    IngestionJob.lease_expires_at > current,
                )
                .values(
                    status="succeeded" if success else "failed",
                    finished_at=current,
                    lease_token=None,
                    lease_expires_at=None,
                    error_code=None if success else outcome.code,
                    error_message=None if success else str(outcome)[:255],
                )
            )
            if result.rowcount != 1:
                return False
            if success:
                session.add(
                    IngestionResult(job_id=claim.job_id, extraction=outcome.model_dump(mode="json"))
                )
            return True
