from collections import defaultdict, deque
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from smartdoc.ncm.contracts import Assertion

Direction = Literal["prerequisites", "impact"]
MAX_PATHS = 200


class DependencyPath(BaseModel):
    concept_ids: list[UUID]
    assertion_ids: list[UUID]
    depth: int


class DependencyCycle(BaseModel):
    concepts: list[UUID]
    assertions: list[UUID]


class DependencyView(BaseModel):
    direction: Direction
    paths: list[DependencyPath]
    cycles: list[DependencyCycle]
    truncated: bool


def usable(assertion: Assertion) -> bool:
    return (
        assertion.validation == "source_validated"
        and not assertion.negated
        and assertion.modality in {None, "must"}
        and assertion.type in {"REQUIRES", "DEPENDS_ON"}
    )


def cycles_within(
    nodes: set[UUID],
    adjacency: dict[UUID, list[tuple[UUID, UUID]]],
) -> list[DependencyCycle]:
    previous = defaultdict(list)
    for origin in nodes:
        for target, _ in adjacency[origin]:
            if target in nodes:
                previous[target].append(origin)

    visited = set()
    order = []
    for start in sorted(nodes):
        if start in visited:
            continue
        stack = [(start, False)]
        while stack:
            current, exiting = stack.pop()
            if exiting:
                order.append(current)
            elif current not in visited:
                visited.add(current)
                stack.append((current, True))
                stack.extend((node, False) for node, _ in adjacency[current] if node in nodes)
    visited.clear()
    groups = []
    for start in reversed(order):
        if start in visited:
            continue
        visited.add(start)
        component = {start}
        pending = [start]
        while pending:
            for node in previous[pending.pop()]:
                if node not in visited:
                    pending.append(node)
                    component.add(node)
                    visited.add(node)
        if len(component) > 1 or any(target == start for target, _ in adjacency[start]):
            groups.append(
                DependencyCycle(
                    concepts=sorted(component),
                    assertions=sorted(
                        {
                            edge
                            for node in component
                            for target, edge in adjacency[node]
                            if target in component
                        }
                    ),
                )
            )
    return groups


def dependency_view(
    relations: list[Assertion],
    root: UUID,
    direction: Direction,
    max_depth: int,
) -> DependencyView:
    adjacency = defaultdict(list)
    for item in relations:
        if usable(item):
            origin, target = (
                (item.subject_id, item.object_id)
                if direction == "prerequisites"
                else (item.object_id, item.subject_id)
            )
            adjacency[origin].append((target, item.id))
    for items in adjacency.values():
        items.sort()
    seen = {root}
    paths = []
    pending = deque([([root], [])])
    truncated = False
    while pending:
        chain, edges = pending.popleft()
        for target, edge in adjacency[chain[-1]]:
            if target in seen:
                continue
            if len(edges) >= max_depth or len(paths) >= MAX_PATHS:
                truncated = True
                continue
            seen.add(target)
            next_path, next_edges = chain + [target], edges + [edge]
            paths.append(
                DependencyPath(
                    concept_ids=next_path, assertion_ids=next_edges, depth=len(next_edges)
                )
            )
            pending.append((next_path, next_edges))
    return DependencyView(
        direction=direction, paths=paths, cycles=cycles_within(seen, adjacency), truncated=truncated
    )
