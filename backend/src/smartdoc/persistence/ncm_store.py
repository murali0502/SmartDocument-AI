import hashlib
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import and_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, defer
from sqlalchemy.sql import Select

from smartdoc.ingestion.contracts import Extraction, ExtractionError
from smartdoc.ncm.candidates import Inputs
from smartdoc.ncm.contracts import NCM_VERSION, Snapshot, Weights
from smartdoc.ncm.model import MAX_CHUNKS, build_snapshot
from smartdoc.nlp.contracts import Annotation
from smartdoc.persistence.ingestion_models import (
    LOCAL_WORKSPACE_ID,
    Document,
    IngestionJob,
    IngestionResult,
)
from smartdoc.persistence.ingestion_store import now
from smartdoc.persistence.ncm_models import NcmSnapshot
from smartdoc.persistence.nlp_models import ChunkAnnotation, NlpRun
from smartdoc.persistence.structure_models import DocumentChunk
from smartdoc.structure.contracts import Chunk

logger = logging.getLogger(__name__)
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024


class NcmStore:
    def __init__(self, engine: Engine, profile_key: str, weights: Weights) -> None:
        self.engine = engine
        self.profile_key = profile_key
        self.weights = weights
        self.key = hashlib.sha256(f"{NCM_VERSION}:{weights.model_dump_json()}".encode()).hexdigest()

    def scope(self, job_id: str) -> Select:
        return select(NcmSnapshot).where(
            NcmSnapshot.job_id == job_id,
            NcmSnapshot.profile_key == self.profile_key,
            NcmSnapshot.configuration == self.key,
        )

    def load(
        self, job_id: str, revision: int | None = None, *, content: bool = True
    ) -> NcmSnapshot | None:
        statement = self.scope(job_id)
        if revision is not None:
            statement = statement.where(NcmSnapshot.revision == revision)
        if not content:
            statement = statement.options(defer(NcmSnapshot.payload))
        with Session(self.engine) as session:
            return session.scalar(statement.order_by(NcmSnapshot.revision.desc()).limit(1))

    def history(self, job_id: str, after: int, limit: int) -> list[NcmSnapshot]:
        with Session(self.engine) as session:
            return list(
                session.scalars(
                    self.scope(job_id)
                    .options(defer(NcmSnapshot.payload))
                    .where(NcmSnapshot.revision > after)
                    .order_by(NcmSnapshot.revision)
                    .limit(limit)
                )
            )

    def materialize(self, job_id: str, document_id: UUID) -> Snapshot:
        with Session(self.engine) as session:
            nlp = session.get(NlpRun, (job_id, self.profile_key))
            extraction = session.scalar(
                select(IngestionResult.extraction).where(IngestionResult.job_id == job_id)
            )
            if nlp is None or nlp.status != "ready" or extraction is None:
                raise ExtractionError("ncm_pending", "The source annotations are not ready.")
            if nlp.processed > MAX_CHUNKS:
                raise ExtractionError("ncm_limit", "The document exceeds the NCM chunk limit.")

            def inputs() -> Iterator[Inputs]:
                rows = session.execute(
                    select(DocumentChunk.payload, ChunkAnnotation.payload)
                    .join(ChunkAnnotation, ChunkAnnotation.chunk_id == DocumentChunk.id)
                    .where(
                        DocumentChunk.job_id == job_id,
                        ChunkAnnotation.profile_key == self.profile_key,
                    )
                    .order_by(DocumentChunk.ordinal)
                    .execution_options(yield_per=100)
                )
                count = 0
                for chunk, annotation in rows:
                    count += 1
                    value = Chunk.model_validate(chunk)
                    parsed = Annotation.model_validate(annotation)
                    if (
                        value.id != parsed.chunk_id
                        or value.document_id != document_id
                        or value.ordinal != count
                    ):
                        raise ExtractionError(
                            "invalid_provenance", "Saved annotation identifiers are inconsistent."
                        )
                    yield Inputs(value, parsed)
                if count != nlp.processed:
                    raise ExtractionError(
                        "invalid_provenance", "The annotation snapshot is incomplete."
                    )

            return build_snapshot(
                document_id,
                UUID(job_id),
                Extraction.model_validate(extraction),
                inputs(),
                datetime.now(UTC),
                self.weights,
            )

    def values(
        self,
        job_id: str,
        data: Snapshot | None,
        revision: int,
        parent_id: str | None,
        audit: dict,
        error: str | None = None,
    ) -> dict:
        if data is not None and len(data.model_dump_json().encode()) > MAX_SNAPSHOT_BYTES:
            raise ExtractionError("ncm_limit", "The NCM snapshot exceeds the storage limit.")
        return {
            "id": str(uuid4()),
            "job_id": job_id,
            "profile_key": self.profile_key,
            "configuration": self.key,
            "revision": revision,
            "parent_id": parent_id,
            "version": NCM_VERSION,
            "status": "failed" if error else "ready",
            "completed_at": now(),
            "error": error,
            "concept_count": len(data.concepts) if data else 0,
            "assertion_count": len(data.assertions) if data else 0,
            "audit": audit,
            "payload": data.model_dump(mode="json") if data else None,
        }

    def build_next(self) -> bool:
        with Session(self.engine) as session:
            pending = session.execute(
                select(NlpRun.job_id, Document.id)
                .join(IngestionJob, IngestionJob.id == NlpRun.job_id)
                .join(Document, Document.id == IngestionJob.document_id)
                .outerjoin(
                    NcmSnapshot,
                    and_(
                        NcmSnapshot.job_id == NlpRun.job_id,
                        NcmSnapshot.profile_key == NlpRun.profile_key,
                        NcmSnapshot.configuration == self.key,
                        NcmSnapshot.revision == 1,
                    ),
                )
                .where(
                    Document.workspace_id == LOCAL_WORKSPACE_ID,
                    NlpRun.profile_key == self.profile_key,
                    NlpRun.status == "ready",
                    NcmSnapshot.id.is_(None),
                )
                .order_by(IngestionJob.created_at, IngestionJob.id)
                .limit(1)
            ).first()
        if pending is None:
            return False
        job_id, document_id = pending
        try:
            values = self.values(
                job_id, self.materialize(job_id, UUID(document_id)), 1, None, {"action": "build"}
            )
        except (
            ExtractionError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            ValidationError,
        ) as error:
            code = error.code if isinstance(error, ExtractionError) else "ncm_failed"
            logger.warning("ncm_build_failed", extra={"job_id": job_id, "error_type": code})
            values = self.values(job_id, None, 1, None, {"action": "build"}, error=code)

        with Session(self.engine) as session, session.begin():
            session.execute(
                sqlite_insert(NcmSnapshot)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=[
                        NcmSnapshot.job_id,
                        NcmSnapshot.profile_key,
                        NcmSnapshot.configuration,
                        NcmSnapshot.revision,
                    ]
                )
            )
        return True

    def append(
        self,
        job_id: str,
        expected: int,
        transform: Callable[[NcmSnapshot], Snapshot],
        audit: dict,
    ) -> NcmSnapshot:
        base = self.load(job_id)
        if base is None or base.revision != expected:
            raise ExtractionError(
                "revision_conflict", "Reload the latest concept revision and try again."
            )
        values = self.values(job_id, transform(base), expected + 1, base.id, audit)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            latest = session.scalar(
                self.scope(job_id)
                .options(defer(NcmSnapshot.payload))
                .order_by(NcmSnapshot.revision.desc())
                .limit(1)
            )
            if latest is None or latest.id != base.id:
                raise ExtractionError(
                    "revision_conflict", "Reload the latest concept revision and try again."
                )
            review = NcmSnapshot(**values)
            session.add(review)
            return review
