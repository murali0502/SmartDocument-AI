import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from smartdoc.graph.contracts import (
    GRAPH_VERSION,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    SourceRevision,
)
from smartdoc.ingestion.contracts import Extraction, ExtractionError
from smartdoc.ncm.contracts import Anchor, Concept, RelationType, Snapshot, Validation
from smartdoc.structure.contracts import Chunk, resolve_span

MAX_DOCUMENTS = 100
MAX_NODES = 35_000
MAX_EDGES = 75_000
MAX_EVIDENCE = 100_000
CONCEPT_TYPES: dict[str, NodeKind] = {
    "PERSON": "entity",
    "ORG": "entity",
    "GPE": "entity",
    "LOC": "entity",
    "PRODUCT": "entity",
    "EVENT": "event",
    "METHOD": "method",
    "ALGORITHM": "algorithm",
    "MEASUREMENT": "measurement",
    "ATTRIBUTE": "attribute",
}
NAME_TYPES = re.compile(r"\b(algorithm|method|measurement|attribute)$", re.I)


@dataclass(frozen=True)
class GraphSource:
    revision: SourceRevision
    filename: str
    extraction: Extraction
    snapshot: Snapshot
    chunks: Callable[[set[UUID]], dict[UUID, Chunk]]


@dataclass
class Projection:
    nodes: dict[UUID, GraphNode]
    edges: dict[UUID, tuple[GraphEdge, list[Anchor]]]


def concept_kind(concept: Concept) -> NodeKind:
    if concept.category in CONCEPT_TYPES:
        return CONCEPT_TYPES[concept.category]
    if any(mention.kind == "heading" for mention in concept.mentions):
        return "topic"
    if match := NAME_TYPES.search(concept.label):
        return match[1].casefold()
    return "concept"


def definition_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


