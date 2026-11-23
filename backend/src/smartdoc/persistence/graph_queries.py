from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from smartdoc.graph.contracts import (
    Direction,
    EdgeKind,
    EdgeStep,
    GraphEdge,
    GraphNode,
    NodeKind,
    View,
)
from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.ncm.candidates import normalized
from smartdoc.ncm.contracts import Anchor, RelationType, Validation
from smartdoc.persistence.graph_models import (
    GraphEdgeRow,
    GraphEvidence,
    GraphMembership,
    GraphNodeRow,
)


@dataclass(frozen=True)
class Filters:
    document_id: UUID | None = None
    predicate: RelationType | None = None
    kind: EdgeKind | None = None
    validation: Validation | None = None
    view: View = "semantic"


class GraphQueries:
    def __init__(self, engine: Engine, version_id: UUID) -> None:
        self.engine = engine
        self.version_id = version_id
        self.version = str(version_id)

    def _nodes(self, document_id: UUID | None) -> Select:
        statement = select(GraphNodeRow).where(GraphNodeRow.version_id == self.version)
        if document_id is not None:
            contained = select(GraphMembership.node_id).where(
                GraphMembership.version_id == self.version,
                GraphMembership.document_id == str(document_id),
            )
            statement = statement.where(GraphNodeRow.id.in_(contained))
        return statement

    def nodes(
        self,
        after: int,
        limit: int,
        document_id: UUID | None = None,
        kind: NodeKind | None = None,
        query: str | None = None,
    ) -> list[tuple[int, GraphNode]]:
        statement = self._nodes(document_id).where(GraphNodeRow.ordinal > after)
        if kind is not None:
            statement = statement.where(GraphNodeRow.kind == kind)
        if query and (key := normalized(query)):
            statement = statement.where(GraphNodeRow.search_label.contains(key, autoescape=True))
        with Session(self.engine) as session:
            return [
                (row.ordinal, GraphNode.model_validate(row.payload))
                for row in session.scalars(statement.order_by(GraphNodeRow.ordinal).limit(limit))
            ]

    def require_node(self, node_id: UUID, document_id: UUID | None = None) -> GraphNode:
        result = self.nodes_by_id({node_id}, document_id)
        if node_id not in result:
            raise ExtractionError("not_found", "The graph node was not found in this scope.")
        return result[node_id]

    def nodes_by_id(self, ids: set[UUID], document_id: UUID | None) -> dict[UUID, GraphNode]:
        if not ids:
            return {}
        with Session(self.engine) as session:
            rows = session.scalars(
                self._nodes(document_id).where(GraphNodeRow.id.in_(map(str, ids)))
            )
            return {UUID(row.id): GraphNode.model_validate(row.payload) for row in rows}

    def _edges(self, filters: Filters, *, traverse: bool = False) -> Select:
        statement = select(GraphEdgeRow).where(GraphEdgeRow.version_id == self.version)
        if filters.view == "semantic":
            statement = statement.where(
                GraphEdgeRow.kind != "provenance", GraphEdgeRow.method != "section_membership"
            )
        elif filters.view == "dependencies":
            statement = statement.where(
                GraphEdgeRow.kind == "assertion",
                GraphEdgeRow.predicate.in_(("REQUIRES", "DEPENDS_ON")),
            )
        if traverse:
            statement = statement.where(GraphEdgeRow.traversable.is_(True))
        if filters.predicate is not None:
            statement = statement.where(GraphEdgeRow.predicate == filters.predicate)
        if filters.kind is not None:
            statement = statement.where(GraphEdgeRow.kind == filters.kind)
        if filters.validation is not None:
            statement = statement.where(GraphEdgeRow.validation == filters.validation)
        if filters.document_id is not None:
            selected = select(GraphEvidence.edge_id).where(
                GraphEvidence.version_id == self.version,
                GraphEvidence.document_id == str(filters.document_id),
            )
            statement = statement.where(GraphEdgeRow.id.in_(selected))
        return statement

    def edges(
        self, filters: Filters, after: int, limit: int, node_id: UUID | None = None
    ) -> list[tuple[int, GraphEdge]]:
        statement = self._edges(filters).where(GraphEdgeRow.ordinal > after)
        if node_id:
            key = str(node_id)
            statement = statement.where(
                or_(GraphEdgeRow.source_id == key, GraphEdgeRow.target_id == key)
            )
        with Session(self.engine) as session:
            return [
                (row.ordinal, GraphEdge.model_validate(row.payload))
                for row in session.scalars(statement.order_by(GraphEdgeRow.ordinal).limit(limit))
            ]

    def evidence(self, edge_id: UUID, after: int, limit: int) -> list[tuple[int, Anchor]]:
        with Session(self.engine) as session:
            exists = session.get(GraphEdgeRow, (self.version, str(edge_id)))
            if exists is None:
                raise ExtractionError("not_found", "The graph edge was not found in this revision.")
            rows = session.scalars(
                select(GraphEvidence)
                .where(
                    GraphEvidence.version_id == self.version,
                    GraphEvidence.edge_id == str(edge_id),
                    GraphEvidence.ordinal > after,
                )
                .order_by(GraphEvidence.ordinal)
                .limit(limit)
            )
            return [(row.ordinal, Anchor.model_validate(row.payload)) for row in rows]

    def adjacent(
        self, node_id: UUID, direction: Direction, filters: Filters, limit: int
    ) -> list[GraphEdge]:
        key = str(node_id)
        source, target = GraphEdgeRow.source_id == key, GraphEdgeRow.target_id == key
        matches = (
            source if direction == "out" else target if direction == "in" else or_(source, target)
        )
        statement = self._edges(filters, traverse=True).where(matches)
        with Session(self.engine) as session:
            return [
                GraphEdge.model_validate(row.payload)
                for row in session.scalars(statement.order_by(GraphEdgeRow.ordinal).limit(limit))
            ]

    def steps(self, edges: list[GraphEdge], document_id: UUID | None) -> list[EdgeStep]:
        if not edges:
            return []
        statement = select(GraphEvidence).where(
            GraphEvidence.version_id == self.version,
            GraphEvidence.edge_id.in_([str(edge.id) for edge in edges]),
        )
        if document_id:
            statement = statement.where(GraphEvidence.document_id == str(document_id))
        examples = {}
        with Session(self.engine) as session:
            for row in session.scalars(
                statement.order_by(GraphEvidence.edge_id, GraphEvidence.ordinal)
            ):
                examples.setdefault(UUID(row.edge_id), row.payload)
        if any(edge.id not in examples for edge in edges):
            raise ExtractionError(
                "graph_integrity", "A graph path contains an edge without evidence."
            )
        return [
            EdgeStep(edge=edge, evidence=Anchor.model_validate(examples[edge.id])) for edge in edges
        ]

    def orphans(self, filters: Filters, after: int, limit: int) -> list[tuple[int, GraphNode]]:
        connected = (
            self._edges(filters, traverse=True)
            .with_only_columns(GraphEdgeRow.source_id, GraphEdgeRow.target_id)
            .subquery()
        )
        incident = (
            select(connected.c.source_id)
            .where(
                or_(
                    connected.c.source_id == GraphNodeRow.id,
                    connected.c.target_id == GraphNodeRow.id,
                )
            )
            .exists()
        )
        statement = self._nodes(filters.document_id).where(
            GraphNodeRow.ordinal > after,
            GraphNodeRow.kind.not_in(("document", "section", "chunk", "definition")),
            ~incident,
        )
        with Session(self.engine) as session:
            return [
                (row.ordinal, GraphNode.model_validate(row.payload))
                for row in session.scalars(statement.order_by(GraphNodeRow.ordinal).limit(limit))
            ]

    def analytic_inputs(
        self, filters: Filters, max_nodes: int, max_edges: int
    ) -> tuple[list[UUID], list[tuple[UUID, UUID]]]:
        nodes = self._nodes(filters.document_id).with_only_columns(GraphNodeRow.id)
        if filters.view != "all":
            nodes = nodes.where(GraphNodeRow.kind.not_in(("document", "section", "chunk")))
        edges = self._edges(filters, traverse=True).with_only_columns(
            GraphEdgeRow.source_id, GraphEdgeRow.target_id
        )
        with Session(self.engine) as session:
            identifiers = list(
                session.scalars(nodes.order_by(GraphNodeRow.id).limit(max_nodes + 1))
            )
            relations = list(
                session.execute(edges.order_by(GraphEdgeRow.ordinal).limit(max_edges + 1))
            )
        if len(identifiers) > max_nodes or len(relations) > max_edges:
            raise ExtractionError(
                "graph_query_limit", "Narrow the graph scope before requesting analytics."
            )
        return [UUID(key) for key in identifiers], [
            (UUID(left), UUID(right)) for left, right in relations
        ]
