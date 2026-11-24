from collections import defaultdict
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.ncm.candidates import normalized
from smartdoc.ncm.contracts import (
    Alias,
    Anchor,
    Assertion,
    Concept,
    RelationType,
    Snapshot,
    Weights,
)
from smartdoc.ncm.model import definitions, hierarchy, mark_conflicts
from smartdoc.ncm.scoring import rank
from smartdoc.ncm.similarity import duplicate_suggestions

Chronology = Literal["unspecified", "declared_left_before_right"]


def merge(snapshot: Snapshot, source: UUID, target: UUID, weights: Weights) -> Snapshot:
    concepts = {item.id: item for item in snapshot.concepts}
    if source == target or source not in concepts or target not in concepts:
        raise ExtractionError(
            "invalid_review", "A merge requires two distinct concepts in the snapshot."
        )
    original, destination = concepts.pop(source), concepts[target]
    concepts[target] = destination.model_copy(
        update={
            "mentions": destination.mentions + original.mentions,
            "definitions": destination.definitions + original.definitions,
            "deprecation": destination.deprecation + original.deprecation,
            "aliases": destination.aliases
            + original.aliases
            + [
                Alias(
                    surface=original.label,
                    method="review",
                    evidence=[original.mentions[0].evidence, destination.mentions[0].evidence],
                )
            ],
            "sense": None if destination.sense == "unresolved" else destination.sense,
        }
    )
    assertions = []
    for row in snapshot.assertions:
        subject = target if row.subject_id == source else row.subject_id
        obj = target if row.object_id == source else row.object_id
        collapsed = subject == obj and row.subject_id != row.object_id
        state = "rejected" if collapsed else row.validation
        assertions.append(
            row.model_copy(update={"subject_id": subject, "object_id": obj, "validation": state})
        )
    ambiguities = [
        item.model_copy(
            update={
                "alternatives": sorted(
                    {
                        target if candidate == source else candidate
                        for candidate in item.alternatives
                    }
                )
            }
        )
        for item in snapshot.ambiguous_aliases
        if normalized(item.surface) != original.normalized
    ]
    return rebuild_projection(
        snapshot, list(concepts.values()), assertions, weights, ambiguous_aliases=ambiguities
    )


def reject_assertion(snapshot: Snapshot, assertion_id: UUID, weights: Weights) -> Snapshot:
    rejected = next((row for row in snapshot.assertions if row.id == assertion_id), None)
    if not rejected or rejected.validation == "rejected":
        raise ExtractionError("invalid_review", "Choose an assertion that has not been rejected.")
    assertions = [
        row.model_copy(update={"validation": "rejected"}) if row.id == assertion_id else row
        for row in snapshot.assertions
    ]
    return rebuild_projection(snapshot, snapshot.concepts, assertions, weights)


def rebuild_projection(
    snapshot: Snapshot, concepts: list, assertions: list, weights: Weights, **changes
) -> Snapshot:
    checked = mark_conflicts(assertions)
    ordered = rank(definitions(concepts, checked), checked, weights)
    return snapshot.model_copy(
        update={
            "concepts": ordered,
            "assertions": checked,
            "hierarchy": hierarchy(ordered, checked),
            "duplicate_candidates": duplicate_suggestions(ordered),
            **changes,
        }
    )


class Change(BaseModel):
    kind: Literal[
        "only_left",
        "only_right",
        "renamed",
        "merged",
        "definitions_changed",
        "aliases_changed",
        "lifecycle_changed",
    ]
    left_id: UUID | None
    right_id: UUID | None
    left_label: str | None
    right_label: str | None
    left_evidence: list[Anchor]
    right_evidence: list[Anchor]


