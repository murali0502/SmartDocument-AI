from collections import defaultdict
from itertools import batched
from time import perf_counter
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from smartdoc.graph.contracts import SourceRevision
from smartdoc.ingestion.contracts import Extraction, ExtractionError
from smartdoc.ncm.contracts import Anchor, Snapshot
from smartdoc.nlp.inference import LocalInference
from smartdoc.persistence.graph_models import (
    GraphEdgeRow,
    GraphEvidence,
    GraphNodeRow,
    GraphVersion,
)
from smartdoc.persistence.ingestion_models import (
    LOCAL_WORKSPACE_ID,
    Document,
    IngestionJob,
    IngestionResult,
)
from smartdoc.persistence.ncm_models import NcmSnapshot
from smartdoc.persistence.structure_models import DocumentChunk, StructureRun
from smartdoc.retrieval.contracts import (
    Method,
    SearchDiagnostics,
    SearchHit,
    SearchQuery,
    SearchResponse,
)
from smartdoc.retrieval.ranking import STOP, bm25, matches, rank, tokens
from smartdoc.structure.contracts import Chunk, verify_chunk_source

MAX_CHUNKS = 5000
MAX_DENSE_CHUNKS = 256
MAX_GRAPH_ROWS = 10000


class RetrievalService:
    def __init__(
        self,
        engine: Engine,
        profile: str,
        configuration: str,
        graph_scope: str,
        inference: LocalInference,
    ) -> None:
        self.engine = engine
        self.profile = profile
        self.configuration = configuration
        self.graph_scope = graph_scope
        self.inference = inference

    def search(self, query: SearchQuery) -> SearchResponse:
        start = perf_counter()
        terms = set(tokens(query.query))
        terms = terms - STOP or terms
        methods = [
            method for method in dict.fromkeys(query.methods) if query.weights.get(method, 1)
        ]
        with Session(self.engine) as session:
            # A read transaction keeps chunks, NCM revisions and graph evidence consistent.
            session.execute(text("BEGIN"))
            return self._search(session, query, terms, methods, start)

    def _search(
        self,
        session: Session,
        query: SearchQuery,
        terms: set[str],
        methods: list[Method],
        start: float,
    ) -> SearchResponse:
        statement = (
            select(
                DocumentChunk.id,
                DocumentChunk.payload,
                DocumentChunk.job_id,
                Document.id.label("document_id"),
                Document.filename,
            )
            .join(StructureRun, StructureRun.job_id == DocumentChunk.job_id)
            .join(IngestionJob, IngestionJob.id == DocumentChunk.job_id)
            .join(Document, Document.id == IngestionJob.document_id)
            .where(
                Document.workspace_id == LOCAL_WORKSPACE_ID,
                StructureRun.status == "ready",
                IngestionJob.status == "succeeded",
            )
        )
        if query.document_ids:
            statement = statement.where(Document.id.in_(str(doc) for doc in query.document_ids))
        if query.element_types:
            statement = statement.where(
                DocumentChunk.payload["element_type"].as_string().in_(query.element_types)
            )
        limit = MAX_DENSE_CHUNKS if "dense" in methods else MAX_CHUNKS
        rows = session.execute(
            statement.order_by(Document.filename, Document.sha256, DocumentChunk.ordinal).limit(
                limit + 1
            )
        ).all()
        if len(rows) > limit:
            raise ExtractionError(
                "retrieval_limit",
                f"This search covers more than {limit} chunks. "
                "Select fewer documents or element types.",
            )

        chunks = [Chunk.model_validate(row.payload) for row in rows]
        words = [tokens(chunk.text) for chunk in chunks]
        scores: dict[Method, dict[int, float]] = {method: {} for method in methods}
        graph_version = None
        truncated = 0
        if "bm25" in scores:
            scores["bm25"] = bm25(words, terms)
        if "structure" in scores:
            scores["structure"] = bm25(
                (
                    tokens(
                        " ".join([row.filename, *[section.title for section in chunk.section_path]])
                    )
                    for row, chunk in zip(rows, chunks, strict=True)
                ),
                terms,
            )
        job_ids = {row.job_id for row in rows}
        if job_ids and terms and ("concept" in scores or "graph" in scores):
            snapshots = self._snapshots(session, job_ids)
            indexes = {UUID(row.id): i for i, row in enumerate(rows)}
            if "concept" in scores:
                scores["concept"] = self._concept_scores(snapshots, indexes, terms)
            if "graph" in scores:
                scores["graph"], graph_version = self._graph_scores(
                    session, snapshots, indexes, terms
                )
        if "dense" in scores and chunks and terms:
            scores["dense"], truncated = self._dense_scores(query.query, chunks)

        ordered, fused = rank(
            words, terms, scores, query.weights, query.limit, query.rerank, query.diversity
        )
        hits = []
        invalid = 0
        manifests: dict[str, Extraction] = {}
        for index in ordered:
            chunk, row = chunks[index], rows[index]
            if row.job_id not in manifests:
                manifest = session.get(IngestionResult, row.job_id)
                manifests[row.job_id] = Extraction.model_validate(manifest.extraction)
            try:
                if str(chunk.id) != row.id or str(chunk.document_id) != row.document_id:
                    raise ExtractionError(
                        "invalid_provenance", "Chunk identity differs from its source."
                    )
                evidence = verify_chunk_source(manifests[row.job_id], chunk)
            except ExtractionError:
                invalid += 1
                continue
            hits.append(
                SearchHit(
                    document_id=chunk.document_id,
                    filename=row.filename,
                    chunk_id=chunk.id,
                    locator=chunk.locator,
                    section_path=chunk.section_path,
                    element_type=chunk.element_type,
                    evidence=evidence,
                    source_url=f"/api/v1/workspaces/local/documents/{chunk.document_id}/chunks/{chunk.id}/source",
                    score=fused[index],
                    method_scores={
                        method: values[index]
                        for method, values in scores.items()
                        if index in values
                    },
                )
            )
            if len(hits) == query.limit:
                break
        return SearchResponse(
            items=hits,
            diagnostics=SearchDiagnostics(
                query_terms=sorted(terms),
                methods=methods,
                candidate_counts={m: len(v) for m, v in scores.items()},
                corpus_chunks=len(rows),
                ranked_candidates=len(ordered),
                invalid_sources=invalid,
                duration_ms=round((perf_counter() - start) * 1000, 2),
                graph_version=graph_version,
                dense_truncated=truncated,
            ),
        )

    def _snapshots(self, session: Session, job_ids: set[str]) -> list[NcmSnapshot]:
        latest = (
            select(NcmSnapshot.job_id, func.max(NcmSnapshot.revision).label("revision"))
            .where(
                NcmSnapshot.job_id.in_(job_ids),
                NcmSnapshot.profile_key == self.profile,
                NcmSnapshot.configuration == self.configuration,
                NcmSnapshot.status == "ready",
            )
            .group_by(NcmSnapshot.job_id)
            .subquery()
        )
        return list(
            session.scalars(
                select(NcmSnapshot)
                .join(
                    latest,
                    (latest.c.job_id == NcmSnapshot.job_id)
                    & (latest.c.revision == NcmSnapshot.revision),
                )
                .where(
                    NcmSnapshot.profile_key == self.profile,
                    NcmSnapshot.configuration == self.configuration,
                )
            )
        )

    @staticmethod
    def _concept_scores(
        snapshots: list[NcmSnapshot], indexes: dict[UUID, int], terms: set[str]
    ) -> dict[int, float]:
        scores: dict[int, float] = defaultdict(float)
        for row in snapshots:
            for concept in Snapshot.model_validate(row.payload).concepts:
                labels = [concept.label, *(alias.surface for alias in concept.aliases)]
                if any(matches(terms, label) for label in labels):
                    mentions = {mention.evidence.chunk_id for mention in concept.mentions}
                    definitions = {definition.quote.chunk_id for definition in concept.definitions}
                    for chunk in (mentions | definitions) & indexes.keys():
                        scores[indexes[chunk]] += 2 if chunk in definitions else 1
        return dict(scores)

    def _graph_scores(
        self,
        session: Session,
        snapshots: list[NcmSnapshot],
        indexes: dict[UUID, int],
        terms: set[str],
    ) -> tuple[dict[int, float], UUID | None]:
        version = session.scalar(
            select(GraphVersion)
            .where(
                GraphVersion.workspace_id == LOCAL_WORKSPACE_ID,
                GraphVersion.scope == self.graph_scope,
                GraphVersion.status == "ready",
            )
            .order_by(GraphVersion.sequence.desc())
            .limit(1)
        )
        if not version:
            return {}, None
        current = {row.id for row in snapshots}
        documents = {
            str(source.document_id)
            for payload in version.sources
            if str((source := SourceRevision.model_validate(payload)).snapshot_id) in current
        }
        if (
            not documents
            or version.node_count > MAX_GRAPH_ROWS
            or version.edge_count > MAX_GRAPH_ROWS
        ):
            return {}, None
        nodes = session.scalars(
            select(GraphNodeRow).where(
                GraphNodeRow.version_id == version.id,
                GraphNodeRow.kind.not_in(("document", "section", "chunk", "definition")),
            )
        )
        seeds = {
            node.id
            for node in nodes
            if documents.intersection(node.payload["document_ids"])
            and matches(terms, node.payload["label"])
        }
        if not seeds:
            return {}, UUID(version.id)
        rows = session.execute(
            select(GraphEvidence.payload, GraphEdgeRow.id)
            .join(
                GraphEdgeRow,
                (GraphEdgeRow.version_id == GraphEvidence.version_id)
                & (GraphEdgeRow.id == GraphEvidence.edge_id),
            )
            .where(
                GraphEvidence.version_id == version.id,
                GraphEvidence.document_id.in_(documents),
                GraphEdgeRow.traversable.is_(True),
                GraphEdgeRow.kind.in_(("assertion", "hierarchy")),
                (GraphEdgeRow.source_id.in_(seeds) | GraphEdgeRow.target_id.in_(seeds)),
            )
        )
        edges: dict[int, set[str]] = defaultdict(set)
        for payload, edge_id in rows:
            chunk = Anchor.model_validate(payload).chunk_id
            if chunk in indexes:
                edges[indexes[chunk]].add(edge_id)
        return {index: float(len(ids)) for index, ids in edges.items()}, UUID(version.id)

    def _dense_scores(self, query: str, chunks: list[Chunk]) -> tuple[dict[int, float], int]:
        (query_vector,), truncated = self.inference.embed([query])
        scores = {}
        count = int(truncated[0])
        for batch in batched(enumerate(chunks), 16):
            vectors, flags = self.inference.embed([chunk.text for _, chunk in batch])
            count += sum(flags)
            for (index, _), vector in zip(batch, vectors, strict=True):
                scores[index] = sum(a * b for a, b in zip(query_vector, vector, strict=True))
        return scores, count
