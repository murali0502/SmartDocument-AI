from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from smartdoc.api.ingestion import require_local
from smartdoc.api.structure import Cursor, Limit
from smartdoc.graph.analysis import analytics, neighborhood, shortest_path
from smartdoc.graph.contracts import (
    Analytics,
    Direction,
    EdgeKind,
    GraphEdge,
    GraphNode,
    GraphPage,
    GraphPath,
    GraphRevision,
    GraphStatus,
    Neighborhood,
    NodeKind,
    View,
)
from smartdoc.ncm.contracts import Anchor, RelationType, Validation
from smartdoc.persistence.graph_queries import Filters, GraphQueries
from smartdoc.persistence.graph_store import GraphStore

router = APIRouter(
    prefix="/api/v1/workspaces/local/graph", tags=["graph"], dependencies=[Depends(require_local)]
)


def store(request: Request, response: Response) -> GraphStore:
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.graph_store


Storage = Annotated[GraphStore, Depends(store)]


def queries(storage: GraphStore, version_id: UUID | None) -> GraphQueries:
    version = storage.load(version_id)
    return GraphQueries(storage.engine, version.id)


def page[T](version: UUID, rows: list[tuple[int, T]], limit: int) -> GraphPage[T]:
    return GraphPage(
        version_id=version,
        items=[value for _, value in rows[:limit]],
        next_cursor=rows[limit - 1][0] if len(rows) > limit else None,
    )


class RevisionPage(BaseModel):
    items: list[GraphRevision]
    next_cursor: int | None


@router.get("")
def status(storage: Storage) -> GraphStatus:
    return storage.status()


@router.get("/versions")
def versions(storage: Storage, after: Cursor = 0, limit: Limit = 25) -> RevisionPage:
    rows = storage.history(after, limit + 1)
    return RevisionPage(
        items=rows[:limit], next_cursor=rows[limit - 1].sequence if len(rows) > limit else None
    )


@router.get("/versions/{version_id}")
def version(version_id: UUID, storage: Storage) -> GraphRevision:
    return storage.load(version_id, ready=False)


@router.get("/nodes")
def nodes(
    storage: Storage,
    version_id: UUID | None = None,
    after: Cursor = 0,
    limit: Limit = 25,
    document_id: UUID | None = None,
    kind: NodeKind | None = None,
    query: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
) -> GraphPage[GraphNode]:
    graph = queries(storage, version_id)
    return page(graph.version_id, graph.nodes(after, limit + 1, document_id, kind, query), limit)


@router.get("/nodes/{node_id}")
def node(
    node_id: UUID, storage: Storage, version_id: UUID | None = None, document_id: UUID | None = None
) -> GraphNode:
    return queries(storage, version_id).require_node(node_id, document_id)


@router.get("/edges")
def edges(
    storage: Storage,
    version_id: UUID | None = None,
    after: Cursor = 0,
    limit: Limit = 25,
    view: View = "all",
    document_id: UUID | None = None,
    node_id: UUID | None = None,
    predicate: RelationType | None = None,
    kind: EdgeKind | None = None,
    validation: Validation | None = None,
) -> GraphPage[GraphEdge]:
    graph = queries(storage, version_id)
    if node_id:
        graph.require_node(node_id, document_id)
    filters = Filters(document_id, predicate, kind, validation, view)
    return page(graph.version_id, graph.edges(filters, after, limit + 1, node_id), limit)


@router.get("/edges/{edge_id}/evidence")
def evidence(
    edge_id: UUID,
    storage: Storage,
    version_id: UUID | None = None,
    after: Cursor = 0,
    limit: Limit = 25,
) -> GraphPage[Anchor]:
    graph = queries(storage, version_id)
    return page(graph.version_id, graph.evidence(edge_id, after, limit + 1), limit)


def navigation_filters(
    document_id: UUID | None = None,
    predicate: RelationType | None = None,
    kind: EdgeKind | None = None,
    view: View = "semantic",
) -> Filters:
    return Filters(document_id=document_id, predicate=predicate, kind=kind, view=view)


Navigation = Annotated[Filters, Depends(navigation_filters)]


@router.get("/neighbors")
def neighbors(
    node_id: UUID,
    storage: Storage,
    filters: Navigation,
    version_id: UUID | None = None,
    direction: Direction = "both",
    depth: Annotated[int, Query(ge=1, le=3)] = 1,
    limit: Limit = 25,
) -> Neighborhood:
    return neighborhood(queries(storage, version_id), node_id, direction, depth, limit, filters)


@router.get("/paths")
def paths(
    source: UUID,
    target: UUID,
    storage: Storage,
    filters: Navigation,
    version_id: UUID | None = None,
    direction: Direction = "out",
    depth: Annotated[int, Query(ge=1, le=8)] = 4,
) -> GraphPath:
    return shortest_path(queries(storage, version_id), source, target, direction, depth, filters)


@router.get("/orphans")
def orphans(
    storage: Storage,
    filters: Navigation,
    version_id: UUID | None = None,
    after: Cursor = 0,
    limit: Limit = 25,
) -> GraphPage[GraphNode]:
    graph = queries(storage, version_id)
    return page(graph.version_id, graph.orphans(filters, after, limit + 1), limit)


@router.get("/analytics")
def metrics(
    storage: Storage,
    filters: Navigation,
    version_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    communities: bool = False,
) -> Analytics:
    return analytics(queries(storage, version_id), filters, limit, communities)