def compare(left: Snapshot, right: Snapshot) -> list[Change]:
    right_labels = defaultdict(list)
    right_ids = {concept.id: concept for concept in right.concepts}
    review_sources = defaultdict(list)
    same_document = left.document_id == right.document_id
    rename_sources = defaultdict(list)
    left_labels = defaultdict(list)
    for concept in left.concepts:
        left_labels[(concept.normalized, concept.category)].append(concept)
    for concept in right.concepts:
        right_labels[(concept.normalized, concept.category)].append(concept)
        for alias in concept.aliases:
            if same_document and alias.method == "review":
                review_sources[normalized(alias.surface)].append((concept, alias))
            if alias.method == "explicit_rename":
                rename_sources[(normalized(alias.surface), concept.category)].append(
                    (concept, alias)
                )
    results = []
    used = set()

    def change(
        kind: str,
        first: Concept | None,
        second: Concept | None,
        left_evidence: list[Anchor],
        right_evidence: list[Anchor],
    ) -> None:
        results.append(
            Change(
                kind=kind,
                left_id=first.id if first else None,
                right_id=second.id if second else None,
                left_label=first.label if first else None,
                right_label=second.label if second else None,
                left_evidence=left_evidence,
                right_evidence=right_evidence,
            )
        )

    for first in left.concepts:
        key = (first.normalized, first.category)
        matches = right_labels[key]
        renamed = rename_sources[key]
        alias_evidence = []
        action = "renamed"
        reviewed = review_sources[first.normalized]
        if same_document and first.id in right_ids:
            second = right_ids[first.id]
        elif len(reviewed) == 1:
            second, alias = reviewed[0]
            alias_evidence = alias.evidence
            action = "merged"
        elif (
            len(left_labels[key]) == 1
            and len(matches) == 1
            and not first.sense
            and not matches[0].sense
        ):
            second = matches[0]
        elif (
            len(left_labels[key]) == 1
            and len(renamed) == 1
            and not first.sense
            and not renamed[0][0].sense
        ):
            second, alias = renamed[0]
            alias_evidence = alias.evidence
        else:
            change("only_left", first, None, [first.mentions[0].evidence], [])
            continue
        used.add(second.id)
        if alias_evidence:
            change(action, first, second, [first.mentions[0].evidence], alias_evidence)
        if {normalized(item.expression.text) for item in first.definitions} != {
            normalized(item.expression.text) for item in second.definitions
        }:
            change(
                "definitions_changed",
                first,
                second,
                [item.quote for item in first.definitions],
                [item.quote for item in second.definitions],
            )
        if {normalized(item.surface) for item in first.aliases} != {
            normalized(item.surface) for item in second.aliases
        }:
            change(
                "aliases_changed",
                first,
                second,
                [anchor for item in first.aliases for anchor in item.evidence],
                [anchor for item in second.aliases for anchor in item.evidence],
            )
        if bool(first.deprecation) != bool(second.deprecation):
            change("lifecycle_changed", first, second, first.deprecation, second.deprecation)
    for second in right.concepts:
        if second.id not in used:
            change("only_right", None, second, [], [second.mentions[0].evidence])
    return results


class OpposingStatements(BaseModel):
    subject: str
    relation: RelationType
    object: str
    left: Anchor
    right: Anchor


def opposing_statements(left: Snapshot, right: Snapshot, limit: int) -> list[OpposingStatements]:
    def indexed(snapshot: Snapshot):
        concepts = {concept.id: concept for concept in snapshot.concepts}
        rows: dict[tuple[tuple, RelationType, tuple, bool], Assertion] = {}
        for assertion in snapshot.assertions:
            if assertion.validation not in {"source_validated", "conflicted"} or assertion.modality:
                continue
            subject, target = concepts.get(assertion.subject_id), concepts.get(assertion.object_id)
            if subject is None or target is None:
                continue
            key = (
                (subject.normalized, subject.category, subject.sense),
                assertion.type,
                (target.normalized, target.category, target.sense),
                assertion.negated,
            )
            rows.setdefault(key, assertion)
        return rows

    opposite = indexed(right)
    results = []
    for (subject, relation, target, negated), assertion in indexed(left).items():
        match = opposite.get((subject, relation, target, not negated))
        if match is not None:
            results.append(
                OpposingStatements(
                    subject=subject[0],
                    relation=relation,
                    object=target[0],
                    left=assertion.evidence,
                    right=match.evidence,
                )
            )
            if len(results) == limit:
                break
    return results
