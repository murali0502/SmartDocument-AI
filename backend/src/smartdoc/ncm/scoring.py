import math

from smartdoc.ncm.contracts import Assertion, Concept, ConceptScore, Weights


def score(concept: Concept, connected: bool, weights: Weights) -> ConceptScore:
    distinct_ranges = {
        (
            item.evidence.source.unit,
            item.evidence.source.field,
            item.evidence.source.start,
            item.evidence.source.end,
        )
        for item in concept.mentions
    }
    signals = {
        "definition": float(any(not item.qualified for item in concept.definitions)),
        "heading": float(any(item.kind == "heading" for item in concept.mentions)),
        "relation": float(connected),
        "entity": float(any(item.kind == "entity" for item in concept.mentions)),
        "frequency": min(3.0, math.log2(1 + len(distinct_ranges))),
    }
    contributions = {
        signal: round(value * getattr(weights, signal), 4) for signal, value in signals.items()
    }
    return ConceptScore(total=round(sum(contributions.values()), 4), features=contributions)


def rank(concepts: list[Concept], assertions: list[Assertion], weights: Weights) -> list[Concept]:
    connected = {
        concept_id
        for row in assertions
        if row.validation == "source_validated"
        for concept_id in (row.subject_id, row.object_id)
    }
    rows = [
        concept.model_copy(update={"score": score(concept, concept.id in connected, weights)})
        for concept in concepts
    ]
    return sorted(
        rows, key=lambda concept: (-concept.score.total, concept.normalized, str(concept.id))
    )
