from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from smartdoc.ncm.contracts import Anchor, RelationType, Validation

GRAPH_VERSION = "graph-v1"
NodeKind = Literal[
    "document",
    "section",
    "chunk",
    "concept",
    "entity",
    "definition",
    "method",
    "algorithm",
    "event",
    "attribute",
    "measurement",
    "topic",
]
EdgeKind = Literal["assertion", "hierarchy", "provenance", "definition"]
Direction = Literal["out", "in", "both"]
View = Literal["semantic", "dependencies", "all"]


class SourceRevision(BaseModel):
    document_id: UUID
    extraction_job_id: UUID
    snapshot_id: UUID
    ncm_revision: int


class GraphNode(BaseModel):
    id: UUID
    kind: NodeKind
    label: str
    category: str | None = None
    document_ids: list[UUID]


class GraphEdge(BaseModel):
    id: UUID
    source_id: UUID
    target_id: UUID
    predicate: RelationType
    kind: EdgeKind
    validation: Validation
    negated: bool = False
    modality: str | None = None
    method: str
    assertion_id: UUID | None = None
    asserted_at: datetime | None = None
    traversable: bool
    evidence_count: int = Field(ge=1)


class GraphRevision(BaseModel):
    id: UUID
    sequence: int
    version: str = GRAPH_VERSION
    status: Literal["ready", "failed"]
    created_at: datetime
    document_count: int
    node_count: int
    edge_count: int
    error: str | None = None
    sources: list[SourceRevision]


class GraphStatus(BaseModel):
    latest: GraphRevision | None
    available_version: UUID | None


class GraphPage[T](BaseModel):
    version_id: UUID
    items: list[T]
    next_cursor: int | None


class EdgeStep(BaseModel):
    edge: GraphEdge
    evidence: Anchor


class Neighborhood(BaseModel):
    version_id: UUID
    root: UUID
    nodes: list[GraphNode]
    edges: list[EdgeStep]
    truncated: bool


class GraphPath(BaseModel):
    version_id: UUID
    status: Literal["found", "not_found", "limit_reached"]
    node_ids: list[UUID]
    steps: list[EdgeStep]
    truncated: bool = False


class Degree(BaseModel):
    node_id: UUID
    degree: int
    centrality: float


class GraphGroup(BaseModel):
    node_ids: list[UUID]


class Analytics(BaseModel):
    version_id: UUID
    node_count: int
    edge_count: int
    component_count: int
    isolated_count: int
    degree: list[Degree]
    cycles: list[GraphGroup]
    communities: list[GraphGroup]
    groups_truncated: bool