class Projector:
    def __init__(self, workspace_id: UUID) -> None:
        self.namespace = uuid5(workspace_id, GRAPH_VERSION)
        self.projection = Projection({}, {})
        self.evidence_count = 0

    def node(
        self, key: UUID, kind: NodeKind, label: str, doc: UUID, category: str | None = None
    ) -> UUID:
        existing = self.projection.nodes.get(key)
        if existing is None:
            if len(self.projection.nodes) >= MAX_NODES:
                raise ExtractionError("graph_limit", "The graph exceeds the node limit.")
            self.projection.nodes[key] = GraphNode(
                id=key, kind=kind, label=label[:240], document_ids=[doc], category=category
            )
        elif existing.kind != kind:
            raise ExtractionError(
                "graph_integrity", "A graph identifier has conflicting node types."
            )
        elif doc not in existing.document_ids:
            existing.document_ids.append(doc)
        return key

    def edge(
        self,
        left: UUID,
        right: UUID,
        predicate: RelationType,
        kind: EdgeKind,
        anchors: list[Anchor],
        method: str,
        *,
        assertion_id: UUID | None = None,
        validation: Validation = "source_validated",
        negated: bool = False,
        modality: str | None = None,
        asserted_at: datetime | None = None,
    ) -> None:
        if not anchors or left not in self.projection.nodes or right not in self.projection.nodes:
            raise ExtractionError("graph_integrity", "A graph edge lacks endpoints or evidence.")
        identity = (
            str(assertion_id)
            if assertion_id and kind == "assertion"
            else (f"{kind}:{left}:{predicate}:{right}:{assertion_id or ''}")
        )
        key = uuid5(self.namespace, identity)
        if key in self.projection.edges:
            return
        self.evidence_count += len(anchors)
        if len(self.projection.edges) >= MAX_EDGES or self.evidence_count > MAX_EVIDENCE:
            raise ExtractionError("graph_limit", "The graph exceeds the edge or evidence limit.")
        edge = GraphEdge(
            id=key,
            source_id=left,
            target_id=right,
            predicate=predicate,
            kind=kind,
            validation=validation,
            negated=negated,
            modality=modality,
            method=method,
            assertion_id=assertion_id,
            asserted_at=asserted_at,
            traversable=validation == "source_validated"
            and not negated
            and modality in {None, "must"},
            evidence_count=len(anchors),
        )
        self.projection.edges[key] = (edge, anchors)

    def sources(self, source: GraphSource) -> None:
        rev = source.revision
        snapshot = source.snapshot
        if snapshot.document_id != rev.document_id:
            raise ExtractionError(
                "invalid_provenance", "An NCM snapshot points to another document."
            )
        local_ids = {item.id for item in snapshot.concepts}
        if len(local_ids) != len(snapshot.concepts) or local_ids.intersection(
            self.projection.nodes
        ):
            raise ExtractionError(
                "graph_integrity", "Concept identifiers must belong to one document."
            )
        if any(
            item.subject_id not in local_ids or item.object_id not in local_ids
            for item in snapshot.assertions
        ):
            raise ExtractionError(
                "graph_integrity", "An assertion points outside its NCM document."
            )
        if any(
            item.child_id not in local_ids or item.parent_id not in local_ids
            for item in snapshot.hierarchy
        ):
            raise ExtractionError(
                "graph_integrity", "A hierarchy link points outside its NCM document."
            )

        anchors = [mention.evidence for item in snapshot.concepts for mention in item.mentions]
        anchors.extend(
            anchor
            for item in snapshot.assertions
            for anchor in (item.subject, item.predicate, item.object, item.evidence)
        )
        anchors.extend(anchor for row in snapshot.hierarchy for anchor in row.evidence)
        anchors.extend(
            anchor
            for item in snapshot.concepts
            for definition in item.definitions
            for anchor in (definition.quote, definition.expression)
        )
        chunks = source.chunks({anchor.chunk_id for anchor in anchors})
        for anchor in anchors:
            chunk = chunks.get(anchor.chunk_id)
            if (
                chunk is None
                or chunk.id != anchor.chunk_id
                or chunk.document_id != rev.document_id
                or anchor.document_id != rev.document_id
                or anchor.extraction_job_id != rev.extraction_job_id
                or anchor.locator != chunk.locator
                or anchor.source.unit != chunk.primary.unit
                or anchor.source.field != chunk.primary.field
                or anchor.source.projection != chunk.primary.projection
                or not chunk.primary.start
                <= anchor.source.start
                < anchor.source.end
                <= chunk.primary.end
                or resolve_span(source.extraction, anchor.source) != anchor.text
            ):
                raise ExtractionError(
                    "invalid_provenance", "Graph evidence does not match its source chunk."
                )

        document = self.node(
            uuid5(self.namespace, f"document:{rev.document_id}"),
            "document",
            source.filename,
            rev.document_id,
        )
        names: dict[tuple[str, str], int] = {}
        for concept in snapshot.concepts:
            key = (concept.normalized, concept.category)
            names[key] = names.get(key, 0) + 1
            self.node(
                concept.id, concept_kind(concept), concept.label, rev.document_id, concept.category
            )

        for concept in snapshot.concepts:
            for mention in concept.mentions:
                anchor = mention.evidence
                chunk = chunks[anchor.chunk_id]
                self.node(chunk.id, "chunk", chunk.text, rev.document_id)
                parent = document
                for section in chunk.section_path:
                    self.node(section.id, "section", section.title, rev.document_id)
                    self.edge(
                        section.id, parent, "PART_OF", "provenance", [anchor], "source_outline"
                    )
                    parent = section.id
                self.edge(chunk.id, parent, "PART_OF", "provenance", [anchor], "source_location")
                self.edge(
                    concept.id, chunk.id, "DERIVED_FROM", "provenance", [anchor], "source_mention"
                )

            qualified = any(item.qualified for item in concept.definitions)
            terms = {definition_key(item.expression.text) for item in concept.definitions}
            align = (
                not qualified
                and len(terms) == 1
                and concept.sense is None
                and names[(concept.normalized, concept.category)] == 1
            )
            for item in concept.definitions:
                if item.qualified:
                    continue
                expression = definition_key(item.expression.text)
                key = (
                    f"shared-definition:{concept.normalized}:{concept.category}:{expression}"
                    if align
                    else f"local-definition:{concept.id}:{expression}"
                )
                definition = self.node(
                    uuid5(self.namespace, key), "definition", item.expression.text, rev.document_id
                )
                self.edge(
                    concept.id,
                    definition,
                    "DEFINED_BY",
                    "definition",
                    [item.quote, item.expression],
                    "exact_definition" if align else "local_definition",
                )

        for assertion in snapshot.assertions:
            self.edge(
                assertion.subject_id,
                assertion.object_id,
                assertion.type,
                "assertion",
                [assertion.evidence],
                assertion.method,
                assertion_id=assertion.id,
                validation=assertion.validation,
                negated=assertion.negated,
                modality=assertion.modality,
                asserted_at=assertion.created_at,
            )
        for link in snapshot.hierarchy:
            predicate = {
                "section": "PART_OF",
                "is_a": "IS_A",
                "part_of": "PART_OF",
                "instance_of": "INSTANCE_OF",
            }[link.kind]
            self.edge(
                link.child_id,
                link.parent_id,
                predicate,
                "hierarchy",
                link.evidence,
                "section_membership" if link.kind == "section" else "semantic_hierarchy",
                assertion_id=link.assertion_id,
            )
