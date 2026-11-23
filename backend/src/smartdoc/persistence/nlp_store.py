import logging
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.nlp.contracts import Annotation
from smartdoc.nlp.pipeline import NLP_VERSION, LanguagePipeline
from smartdoc.persistence.ingestion_models import LOCAL_WORKSPACE_ID, Document, IngestionJob
from smartdoc.persistence.ingestion_store import now
from smartdoc.persistence.nlp_models import ChunkAnnotation, NlpRun
from smartdoc.persistence.structure_models import DocumentChunk, StructureRun
from smartdoc.structure.contracts import Chunk

logger = logging.getLogger(__name__)
BATCH_SIZE = 12


class NlpStore:
    def __init__(self, engine: Engine, pipeline: LanguagePipeline) -> None:
        self.engine = engine
        self.pipeline = pipeline

    def build_next(self) -> bool:
        key = self.pipeline.key
        with Session(self.engine) as session:
            row = session.execute(
                select(StructureRun.job_id, StructureRun.chunk_count, NlpRun.processed)
                .join(IngestionJob, IngestionJob.id == StructureRun.job_id)
                .join(Document, Document.id == IngestionJob.document_id)
                .outerjoin(
                    NlpRun, and_(NlpRun.job_id == StructureRun.job_id, NlpRun.profile_key == key)
                )
                .where(
                    Document.workspace_id == LOCAL_WORKSPACE_ID,
                    StructureRun.status == "ready",
                    or_(NlpRun.status.is_(None), NlpRun.status == "pending"),
                )
                .order_by(IngestionJob.created_at, IngestionJob.id)
                .limit(1)
            ).first()
        if row is None or not self.pipeline.available:
            return False

        job_id, total, processed = row
        start = processed or 0
        with Session(self.engine) as session:
            payloads = session.scalars(
                select(DocumentChunk.payload)
                .where(DocumentChunk.job_id == job_id, DocumentChunk.ordinal > start)
                .order_by(DocumentChunk.ordinal)
                .limit(BATCH_SIZE)
            ).all()

        error_code = None
        try:
            chunks = [Chunk.model_validate(item) for item in payloads]
            if [chunk.ordinal for chunk in chunks] != list(
                range(start + 1, min(start + BATCH_SIZE, total) + 1)
            ):
                raise ValueError("Invalid chunk ordinal.")
            annotated = list(self.pipeline.annotate_batch(chunks))
        except ExtractionError as error:
            if error.code == "model_unavailable":
                return False
            error_code = error.code
        except (IndexError, ValueError, TypeError, ValidationError):
            error_code = "annotation_failed"
        if error_code:
            annotated = []
        count = start + len(annotated)
        status = "failed" if error_code else "ready" if count == total else "pending"

        with Session(self.engine) as session, session.begin():
            session.execute(
                sqlite_insert(NlpRun)
                .values(
                    job_id=job_id,
                    profile_key=key,
                    status="pending",
                    processed=0,
                    method=self.pipeline.method,
                    version=NLP_VERSION,
                )
                .on_conflict_do_nothing(index_elements=[NlpRun.job_id, NlpRun.profile_key])
            )
            advanced = session.execute(
                update(NlpRun)
                .where(
                    NlpRun.job_id == job_id,
                    NlpRun.profile_key == key,
                    NlpRun.status == "pending",
                    NlpRun.processed == start,
                )
                .values(
                    status=status,
                    processed=count,
                    error_code=error_code,
                    completed_at=None if status == "pending" else now(),
                )
            )
            if advanced.rowcount == 1 and annotated:
                session.execute(
                    insert(ChunkAnnotation),
                    [
                        {
                            "chunk_id": str(item.chunk_id),
                            "profile_key": key,
                            "job_id": job_id,
                            "ordinal": ordinal,
                            "payload": item.model_dump(mode="json"),
                        }
                        for ordinal, item in enumerate(annotated, start + 1)
                    ],
                )
        if error_code:
            logger.warning(
                "nlp_annotation_failed", extra={"job_id": job_id, "error_type": error_code}
            )
        return True

    def run(self, job_id: str) -> NlpRun | None:
        with Session(self.engine) as session:
            return session.get(NlpRun, (job_id, self.pipeline.key))

    def page(self, job_id: str, after: int, limit: int) -> list[tuple[int, Annotation]]:
        with Session(self.engine) as session:
            rows = session.execute(
                select(ChunkAnnotation.ordinal, ChunkAnnotation.payload)
                .where(
                    ChunkAnnotation.job_id == job_id,
                    ChunkAnnotation.profile_key == self.pipeline.key,
                    ChunkAnnotation.ordinal > after,
                )
                .order_by(ChunkAnnotation.ordinal)
                .limit(limit)
            )
            return [(ordinal, Annotation.model_validate(payload)) for ordinal, payload in rows]

    def annotation(self, job_id: str, chunk_id: UUID) -> Annotation | None:
        with Session(self.engine) as session:
            payload = session.scalar(
                select(ChunkAnnotation.payload).where(
                    ChunkAnnotation.chunk_id == str(chunk_id),
                    ChunkAnnotation.job_id == job_id,
                    ChunkAnnotation.profile_key == self.pipeline.key,
                )
            )
            return Annotation.model_validate(payload) if payload is not None else None
