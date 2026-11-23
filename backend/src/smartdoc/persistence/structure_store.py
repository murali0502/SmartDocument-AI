import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import batched
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import insert, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from smartdoc.ingestion.contracts import Extraction, ExtractionError
from smartdoc.persistence.ingestion_models import (
    LOCAL_WORKSPACE_ID,
    Document,
    IngestionJob,
    IngestionResult,
)
from smartdoc.persistence.ingestion_store import now
from smartdoc.persistence.structure_models import DocumentChunk, StructureElement, StructureRun
from smartdoc.structure.builder import Structure, build_structure
from smartdoc.structure.contracts import STRUCTURE_VERSION, Chunk, Element

logger = logging.getLogger(__name__)
BATCH_SIZE = 300


@dataclass(frozen=True)
class State:
    job_id: str
    ingestion_status: str
    run: StructureRun | None


class StructureStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def build_next(self) -> bool:
        with Session(self.engine) as session:
            row = session.execute(
                select(IngestionJob.id, Document.id, IngestionResult.extraction)
                .join(Document)
                .join(IngestionResult, IngestionResult.job_id == IngestionJob.id)
                .outerjoin(StructureRun, StructureRun.job_id == IngestionJob.id)
                .where(
                    Document.workspace_id == LOCAL_WORKSPACE_ID,
                    IngestionJob.status == "succeeded",
                    StructureRun.job_id.is_(None),
                )
                .order_by(IngestionJob.created_at, IngestionJob.id)
                .limit(1)
            ).first()
        if row is None:
            return False

        job_id, document_id, manifest = row
        started = datetime.now(UTC)
        error_code = None
        structure = Structure([], [])
        try:
            structure = build_structure(
                UUID(document_id), UUID(job_id), Extraction.model_validate(manifest), started
            )
        except ExtractionError as error:
            error_code = error.code
        except (IndexError, KeyError, TypeError, ValueError, ValidationError):
            error_code = "invalid_manifest"

        with Session(self.engine) as session, session.begin():
            inserted = session.execute(
                sqlite_insert(StructureRun)
                .values(
                    job_id=job_id,
                    version=STRUCTURE_VERSION,
                    status="failed" if error_code else "ready",
                    completed_at=now(),
                    element_count=len(structure.elements),
                    chunk_count=len(structure.chunks),
                    error_code=error_code,
                )
                .on_conflict_do_nothing(index_elements=[StructureRun.job_id])
            )
            if inserted.rowcount == 1 and not error_code:
                self._publish(session, job_id, structure)
        if error_code:
            logger.warning(
                "structure_build_failed", extra={"job_id": job_id, "error_type": error_code}
            )
        return True

    @staticmethod
    def _publish(session: Session, job_id: str, structure: Structure) -> None:
        for batch in batched(structure.elements, BATCH_SIZE):
            session.execute(
                insert(StructureElement),
                [
                    {
                        "id": str(element.id),
                        "job_id": job_id,
                        "ordinal": element.ordinal,
                        "parent_id": str(element.parent_id) if element.parent_id else None,
                        "payload": element.model_dump(mode="json"),
                    }
                    for element in batch
                ],
            )
        for batch in batched(structure.chunks, BATCH_SIZE):
            session.execute(
                insert(DocumentChunk),
                [
                    {
                        "id": str(chunk.id),
                        "job_id": job_id,
                        "ordinal": chunk.ordinal,
                        "element_id": str(chunk.parent_element_id),
                        "payload": chunk.model_dump(mode="json"),
                    }
                    for chunk in batch
                ],
            )

    def state(self, document_id: UUID) -> State | None:
        with Session(self.engine) as session:
            row = session.execute(
                select(IngestionJob.id, IngestionJob.status, StructureRun)
                .join(Document)
                .outerjoin(StructureRun, StructureRun.job_id == IngestionJob.id)
                .where(Document.id == str(document_id), Document.workspace_id == LOCAL_WORKSPACE_ID)
            ).first()
            return State(*row) if row else None

    def elements(self, job_id: str, after: int, limit: int) -> list[Element]:
        with Session(self.engine) as session:
            contained = session.scalars(
                select(StructureElement.payload)
                .where(StructureElement.job_id == job_id, StructureElement.ordinal > after)
                .order_by(StructureElement.ordinal)
                .limit(limit)
            )
            return [Element.model_validate(payload) for payload in contained]

    def chunks(self, job_id: str, after: int, limit: int) -> list[Chunk]:
        with Session(self.engine) as session:
            contained = session.scalars(
                select(DocumentChunk.payload)
                .where(DocumentChunk.job_id == job_id, DocumentChunk.ordinal > after)
                .order_by(DocumentChunk.ordinal)
                .limit(limit)
            )
            return [Chunk.model_validate(payload) for payload in contained]

    def source(self, job_id: str, chunk_id: UUID) -> tuple[Chunk, Extraction] | None:
        with Session(self.engine) as session:
            row = session.execute(
                select(DocumentChunk.payload, IngestionResult.extraction)
                .join(IngestionResult, IngestionResult.job_id == DocumentChunk.job_id)
                .where(DocumentChunk.id == str(chunk_id), DocumentChunk.job_id == job_id)
            ).first()
            if row is None:
                return None
            return Chunk.model_validate(row[0]), Extraction.model_validate(row[1])
