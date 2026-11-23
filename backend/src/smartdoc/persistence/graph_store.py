import hashlib
import logging
from datetime import UTC
from functools import partial
from itertools import batched
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from smartdoc.graph.contracts import GRAPH_VERSION, GraphRevision, GraphStatus, SourceRevision
from smartdoc.graph.projection import MAX_DOCUMENTS, GraphSource, Projection, Projector
from smartdoc.ingestion.contracts import Extraction, ExtractionError
from smartdoc.ncm.candidates import normalized
from smartdoc.ncm.contracts import Snapshot
from smartdoc.persistence.graph_models import (
    GraphEdgeRow,
    GraphEvidence,
    GraphMembership,
    GraphNodeRow,
    GraphVersion,
)
from smartdoc.persistence.ingestion_models import (
    LOCAL_WORKSPACE_ID,
    Document,
    IngestionJob,
    IngestionResult,
)
from smartdoc.persistence.ingestion_store import now
from smartdoc.persistence.ncm_models import NcmSnapshot
from smartdoc.persistence.structure_models import DocumentChunk
from smartdoc.structure.contracts import Chunk

logger = logging.getLogger(__name__)
BATCH_SIZE = 250


def revision(row: GraphVersion) -> GraphRevision:
    return GraphRevision(
        id=row.id,
        sequence=row.sequence,
        version=row.version,
        status=row.status,
        created_at=row.created_at.replace(tzinfo=UTC),
        node_count=row.node_count,
        edge_count=row.edge_count,
        document_count=len(row.sources),
        sources=[SourceRevision.model_validate(item) for item in row.sources],
        error=row.error,
    )


