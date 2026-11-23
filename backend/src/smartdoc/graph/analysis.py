from collections import deque
from uuid import UUID

import networkx as nx

from smartdoc.graph.contracts import (
    Analytics,
    Degree,
    Direction,
    GraphEdge,
    GraphGroup,
    GraphPath,
    Neighborhood,
)
from smartdoc.persistence.graph_queries import Filters, GraphQueries

MAX_ADJACENT = 160
MAX_EXPANSIONS = 400
MAX_SCANNED_EDGES = 5000
MAX_ANALYTIC_NODES = 2000
MAX_ANALYTIC_EDGES = 6000
MAX_GROUPS = 50


def other(edge: GraphEdge, current: UUID) -> UUID:
    return edge.target_id if edge.source_id == current else edge.source_id


def neighborhood(
    graph: GraphQueries,
    root: UUID,
    direction: Direction,
    depth: int,
    limit: int,
    filters: Filters,
) -> Neighborhood:
    graph.require_node(root, filters.document_id)
    seen = {root}
    queue = deque([(root, 0)])
    included = {}
    truncated = False
    while queue:
        node, hops = queue.popleft()
        if hops >= depth:
            continue
        edges = graph.adjacent(node, direction, filters, MAX_ADJACENT + 1)
        if len(edges) > MAX_ADJACENT:
            truncated = True
        for edge in edges[:MAX_ADJACENT]:
            target = other(edge, node)
            if target not in seen:
                if len(seen) >= limit:
                    truncated = True
                    continue
                seen.add(target)
                queue.append((target, hops + 1))
            if edge.id not in included and len(included) >= limit * 4:
                truncated = True
                continue
            included[edge.id] = edge
    nodes = graph.nodes_by_id(seen, filters.document_id)
    return Neighborhood(
        version_id=graph.version_id,
        root=root,
        nodes=[nodes[root], *(nodes[key] for key in sorted(seen - {root}))],
        edges=graph.steps(list(included.values()), filters.document_id),
        truncated=truncated,
    )


def shortest_path(
    graph: GraphQueries,
    source: UUID,
    target: UUID,
    direction: Direction,
    depth: int,
    filters: Filters,
) -> GraphPath:
    graph.require_node(source, filters.document_id)
    if target == source:
        return GraphPath(version_id=graph.version_id, status="found", node_ids=[source], steps=[])
    graph.require_node(target, filters.document_id)
    reached = {source}
    pending = deque([(source, 0)])
    previous: dict[UUID, tuple[UUID, GraphEdge]] = {}
    truncated = False
    expansions = 0
    scanned = 0
    while pending:
        node, hops = pending.popleft()
        if expansions >= MAX_EXPANSIONS or scanned >= MAX_SCANNED_EDGES:
            truncated = True
            break
        expansions += 1
        edges = graph.adjacent(node, direction, filters, MAX_ADJACENT + 1)
        budget = min(MAX_ADJACENT, MAX_SCANNED_EDGES - scanned)
        if len(edges) > budget:
            truncated = True
        scanned += min(len(edges), budget)
        if hops >= depth:
            if any(other(edge, node) not in reached for edge in edges[:budget]):
                truncated = True
            continue
        for edge in edges[:budget]:
            neighbor = other(edge, node)
            if neighbor in reached:
                continue
            reached.add(neighbor)
            previous[neighbor] = (node, edge)
            if neighbor == target:
                path = [target]
                links = []
                while path[-1] != source:
                    parent, incoming = previous[path[-1]]
                    path.append(parent)
                    links.append(incoming)
                return GraphPath(
                    version_id=graph.version_id,
                    status="found",
                    node_ids=path[::-1],
                    steps=graph.steps(links[::-1], filters.document_id),
                    truncated=truncated,
                )
            pending.append((neighbor, hops + 1))
    return GraphPath(
        version_id=graph.version_id,
        status="limit_reached" if truncated else "not_found",
        node_ids=[],
        steps=[],
        truncated=truncated,
    )


def analytics(
    graph: GraphQueries, filters: Filters, limit: int, include_communities: bool
) -> Analytics:
    nodes, edges = graph.analytic_inputs(filters, MAX_ANALYTIC_NODES, MAX_ANALYTIC_EDGES)
    directed = nx.DiGraph()
    directed.add_nodes_from(nodes)
    directed.add_edges_from(edges)
    undirected = directed.to_undirected()
    degree_graph = undirected.copy()
    degree_graph.remove_edges_from(list(nx.selfloop_edges(degree_graph)))

    components = nx.number_connected_components(undirected)
    centrality = (
        nx.degree_centrality(degree_graph)
        if len(degree_graph) > 1
        else dict.fromkeys(degree_graph, 0.0)
    )
    rankings = sorted(degree_graph, key=lambda node: (-degree_graph.degree(node), node))
    degree = [
        Degree(
            node_id=node, degree=degree_graph.degree(node), centrality=round(centrality[node], 6)
        )
        for node in rankings[:limit]
    ]
    cycles = [
        sorted(group)
        for group in nx.strongly_connected_components(directed)
        if len(group) > 1 or directed.has_edge(next(iter(group)), next(iter(group)))
    ]
    cycles.sort()
    communities = []
    if include_communities and degree_graph.number_of_edges() > 0:
        communities = [
            sorted(group)
            for group in nx.algorithms.community.greedy_modularity_communities(degree_graph)
        ]
        communities.sort(key=lambda group: (-len(group), group))
    return Analytics(
        version_id=graph.version_id,
        node_count=directed.number_of_nodes(),
        edge_count=directed.number_of_edges(),
        component_count=components,
        isolated_count=nx.number_of_isolates(undirected),
        degree=degree,
        cycles=[GraphGroup(node_ids=group) for group in cycles[:MAX_GROUPS]],
        communities=[GraphGroup(node_ids=group) for group in communities[:MAX_GROUPS]],
        groups_truncated=len(cycles) > MAX_GROUPS or len(communities) > MAX_GROUPS,
    )