class GraphStore:
    def __init__(self, engine: Engine, profile_key: str, configuration: str) -> None:
        self.engine = engine
        self.profile_key = profile_key
        self.configuration = configuration
        self.scope = hashlib.sha256(
            f"{GRAPH_VERSION}:{profile_key}:{configuration}".encode()
        ).hexdigest()

    def _versions(self) -> Select:
        return select(GraphVersion).where(
            GraphVersion.workspace_id == LOCAL_WORKSPACE_ID, GraphVersion.scope == self.scope
        )

    def status(self) -> GraphStatus:
        with Session(self.engine) as session:
            versions = self._versions().order_by(GraphVersion.sequence.desc()).limit(1)
            latest = session.scalar(versions)
            ready = session.scalar(versions.where(GraphVersion.status == "ready"))
            return GraphStatus(
                latest=revision(latest) if latest else None,
                available_version=ready.id if ready else None,
            )

    def history(self, after: int, limit: int) -> list[GraphRevision]:
        with Session(self.engine) as session:
            rows = session.scalars(
                self._versions()
                .where(GraphVersion.sequence > after)
                .order_by(GraphVersion.sequence)
                .limit(limit)
            )
            return [revision(row) for row in rows]

    def load(self, version_id: UUID | None = None, *, ready: bool = True) -> GraphRevision:
        statement = self._versions()
        if version_id is not None:
            statement = statement.where(GraphVersion.id == str(version_id))
        elif ready:
            statement = statement.where(GraphVersion.status == "ready")
        with Session(self.engine) as session:
            row = session.scalar(statement.order_by(GraphVersion.sequence.desc()).limit(1))
            if row is None:
                if version_id is None:
                    latest = session.scalar(
                        self._versions().order_by(GraphVersion.sequence.desc()).limit(1)
                    )
                    if latest is not None and latest.status == "failed":
                        raise ExtractionError(
                            "graph_failed", "The first graph revision did not build successfully."
                        )
                    raise ExtractionError("graph_pending", "A graph revision is not available yet.")
                raise ExtractionError("not_found", "The graph revision was not found.")
            if ready and row.status != "ready":
                raise ExtractionError(
                    "graph_failed", "This graph revision did not build successfully."
                )
            return revision(row)

    def _input_revisions(self, session: Session) -> list[SourceRevision]:
        latest = (
            select(
                Document.id.label("doc"),
                NcmSnapshot.job_id.label("job"),
                NcmSnapshot.id.label("snapshot"),
                NcmSnapshot.revision.label("revision"),
                func.row_number()
                .over(partition_by=NcmSnapshot.job_id, order_by=NcmSnapshot.revision.desc())
                .label("rank"),
            )
            .join(IngestionJob, IngestionJob.id == NcmSnapshot.job_id)
            .join(Document, Document.id == IngestionJob.document_id)
            .where(
                Document.workspace_id == LOCAL_WORKSPACE_ID,
                NcmSnapshot.profile_key == self.profile_key,
                NcmSnapshot.configuration == self.configuration,
                NcmSnapshot.status == "ready",
            )
            .subquery()
        )
        current = session.execute(
            select(latest.c.doc, latest.c.job, latest.c.snapshot, latest.c.revision)
            .where(latest.c.rank == 1)
            .order_by(latest.c.doc)
            .limit(MAX_DOCUMENTS + 1)
        )
        return [
            SourceRevision(
                document_id=doc, extraction_job_id=job, snapshot_id=snapshot, ncm_revision=rev
            )
            for doc, job, snapshot, rev in current
        ]

    @staticmethod
    def _fingerprint(revisions: list[SourceRevision]) -> str:
        return hashlib.sha256(
            "".join(str(row.snapshot_id) for row in revisions).encode()
        ).hexdigest()

    @staticmethod
    def _chunks(
        session: Session, source: SourceRevision, identifiers: set[UUID]
    ) -> dict[UUID, Chunk]:
        result = {}
        for group in batched(sorted(map(str, identifiers)), BATCH_SIZE):
            rows = session.scalars(
                select(DocumentChunk.payload).where(
                    DocumentChunk.job_id == str(source.extraction_job_id),
                    DocumentChunk.id.in_(group),
                )
            )
            for payload in rows:
                chunk = Chunk.model_validate(payload)
                result[chunk.id] = chunk
        return result

    def _project(self, inputs: list[SourceRevision]) -> Projection:
        if len(inputs) > MAX_DOCUMENTS:
            raise ExtractionError("graph_limit", "The collection exceeds the graph document limit.")
        projector = Projector(UUID(LOCAL_WORKSPACE_ID))
        with Session(self.engine) as session:
            for source in inputs:
                row = session.execute(
                    select(Document.filename, NcmSnapshot.payload, IngestionResult.extraction)
                    .join(IngestionJob, IngestionJob.document_id == Document.id)
                    .join(NcmSnapshot, NcmSnapshot.job_id == IngestionJob.id)
                    .join(IngestionResult, IngestionResult.job_id == IngestionJob.id)
                    .where(
                        Document.workspace_id == LOCAL_WORKSPACE_ID,
                        Document.id == str(source.document_id),
                        NcmSnapshot.id == str(source.snapshot_id),
                    )
                ).first()
                if row is None:
                    raise ExtractionError(
                        "invalid_provenance", "A graph input snapshot could not be opened."
                    )
                chunks = partial(self._chunks, session, source)
                projector.sources(
                    GraphSource(
                        revision=source,
                        filename=row.filename,
                        snapshot=Snapshot.model_validate(row.payload),
                        extraction=Extraction.model_validate(row.extraction),
                        chunks=chunks,
                    )
                )
        return projector.projection

    def build_next(self) -> bool:
        with Session(self.engine) as session:
            sources = self._input_revisions(session)
            fingerprint = self._fingerprint(sources)
            previous = session.scalar(
                self._versions().order_by(GraphVersion.sequence.desc()).limit(1)
            )
            if previous and previous.fingerprint == fingerprint:
                return False
        error_code = None
        try:
            contents = self._project(sources)
        except (ExtractionError, ValueError, KeyError, TypeError, IndexError) as error:
            error_code = error.code if isinstance(error, ExtractionError) else "graph_integrity"
            logger.warning("graph_build_failed", extra={"error_type": error_code})
            contents = Projection({}, {})

        with Session(self.engine) as session, session.begin():
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            if self._fingerprint(self._input_revisions(session)) != fingerprint:
                return True
            previous = session.scalar(
                self._versions().order_by(GraphVersion.sequence.desc()).limit(1)
            )
            if previous and previous.fingerprint == fingerprint:
                return False
            graph_id = str(uuid4())
            session.add(
                GraphVersion(
                    id=graph_id,
                    workspace_id=LOCAL_WORKSPACE_ID,
                    scope=self.scope,
                    fingerprint=fingerprint,
                    version=GRAPH_VERSION,
                    status="failed" if error_code else "ready",
                    created_at=now(),
                    sources=[item.model_dump(mode="json") for item in sources],
                    node_count=len(contents.nodes),
                    edge_count=len(contents.edges),
                    error=error_code,
                )
            )
            session.flush()
            if not error_code:
                self._publish(session, graph_id, contents)
        return True

    @staticmethod
    def _publish(session: Session, graph_id: str, projection: Projection) -> None:
        for batch in batched(enumerate(projection.nodes.values(), 1), BATCH_SIZE):
            session.execute(
                insert(GraphNodeRow),
                [
                    {
                        "version_id": graph_id,
                        "id": str(node.id),
                        "ordinal": idx,
                        "kind": node.kind,
                        "search_label": normalized(node.label),
                        "payload": node.model_dump(mode="json"),
                    }
                    for idx, node in batch
                ],
            )
            session.execute(
                insert(GraphMembership),
                [
                    {"version_id": graph_id, "node_id": str(node.id), "document_id": str(document)}
                    for _, node in batch
                    for document in node.document_ids
                ],
            )
        for batch in batched(enumerate(projection.edges.values(), 1), BATCH_SIZE):
            session.execute(
                insert(GraphEdgeRow),
                [
                    {
                        "version_id": graph_id,
                        "id": str(edge.id),
                        "ordinal": idx,
                        "source_id": str(edge.source_id),
                        "target_id": str(edge.target_id),
                        "predicate": edge.predicate,
                        "kind": edge.kind,
                        "method": edge.method,
                        "validation": edge.validation,
                        "traversable": edge.traversable,
                        "payload": edge.model_dump(mode="json"),
                    }
                    for idx, (edge, _) in batch
                ],
            )
            session.execute(
                insert(GraphEvidence),
                [
                    {
                        "version_id": graph_id,
                        "edge_id": str(edge.id),
                        "ordinal": idx,
                        "document_id": str(anchor.document_id),
                        "payload": anchor.model_dump(mode="json"),
                    }
                    for _, (edge, anchors) in batch
                    for idx, anchor in enumerate(anchors, 1)
                ],
            )
